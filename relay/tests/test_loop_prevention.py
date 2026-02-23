"""Unit tests for appservice loop prevention.

Tests the pure functions that determine whether an event should be ignored
to prevent message loops.  All functions are side-effect-free and operate on
plain strings, making them fast and deterministic.
"""

from __future__ import annotations

import pytest

from appservice.loop_prevention import (
    has_attribution,
    is_bridge_bot,
    is_bridge_puppet,
    is_own_message,
    is_relay_puppet,
    platform_label,
    should_ignore_in_hub,
    should_ignore_in_portal,
)

BOT_MXID = "@relay-bot:example.com"


# ---------------------------------------------------------------------------
# is_own_message
# ---------------------------------------------------------------------------


class TestIsOwnMessage:
    def test_bot_mxid_matches(self):
        assert is_own_message(BOT_MXID, BOT_MXID) is True

    def test_different_user(self):
        assert is_own_message("@alice:example.com", BOT_MXID) is False


# ---------------------------------------------------------------------------
# is_relay_puppet
# ---------------------------------------------------------------------------


class TestIsRelayPuppet:
    def test_relay_puppet(self):
        assert is_relay_puppet("@_relay_whatsapp_abc12345:example.com") is True

    def test_regular_user(self):
        assert is_relay_puppet("@alice:example.com") is False

    def test_bridge_puppet_not_relay(self):
        assert is_relay_puppet("@_whatsapp_12345:example.com") is False


# ---------------------------------------------------------------------------
# is_bridge_bot
# ---------------------------------------------------------------------------


class TestIsBridgeBot:
    @pytest.mark.parametrize("localpart", [
        "whatsappbot", "discordbot", "telegrambot", "signalbot",
    ])
    def test_known_bots(self, localpart):
        assert is_bridge_bot(f"@{localpart}:example.com") is True

    def test_regular_user(self):
        assert is_bridge_bot("@alice:example.com") is False

    def test_puppet_not_bot(self):
        assert is_bridge_bot("@_whatsapp_12345:example.com") is False


# ---------------------------------------------------------------------------
# is_bridge_puppet
# ---------------------------------------------------------------------------


class TestIsBridgePuppet:
    @pytest.mark.parametrize("user_id", [
        "@_whatsapp_12345:example.com",
        "@_discord_789:example.com",
        "@_telegram_456:example.com",
        "@_signal_abc:example.com",
    ])
    def test_puppet_mxids(self, user_id):
        assert is_bridge_puppet(user_id) is True

    @pytest.mark.parametrize("localpart", [
        "whatsappbot", "discordbot", "telegrambot", "signalbot",
    ])
    def test_bot_accounts_also_match(self, localpart):
        assert is_bridge_puppet(f"@{localpart}:example.com") is True

    def test_regular_user(self):
        assert is_bridge_puppet("@alice:example.com") is False

    def test_relay_puppet_not_bridge(self):
        assert is_bridge_puppet("@_relay_wa_abc123:example.com") is False


# ---------------------------------------------------------------------------
# has_attribution
# ---------------------------------------------------------------------------


class TestHasAttribution:
    def test_bold_attribution(self):
        assert has_attribution("**Alice (WhatsApp):** hello") is True

    def test_plain_colon_attribution(self):
        assert has_attribution("Alice: hello from Discord relay") is True

    def test_normal_message(self):
        assert has_attribution("hello world") is False

    def test_lowercase_start(self):
        assert has_attribution("alice: not attributed") is False


# ---------------------------------------------------------------------------
# platform_label
# ---------------------------------------------------------------------------


class TestPlatformLabel:
    @pytest.mark.parametrize("user_id,expected", [
        ("@_discord_123:example.com", "Discord"),
        ("@_telegram_456:example.com", "Telegram"),
        ("@_signal_abc:example.com", "Signal"),
        ("@_whatsapp_12345:example.com", "WhatsApp"),
    ])
    def test_puppet_platforms(self, user_id, expected):
        assert platform_label(user_id) == expected

    def test_native_matrix_user(self):
        assert platform_label("@alice:example.com") == "Matrix"


# ---------------------------------------------------------------------------
# should_ignore_in_portal
# ---------------------------------------------------------------------------


class TestShouldIgnoreInPortal:
    def test_own_message_ignored(self):
        assert should_ignore_in_portal(BOT_MXID, "hello", BOT_MXID) is True

    def test_relay_puppet_ignored(self):
        assert should_ignore_in_portal(
            "@_relay_wa_abc123:example.com", "hello", BOT_MXID,
        ) is True

    def test_bridge_bot_ignored(self):
        assert should_ignore_in_portal(
            "@whatsappbot:example.com", "status", BOT_MXID,
        ) is True

    def test_bridge_puppet_allowed(self):
        """Bridge puppets ARE the real users in portals — not ignored."""
        assert should_ignore_in_portal(
            "@_whatsapp_12345:example.com", "hello", BOT_MXID,
        ) is False

    def test_attributed_message_ignored(self):
        assert should_ignore_in_portal(
            "@someone:example.com", "**Alice (WhatsApp):** hi", BOT_MXID,
        ) is True

    def test_normal_message_allowed(self):
        assert should_ignore_in_portal(
            "@alice:example.com", "hello", BOT_MXID,
        ) is False


# ---------------------------------------------------------------------------
# should_ignore_in_hub
# ---------------------------------------------------------------------------


class TestShouldIgnoreInHub:
    def test_own_message_ignored(self):
        assert should_ignore_in_hub(BOT_MXID, "hello", BOT_MXID) is True

    def test_relay_puppet_ignored(self):
        assert should_ignore_in_hub(
            "@_relay_wa_abc123:example.com", "hello", BOT_MXID,
        ) is True

    def test_bridge_bot_ignored(self):
        assert should_ignore_in_hub(
            "@whatsappbot:example.com", "status", BOT_MXID,
        ) is True

    def test_bridge_puppet_ignored(self):
        """Bridge puppets in the hub are filtered (bridges handle natively)."""
        assert should_ignore_in_hub(
            "@_whatsapp_12345:example.com", "hello", BOT_MXID,
        ) is True

    def test_attributed_message_ignored(self):
        assert should_ignore_in_hub(
            "@someone:example.com", "**Alice (WhatsApp):** hi", BOT_MXID,
        ) is True

    def test_normal_message_allowed(self):
        assert should_ignore_in_hub(
            "@nick:example.com", "hello", BOT_MXID,
        ) is False
