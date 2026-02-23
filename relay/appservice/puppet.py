"""Puppet user management for the relay appservice.

Creates and maintains Matrix puppet users so that relayed messages appear
as the actual sender with their name and avatar, rather than a single bot
account with text attribution.
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING

from mautrix.types import EventType

if TYPE_CHECKING:
    from mautrix.appservice import AppService
    from mautrix.appservice.api import IntentAPI

log = logging.getLogger(__name__)


class PuppetManager:
    """Manages puppet users for the relay appservice.

    Each unique sender gets a deterministic puppet MXID of the form
    ``@_relay_{platform}_{hash8}:{domain}``.  Intents are cached so that
    repeated messages from the same sender reuse the same puppet.
    """

    def __init__(self, appservice: AppService, domain: str) -> None:
        self._appservice = appservice
        self._domain = domain
        # Cache: puppet_mxid -> IntentAPI
        self._intents: dict[str, IntentAPI] = {}
        # Cache: puppet_mxid -> last display name set
        self._display_names: dict[str, str] = {}
        # Cache: puppet_mxid -> last avatar URL set
        self._avatar_urls: dict[str, str | None] = {}
        # Cache: (puppet_mxid, room_id) -> (display_name, avatar_url) last
        # written into the room member state event.  Bridges read the room
        # member event (not the global profile) to get display names and
        # avatars, so we must explicitly keep it in sync.
        self._member_profiles: dict[tuple[str, str], tuple[str, str | None]] = {}

    def mxid_for(self, platform: str, sender: str) -> str:
        """Return a deterministic puppet MXID for *sender* on *platform*.

        The MXID is ``@_relay_{platform}_{hash8}:{domain}`` where *hash8* is
        the first 8 hex characters of the SHA-256 hash of ``{platform}:{sender}``.
        """
        raw = f"{platform}:{sender}"
        hash8 = hashlib.sha256(raw.encode()).hexdigest()[:8]
        return f"@_relay_{platform}_{hash8}:{self._domain}"

    async def get_intent(
        self,
        *,
        platform: str,
        sender: str,
        display_name: str,
        avatar_url: str | None = None,
        room_id: str,
        sync_member_state: bool = False,
    ) -> IntentAPI:
        """Return an :class:`IntentAPI` for the puppet, ensuring it is ready.

        On first call for a puppet:
        - Registers the puppet user on the homeserver.
        - Sets its display name (just the name, no platform suffix).
        - Sets its avatar URL if provided.

        Room join strategy (avoids breaking bridge-managed portal rooms):

        - **First entry** to any room: a single ``m.room.member`` state event
          that both joins the room AND carries the display name and avatar.
          This produces only one member event (not a bare join followed by a
          separate profile update), which is safe for bridge portals.
        - **Subsequent calls**, profile unchanged: ``ensure_joined`` (no-op
          if already in the room; safety net if the puppet was kicked).
        - **Profile changed**, hub room (``sync_member_state=True``):
          re-send the member state event so bridges see the new name/avatar.
        - **Profile changed**, portal room (``sync_member_state=False``):
          only update the global profile; don't re-send member state to
          avoid disrupting bridge-managed rooms.

        Args:
            platform: Platform label in lowercase (e.g. ``"whatsapp"``).
            sender: The original sender's MXID.
            display_name: The sender's display name (no platform suffix).
            avatar_url: The sender's ``mxc://`` avatar URL, or ``None``.
            room_id: The room to ensure the puppet has joined.
            sync_member_state: If True, re-send the ``m.room.member`` state
                event when the profile changes.  Use for rooms we control
                (hub room); portal rooms should pass False.
        """
        mxid = self.mxid_for(platform, sender)

        if mxid not in self._intents:
            intent = self._appservice.intent.user(mxid)
            await intent.ensure_registered()
            await intent.set_displayname(display_name)
            self._intents[mxid] = intent
            self._display_names[mxid] = display_name
            if avatar_url:
                await intent.set_avatar_url(avatar_url)
            self._avatar_urls[mxid] = avatar_url
        else:
            intent = self._intents[mxid]
            if self._display_names.get(mxid) != display_name:
                await intent.set_displayname(display_name)
                self._display_names[mxid] = display_name
            if self._avatar_urls.get(mxid) != avatar_url:
                await intent.set_avatar_url(avatar_url or "")
                self._avatar_urls[mxid] = avatar_url

        # Bridges read display names and avatars from the m.room.member
        # state event, NOT the global profile.  Continuwuity doesn't
        # auto-propagate profile changes into room member events.
        #
        # Strategy: on first entry to a room, send a SINGLE m.room.member
        # state event that both joins AND carries the profile.  This avoids
        # the two-event pattern (bare join + separate state update) that
        # crashed bridge-managed portal rooms.  For subsequent profile
        # changes, only re-sync in the hub room (sync_member_state=True).
        current_profile = (display_name, avatar_url)
        member_key = (mxid, room_id)
        cached = self._member_profiles.get(member_key)

        if cached is None:
            # First entry: single state event = join + profile.
            await self._send_member_event(intent, mxid, room_id, display_name, avatar_url)
            self._member_profiles[member_key] = current_profile
        elif cached != current_profile and sync_member_state:
            # Profile changed in a room we control — re-sync state.
            await self._send_member_event(intent, mxid, room_id, display_name, avatar_url)
            self._member_profiles[member_key] = current_profile
        else:
            # Already joined with current profile (or portal with stale
            # profile).  Just ensure membership as a safety net.
            await intent.ensure_joined(room_id)

        return intent

    @staticmethod
    async def _send_member_event(
        intent: IntentAPI,
        mxid: str,
        room_id: str,
        display_name: str,
        avatar_url: str | None,
    ) -> None:
        """Send a ``m.room.member`` state event that joins with profile info.

        A single event that sets membership, display name, and avatar in one
        shot — avoiding the two-event pattern that breaks bridge portals.
        """
        await intent.send_state_event(
            room_id,
            EventType.ROOM_MEMBER,
            mxid,
            content={
                "membership": "join",
                "displayname": display_name,
                "avatar_url": avatar_url or "",
            },
        )
