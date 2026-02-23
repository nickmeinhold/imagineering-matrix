"""Unit tests for ``_is_bridge_bot`` and ``_is_bridge_puppet``."""

import relay_bot


class TestIsBridgeBot:
    """Verify that ``_is_bridge_bot`` matches only bridge bot accounts."""

    def test_whatsapp_bot(self):
        assert relay_bot._is_bridge_bot("@whatsappbot:example.com") is True

    def test_discord_bot(self):
        assert relay_bot._is_bridge_bot("@discordbot:example.com") is True

    def test_telegram_bot(self):
        assert relay_bot._is_bridge_bot("@telegrambot:example.com") is True

    def test_signal_bot(self):
        assert relay_bot._is_bridge_bot("@signalbot:example.com") is True

    def test_puppet_not_matched(self):
        """Puppets are NOT bots — this is the key divergence from _is_bridge_puppet."""
        assert relay_bot._is_bridge_bot("@_whatsapp_12345:example.com") is False

    def test_regular_user_not_matched(self):
        assert relay_bot._is_bridge_bot("@alice:example.com") is False


class TestIsBridgePuppet:
    """Verify detection of bridge bots and puppet users."""

    def test_whatsapp_bot(self):
        assert relay_bot._is_bridge_puppet("@whatsappbot:example.com") is True

    def test_discord_bot(self):
        assert relay_bot._is_bridge_puppet("@discordbot:example.com") is True

    def test_telegram_bot(self):
        assert relay_bot._is_bridge_puppet("@telegrambot:example.com") is True

    def test_signal_bot(self):
        assert relay_bot._is_bridge_puppet("@signalbot:example.com") is True

    def test_puppet_prefix(self):
        assert relay_bot._is_bridge_puppet("@_discord_789:example.com") is True

    def test_regular_user(self):
        assert relay_bot._is_bridge_puppet("@alice:example.com") is False
