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
    ) -> IntentAPI:
        """Return an :class:`IntentAPI` for the puppet, ensuring it is ready.

        On first call for a puppet:
        - Registers the puppet user on the homeserver.
        - Sets its display name (just the name, no platform suffix).
        - Sets its avatar URL if provided.

        On every call:
        - Ensures the puppet has joined *room_id*.
        - Updates the display name or avatar if they have changed.
        - Syncs the room member state event so bridges see the correct
          display name and avatar (they read member state, not the global
          profile).

        Args:
            platform: Platform label in lowercase (e.g. ``"whatsapp"``).
            sender: The original sender's MXID.
            display_name: The sender's display name (no platform suffix).
            avatar_url: The sender's ``mxc://`` avatar URL, or ``None``.
            room_id: The room to ensure the puppet has joined.
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

        await intent.ensure_joined(room_id)

        # Bridges (WhatsApp, Discord, etc.) read display names and avatars
        # from the m.room.member state event, NOT the global profile.
        # Continuwuity doesn't auto-propagate profile changes into room
        # member events, so we explicitly update the state when the profile
        # differs from what we last wrote for this (puppet, room) pair.
        current_profile = (display_name, avatar_url)
        member_key = (mxid, room_id)
        if self._member_profiles.get(member_key) != current_profile:
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
            self._member_profiles[member_key] = current_profile

        return intent
