"""Unit tests for ``ATTRIBUTION_RE``."""

import relay_bot


class TestAttributionRegex:
    """Verify that already-attributed messages are detected."""

    def test_bold_attribution_matches(self):
        assert relay_bot.ATTRIBUTION_RE.match("**Alice (WhatsApp):** hello")

    def test_plain_colon_attribution_matches(self):
        assert relay_bot.ATTRIBUTION_RE.match("Alice: hello from Discord")

    def test_normal_message_no_match(self):
        assert relay_bot.ATTRIBUTION_RE.match("just a normal message") is None

    def test_lowercase_start_no_match(self):
        """Plain colon pattern requires uppercase start (``[A-Z]``)."""
        assert relay_bot.ATTRIBUTION_RE.match("alice: sneaky") is None
