"""Core relay logic using puppet intents.

Routes messages between portal rooms and the hub room, sending via puppet
users so messages appear as the actual sender.  Supports reply threading
via event ID mapping.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .loop_prevention import (
    platform_label,
    should_ignore_in_hub,
    should_ignore_in_portal,
)

if TYPE_CHECKING:
    from mautrix.appservice import AppService

    from .event_map import EventMap
    from .puppet import PuppetManager

log = logging.getLogger(__name__)


class RelayHandler:
    """Routes messages between portal rooms and the hub via puppet intents.

    Args:
        appservice: The mautrix :class:`AppService` instance.
        puppet_manager: Manages puppet user intents.
        portal_rooms: Mapping of portal room IDs to platform labels.
        hub_room_id: The superbridge hub room ID.
        event_map: Optional event ID mapping store for reply/reaction relay.
    """

    def __init__(
        self,
        appservice: AppService,
        puppet_manager: PuppetManager,
        portal_rooms: dict[str, str],
        hub_room_id: str,
        event_map: EventMap | None = None,
    ) -> None:
        self._appservice = appservice
        self._puppet_manager = puppet_manager
        self._portal_rooms = portal_rooms
        self._hub_room_id = hub_room_id
        self._event_map = event_map

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def handle_message(self, event) -> None:
        """Route a message event to the appropriate targets.

        Handles portal->hub, hub->portals, and portal->portal cross-relay.
        """
        room_id: str = event.room_id
        sender: str = event.sender
        body: str = event.content.body
        bot_mxid: str = self._appservice.bot_mxid

        if room_id in self._portal_rooms:
            if should_ignore_in_portal(sender, body, bot_mxid):
                return
            await self._relay_from_portal(event)

        elif room_id == self._hub_room_id:
            if should_ignore_in_hub(sender, body, bot_mxid):
                return
            await self._relay_from_hub(event)

        # Unrelated room -> ignore silently.

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _relay_from_portal(self, event) -> None:
        """Relay a portal message to the hub and to other portal rooms."""
        sender: str = event.sender
        room_id: str = event.room_id
        body: str = event.content.body
        source_event_id: str = event.event_id
        display_name, avatar_url = await self._get_sender_profile(sender)
        source_label = self._portal_rooms[room_id]
        platform = source_label.lower()
        reply_to = self._get_reply_to(event)

        # Portal -> Hub
        target_evt = await self._send_as_puppet(
            platform=platform,
            sender=sender,
            display_name=display_name,
            avatar_url=avatar_url,
            room_id=self._hub_room_id,
            body=body,
            reply_to_source=reply_to,
            target_room_id=self._hub_room_id,
        )
        if target_evt and self._event_map:
            await self._event_map.store(
                source_event_id, room_id, target_evt, self._hub_room_id,
            )

        # Portal -> Other portals (cross-relay)
        for portal_id in self._portal_rooms:
            if portal_id == room_id:
                continue
            target_evt = await self._send_as_puppet(
                platform=platform,
                sender=sender,
                display_name=display_name,
                avatar_url=avatar_url,
                room_id=portal_id,
                body=body,
                reply_to_source=reply_to,
                target_room_id=portal_id,
            )
            if target_evt and self._event_map:
                await self._event_map.store(
                    source_event_id, room_id, target_evt, portal_id,
                )

    async def _relay_from_hub(self, event) -> None:
        """Fan out a hub message to all portal rooms."""
        sender: str = event.sender
        body: str = event.content.body
        source_event_id: str = event.event_id
        room_id: str = event.room_id
        display_name, avatar_url = await self._get_sender_profile(sender)
        platform = platform_label(sender).lower()
        reply_to = self._get_reply_to(event)

        for portal_id in self._portal_rooms:
            target_evt = await self._send_as_puppet(
                platform=platform,
                sender=sender,
                display_name=display_name,
                avatar_url=avatar_url,
                room_id=portal_id,
                body=body,
                reply_to_source=reply_to,
                target_room_id=portal_id,
            )
            if target_evt and self._event_map:
                await self._event_map.store(
                    source_event_id, room_id, target_evt, portal_id,
                )

    async def _send_as_puppet(
        self,
        *,
        platform: str,
        sender: str,
        display_name: str,
        avatar_url: str | None = None,
        room_id: str,
        body: str,
        reply_to_source: str | None = None,
        target_room_id: str | None = None,
    ) -> str | None:
        """Send *body* to *room_id* via a puppet intent.

        If *reply_to_source* is set and a mapping exists in the event map,
        the message is sent as a reply with ``m.in_reply_to``.

        Returns the event ID on success, or ``None`` on failure.
        """
        try:
            intent = await self._puppet_manager.get_intent(
                platform=platform,
                sender=sender,
                display_name=display_name,
                avatar_url=avatar_url,
                room_id=room_id,
            )

            # Check if this is a reply and we have a mapped target event.
            mapped_reply_to = None
            if reply_to_source and self._event_map and target_room_id:
                mapped_reply_to = await self._event_map.lookup(
                    reply_to_source, target_room_id,
                )

            if mapped_reply_to:
                # Send as reply with m.in_reply_to.
                from mautrix.types import (
                    TextMessageEventContent,
                    MessageType,
                    RelatesTo,
                    InReplyTo,
                )
                content = TextMessageEventContent(
                    msgtype=MessageType.TEXT,
                    body=body,
                )
                content.set_reply(mapped_reply_to)
                event_id = await intent.send_message(room_id, content)
            else:
                # Plain text message.
                event_id = await intent.send_text(room_id, text=body)

            log.info("Relayed to %s as %s: %s", room_id, sender, body[:120])
            return event_id
        except Exception:
            log.exception("Failed to relay to %s", room_id)
            return None

    async def handle_reaction(self, event) -> None:
        """Relay a reaction event to all other rooms.

        Looks up the reacted-to event in the event map and sends the same
        reaction via a puppet intent in each target room.
        """
        if not self._event_map:
            return

        sender: str = event.sender
        room_id: str = event.room_id
        bot_mxid: str = self._appservice.bot_mxid

        # Loop prevention: same layers apply.
        if room_id in self._portal_rooms:
            if should_ignore_in_portal(sender, "", bot_mxid):
                return
        elif room_id == self._hub_room_id:
            if should_ignore_in_hub(sender, "", bot_mxid):
                return
        else:
            return

        reacted_to = event.content.relates_to.event_id
        reaction_key = event.content.relates_to.key
        display_name, avatar_url = await self._get_sender_profile(sender)

        # Determine platform and target rooms.
        if room_id in self._portal_rooms:
            source_label = self._portal_rooms[room_id]
            platform = source_label.lower()
            target_rooms = [self._hub_room_id] + [
                p for p in self._portal_rooms if p != room_id
            ]
        else:
            platform = platform_label(sender).lower()
            target_rooms = list(self._portal_rooms)

        for target_room in target_rooms:
            mapped_event = await self._event_map.lookup(reacted_to, target_room)
            if not mapped_event:
                continue
            try:
                intent = await self._puppet_manager.get_intent(
                    platform=platform,
                    sender=sender,
                    display_name=display_name,
                    avatar_url=avatar_url,
                    room_id=target_room,
                )
                await intent.react(target_room, mapped_event, reaction_key)
                log.info(
                    "Relayed reaction %s to %s in %s",
                    reaction_key, mapped_event, target_room,
                )
            except Exception:
                log.exception("Failed to relay reaction to %s", target_room)

    @staticmethod
    def _get_reply_to(event) -> str | None:
        """Extract the replied-to event ID from the event, if any."""
        try:
            relates_to = event.content.relates_to
            if relates_to and relates_to.in_reply_to:
                return relates_to.in_reply_to.event_id
        except (AttributeError, TypeError):
            pass
        return None

    async def _get_sender_profile(self, sender: str) -> tuple[str, str | None]:
        """Fetch the sender's display name and avatar from the homeserver.

        Queries the profile via the appservice bot intent so we get the real
        display name that the mautrix bridge already set (e.g. "Alice") instead
        of the raw MXID localpart (e.g. "signal_1f11a469-eb2d-4c50-…").

        Returns:
            A ``(display_name, avatar_url)`` tuple.  Falls back to the MXID
            localpart and ``None`` if the profile lookup fails.
        """
        try:
            profile = await self._appservice.intent.get_profile(sender)
            display_name = getattr(profile, "displayname", None) or ""
            avatar_url = getattr(profile, "avatar_url", None) or None
            if display_name:
                return display_name, avatar_url
        except Exception:
            log.debug("Profile lookup failed for %s, using localpart", sender)
        return sender.split(":")[0].lstrip("@"), None
