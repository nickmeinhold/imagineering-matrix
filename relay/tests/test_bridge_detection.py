"""Unit tests for ``_is_bridge_puppet``."""

import relay_bot


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
