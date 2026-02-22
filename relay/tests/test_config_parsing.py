"""Acceptance tests for portal room configuration parsing.

Verifies ``parse_portal_rooms()`` handles:
- The new ``PORTAL_ROOMS`` env var format
- Legacy ``WHATSAPP_ROOM_ID`` fallback
- Precedence rules
- Error cases (missing config)
- Whitespace trimming

All tests call ``relay_bot.parse_portal_rooms()`` which does not exist yet —
``AttributeError`` in RED phase.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest


def _clean_env():
    """Return an env dict with portal-related vars removed."""
    env = os.environ.copy()
    for key in ("PORTAL_ROOMS", "WHATSAPP_ROOM_ID", "HUB_ROOM_ID"):
        env.pop(key, None)
    return env


class TestNewFormat:
    """Parsing the new ``PORTAL_ROOMS`` env var."""

    def test_new_format_single_room(self):
        """A single room in PORTAL_ROOMS is parsed correctly."""
        import relay_bot

        env = _clean_env()
        env["PORTAL_ROOMS"] = "!wa:domain=WhatsApp"
        env["HUB_ROOM_ID"] = "!hub:domain"

        with patch.dict(os.environ, env, clear=True):
            portal_rooms, hub_room = relay_bot.parse_portal_rooms()

        assert portal_rooms == {"!wa:domain": "WhatsApp"}
        assert hub_room == "!hub:domain"

    def test_new_format_multiple_rooms(self):
        """Two comma-separated rooms are both parsed."""
        import relay_bot

        env = _clean_env()
        env["PORTAL_ROOMS"] = "!wa:domain=WhatsApp,!sig:domain=Signal"
        env["HUB_ROOM_ID"] = "!hub:domain"

        with patch.dict(os.environ, env, clear=True):
            portal_rooms, hub_room = relay_bot.parse_portal_rooms()

        assert portal_rooms == {
            "!wa:domain": "WhatsApp",
            "!sig:domain": "Signal",
        }
        assert hub_room == "!hub:domain"


class TestLegacyFallback:
    """Falling back to ``WHATSAPP_ROOM_ID`` when ``PORTAL_ROOMS`` is absent."""

    def test_legacy_fallback(self):
        """No PORTAL_ROOMS uses WHATSAPP_ROOM_ID with 'WhatsApp' label."""
        import relay_bot

        env = _clean_env()
        env["WHATSAPP_ROOM_ID"] = "!wa:domain"
        env["HUB_ROOM_ID"] = "!hub:domain"

        with patch.dict(os.environ, env, clear=True):
            portal_rooms, hub_room = relay_bot.parse_portal_rooms()

        assert portal_rooms == {"!wa:domain": "WhatsApp"}
        assert hub_room == "!hub:domain"

    def test_portal_rooms_takes_precedence(self):
        """PORTAL_ROOMS wins when both it and WHATSAPP_ROOM_ID are set."""
        import relay_bot

        env = _clean_env()
        env["PORTAL_ROOMS"] = "!sig:domain=Signal"
        env["WHATSAPP_ROOM_ID"] = "!wa:domain"
        env["HUB_ROOM_ID"] = "!hub:domain"

        with patch.dict(os.environ, env, clear=True):
            portal_rooms, hub_room = relay_bot.parse_portal_rooms()

        assert portal_rooms == {"!sig:domain": "Signal"}
        assert hub_room == "!hub:domain"

    def test_empty_portal_rooms_falls_back(self):
        """An empty PORTAL_ROOMS string falls back to WHATSAPP_ROOM_ID."""
        import relay_bot

        env = _clean_env()
        env["PORTAL_ROOMS"] = ""
        env["WHATSAPP_ROOM_ID"] = "!wa:domain"
        env["HUB_ROOM_ID"] = "!hub:domain"

        with patch.dict(os.environ, env, clear=True):
            portal_rooms, hub_room = relay_bot.parse_portal_rooms()

        assert portal_rooms == {"!wa:domain": "WhatsApp"}


class TestErrorCases:
    """Missing configuration should exit with an error."""

    def test_missing_hub_room_exits(self):
        """No HUB_ROOM_ID causes sys.exit(1)."""
        import relay_bot

        env = _clean_env()
        env["PORTAL_ROOMS"] = "!wa:domain=WhatsApp"
        # HUB_ROOM_ID deliberately absent.

        with patch.dict(os.environ, env, clear=True), pytest.raises(SystemExit):
            relay_bot.parse_portal_rooms()

    def test_no_portal_config_exits(self):
        """Neither PORTAL_ROOMS nor WHATSAPP_ROOM_ID causes sys.exit(1)."""
        import relay_bot

        env = _clean_env()
        env["HUB_ROOM_ID"] = "!hub:domain"
        # Both portal env vars absent.

        with patch.dict(os.environ, env, clear=True), pytest.raises(SystemExit):
            relay_bot.parse_portal_rooms()


class TestWhitespace:
    """Whitespace in env var values is trimmed."""

    def test_whitespace_trimmed(self):
        """Leading/trailing whitespace is stripped from room IDs and labels."""
        import relay_bot

        env = _clean_env()
        env["PORTAL_ROOMS"] = "  !wa:domain = WhatsApp , !sig:domain = Signal  "
        env["HUB_ROOM_ID"] = "  !hub:domain  "

        with patch.dict(os.environ, env, clear=True):
            portal_rooms, hub_room = relay_bot.parse_portal_rooms()

        assert portal_rooms == {
            "!wa:domain": "WhatsApp",
            "!sig:domain": "Signal",
        }
        assert hub_room == "!hub:domain"
