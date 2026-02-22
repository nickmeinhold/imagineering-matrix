"""Unit tests for ``_platform_label``."""

import relay_bot


class TestPlatformLabel:
    """Verify platform inference from Matrix user IDs."""

    def test_discord_puppet(self):
        assert relay_bot._platform_label("@_discord_123:example.com") == "Discord"

    def test_telegram_puppet(self):
        assert relay_bot._platform_label("@_telegram_456:example.com") == "Telegram"

    def test_signal_puppet(self):
        assert relay_bot._platform_label("@_signal_789:example.com") == "Signal"

    def test_whatsapp_puppet(self):
        assert relay_bot._platform_label("@_whatsapp_012:example.com") == "WhatsApp"

    def test_native_matrix_user(self):
        assert relay_bot._platform_label("@nick:example.com") == "Matrix"
