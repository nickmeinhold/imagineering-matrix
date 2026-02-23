"""Configuration parsed from environment variables."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RelayConfig:
    """Relay appservice configuration.

    All values are read from environment variables via :meth:`from_env`.

    Environment variables:
        RELAY_HOMESERVER_URL: Matrix homeserver URL (e.g. ``http://continuwuity:6167``)
        RELAY_DOMAIN: Matrix server domain (e.g. ``yourdomain.com``)
        RELAY_AS_TOKEN: Appservice token from ``registration.yaml``
        RELAY_HS_TOKEN: Homeserver token from ``registration.yaml``
        RELAY_PORTAL_ROOMS: Portal rooms as ``!room1:domain=WhatsApp,!room2:domain=Signal``
        RELAY_HUB_ROOM_ID: Hub room ID
        RELAY_BOT_LOCALPART: Bot localpart (default: ``relay-bot``)
        RELAY_DB_PATH: SQLite database path (default: ``/data/relay.db``)
    """

    homeserver_url: str
    domain: str
    as_token: str
    hs_token: str
    portal_rooms: dict[str, str]  # room_id -> label
    hub_room_id: str
    bot_localpart: str = "relay-bot"
    db_path: str = "/data/relay.db"

    @classmethod
    def from_env(cls) -> RelayConfig:
        """Parse configuration from environment variables.

        Exits the process if required variables are missing or invalid.
        """
        homeserver_url = _require("RELAY_HOMESERVER_URL")
        domain = _require("RELAY_DOMAIN")
        as_token = _require("RELAY_AS_TOKEN")
        hs_token = _require("RELAY_HS_TOKEN")
        hub_room_id = _require("RELAY_HUB_ROOM_ID")
        portal_rooms = _parse_portal_rooms()
        bot_localpart = os.environ.get("RELAY_BOT_LOCALPART", "relay-bot").strip()
        db_path = os.environ.get("RELAY_DB_PATH", "/data/relay.db").strip()

        return cls(
            homeserver_url=homeserver_url,
            domain=domain,
            as_token=as_token,
            hs_token=hs_token,
            portal_rooms=portal_rooms,
            hub_room_id=hub_room_id,
            bot_localpart=bot_localpart,
            db_path=db_path,
        )


def _require(var: str) -> str:
    """Return the stripped value of *var*, or exit if empty/missing."""
    value = os.environ.get(var, "").strip()
    if not value:
        log.error("%s is required", var)
        sys.exit(1)
    return value


def _parse_portal_rooms() -> dict[str, str]:
    """Parse ``RELAY_PORTAL_ROOMS`` into a ``{room_id: label}`` dict."""
    raw = os.environ.get("RELAY_PORTAL_ROOMS", "").strip()
    if not raw:
        log.error("RELAY_PORTAL_ROOMS is required")
        sys.exit(1)

    portal_rooms: dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        room_id, _, label = entry.partition("=")
        label = label.strip()
        if not label:
            log.error(
                "RELAY_PORTAL_ROOMS entry %r is missing a label "
                "(expected '!room:domain=Label')",
                entry,
            )
            sys.exit(1)
        portal_rooms[room_id.strip()] = label

    if not portal_rooms:
        log.error("RELAY_PORTAL_ROOMS is required")
        sys.exit(1)

    return portal_rooms
