"""Unit tests for ``_display_name``."""

import relay_bot
from tests.conftest import FakeRoom, FakeUser


class TestDisplayName:
    """Verify display-name resolution with fallback."""

    def test_display_name_present(self):
        room = FakeRoom(
            room_id="!r:example.com",
            users={"@alice:example.com": FakeUser(display_name="Alice")},
        )
        assert relay_bot._display_name(room, "@alice:example.com") == "Alice"

    def test_fallback_to_localpart(self):
        room = FakeRoom(room_id="!r:example.com")
        assert relay_bot._display_name(room, "@bob:example.com") == "bob"
