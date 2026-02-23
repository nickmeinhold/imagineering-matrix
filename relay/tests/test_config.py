"""Unit tests for appservice configuration parsing.

Verifies that :class:`RelayConfig` correctly reads environment variables,
applies defaults, trims whitespace, and exits on missing required values.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from appservice.config import RelayConfig

# Minimal valid environment for all required variables.
REQUIRED_ENV = {
    "RELAY_HOMESERVER_URL": "http://localhost:8008",
    "RELAY_DOMAIN": "example.com",
    "RELAY_AS_TOKEN": "as_token_123",
    "RELAY_HS_TOKEN": "hs_token_456",
    "RELAY_PORTAL_ROOMS": "!wa:example.com=WhatsApp,!sig:example.com=Signal",
    "RELAY_HUB_ROOM_ID": "!hub:example.com",
}


def _make_config(**overrides: str) -> RelayConfig:
    """Build a :class:`RelayConfig` with *overrides* applied on top of defaults."""
    env = {**REQUIRED_ENV, **overrides}
    with patch.dict(os.environ, env, clear=False):
        return RelayConfig.from_env()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestRelayConfigFromEnv:
    """All required fields are parsed correctly."""

    def test_all_required_fields_parsed(self):
        config = _make_config()
        assert config.homeserver_url == "http://localhost:8008"
        assert config.domain == "example.com"
        assert config.as_token == "as_token_123"
        assert config.hs_token == "hs_token_456"
        assert config.hub_room_id == "!hub:example.com"

    def test_portal_rooms_parsed(self):
        config = _make_config()
        assert config.portal_rooms == {
            "!wa:example.com": "WhatsApp",
            "!sig:example.com": "Signal",
        }

    def test_single_portal_room(self):
        config = _make_config(RELAY_PORTAL_ROOMS="!wa:example.com=WhatsApp")
        assert config.portal_rooms == {"!wa:example.com": "WhatsApp"}

    def test_default_bot_localpart(self):
        config = _make_config()
        assert config.bot_localpart == "relay-bot"

    def test_default_db_path(self):
        config = _make_config()
        assert config.db_path == "/data/relay.db"

    def test_custom_bot_localpart(self):
        config = _make_config(RELAY_BOT_LOCALPART="mybot")
        assert config.bot_localpart == "mybot"

    def test_custom_db_path(self):
        config = _make_config(RELAY_DB_PATH="/tmp/test.db")
        assert config.db_path == "/tmp/test.db"


# ---------------------------------------------------------------------------
# Whitespace handling
# ---------------------------------------------------------------------------


class TestWhitespace:
    def test_required_fields_trimmed(self):
        config = _make_config(
            RELAY_HOMESERVER_URL="  http://localhost:8008  ",
            RELAY_DOMAIN="  example.com  ",
            RELAY_HUB_ROOM_ID="  !hub:example.com  ",
        )
        assert config.homeserver_url == "http://localhost:8008"
        assert config.domain == "example.com"
        assert config.hub_room_id == "!hub:example.com"

    def test_portal_rooms_trimmed(self):
        config = _make_config(
            RELAY_PORTAL_ROOMS=" !wa:example.com = WhatsApp , !sig:example.com = Signal ",
        )
        assert config.portal_rooms == {
            "!wa:example.com": "WhatsApp",
            "!sig:example.com": "Signal",
        }


# ---------------------------------------------------------------------------
# Missing / invalid values → sys.exit(1)
# ---------------------------------------------------------------------------


class TestRelayConfigMissingRequired:
    """Missing required env vars cause ``sys.exit(1)``."""

    @pytest.mark.parametrize("missing_var", [
        "RELAY_HOMESERVER_URL",
        "RELAY_DOMAIN",
        "RELAY_AS_TOKEN",
        "RELAY_HS_TOKEN",
        "RELAY_HUB_ROOM_ID",
        "RELAY_PORTAL_ROOMS",
    ])
    def test_missing_required_exits(self, missing_var: str):
        env = {**REQUIRED_ENV, missing_var: ""}
        with patch.dict(os.environ, env, clear=False), pytest.raises(SystemExit):
            RelayConfig.from_env()

    def test_missing_portal_label_exits(self):
        env = {**REQUIRED_ENV, "RELAY_PORTAL_ROOMS": "!wa:example.com"}
        with patch.dict(os.environ, env, clear=False), pytest.raises(SystemExit):
            RelayConfig.from_env()
