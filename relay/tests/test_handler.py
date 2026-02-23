"""Acceptance tests for the appservice relay handler.

Ports the behavioral contracts from ``test_on_message.py`` and
``test_multi_portal.py`` to the new appservice-based handler that uses puppet
intents instead of text attribution.

Key differences from old tests:
- Messages are sent via puppet intents, not ``client.room_send``
- Display names have no ``(Platform)`` suffix
- The handler receives mautrix ``Event`` objects, not nio ``RoomMessageText``
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from appservice.config import RelayConfig
from appservice.handler import RelayHandler

# ---------------------------------------------------------------------------
# Canonical IDs
# ---------------------------------------------------------------------------

DOMAIN = "example.com"
BOT_MXID = "@relay-bot:example.com"
WHATSAPP_ROOM = "!whatsapp:example.com"
SIGNAL_ROOM = "!signal:example.com"
HUB_ROOM = "!hub:example.com"

PORTAL_ROOMS = {
    WHATSAPP_ROOM: "WhatsApp",
    SIGNAL_ROOM: "Signal",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_message_event(
    sender: str,
    room_id: str,
    body: str,
    event_id: str = "$evt1",
) -> MagicMock:
    """Build a mock mautrix MessageEvent."""
    event = MagicMock()
    event.sender = sender
    event.room_id = room_id
    event.event_id = event_id

    # content
    event.content.msgtype.value = "m.text"
    event.content.body = body
    event.content.relates_to = None

    return event


def _make_profile(displayname: str, avatar_url: str | None = None) -> MagicMock:
    """Build a mock profile response."""
    profile = MagicMock()
    profile.displayname = displayname
    profile.avatar_url = avatar_url
    return profile


# Default profiles keyed by sender MXID.  Tests can override via
# ``appservice.intent.get_profile.side_effect``.
_DEFAULT_PROFILES: dict[str, MagicMock] = {
    "@_whatsapp_12345:example.com": _make_profile("Alice"),
    "@_signal_abc:example.com": _make_profile("Bob"),
    "@nick:example.com": _make_profile("Nick"),
}


def _make_handler(
    portal_rooms: dict[str, str] | None = None,
    hub_room: str = HUB_ROOM,
    profiles: dict[str, MagicMock] | None = None,
) -> tuple[RelayHandler, AsyncMock]:
    """Build a RelayHandler with a mocked puppet manager.

    Returns (handler, puppet_intent) where puppet_intent is the mock intent
    returned by ``puppet_manager.get_intent()``.

    The appservice intent's ``get_profile`` is wired to return display names
    from *profiles* (defaults to ``_DEFAULT_PROFILES``).  Unknown senders
    raise an ``Exception`` so the handler falls back to the MXID localpart.
    """
    merged_profiles = {**_DEFAULT_PROFILES, **(profiles or {})}

    appservice = MagicMock()
    appservice.bot_mxid = BOT_MXID
    appservice.intent = MagicMock()

    async def _get_profile(sender: str):
        if sender in merged_profiles and merged_profiles[sender] is not None:
            return merged_profiles[sender]
        raise Exception(f"Unknown profile: {sender}")

    appservice.intent.get_profile = AsyncMock(side_effect=_get_profile)

    puppet_manager = AsyncMock()
    puppet_intent = AsyncMock()
    puppet_intent.send_text = AsyncMock(return_value="$relayed_evt")
    puppet_manager.get_intent.return_value = puppet_intent

    handler = RelayHandler(
        appservice=appservice,
        puppet_manager=puppet_manager,
        portal_rooms=portal_rooms or PORTAL_ROOMS,
        hub_room_id=hub_room,
    )

    return handler, puppet_intent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def handler_and_intent():
    return _make_handler()


@pytest.fixture()
def handler(handler_and_intent):
    return handler_and_intent[0]


@pytest.fixture()
def puppet_intent(handler_and_intent):
    return handler_and_intent[1]


# ---------------------------------------------------------------------------
# Portal → Hub (happy path)
# ---------------------------------------------------------------------------


class TestPortalToHub:
    """Messages in a portal room are relayed to the hub via puppet intent."""

    async def test_whatsapp_message_relayed_to_hub(self, handler, puppet_intent):
        event = _make_message_event(
            sender="@_whatsapp_12345:example.com",
            room_id=WHATSAPP_ROOM,
            body="hello from WhatsApp",
        )

        await handler.handle_message(event)

        # Puppet manager was asked for an intent with "Alice" (no suffix).
        handler._puppet_manager.get_intent.assert_any_await(
            platform="whatsapp",
            sender="@_whatsapp_12345:example.com",
            display_name="Alice",
            avatar_url=None,
            room_id=HUB_ROOM,
        )
        # Message was sent to hub room.
        hub_calls = [
            c for c in puppet_intent.send_text.await_args_list
            if c.kwargs.get("room_id") == HUB_ROOM
            or (c.args and c.args[0] == HUB_ROOM)
        ]
        assert len(hub_calls) >= 1

    async def test_signal_message_relayed_to_hub(self, handler, puppet_intent):
        event = _make_message_event(
            sender="@_signal_abc:example.com",
            room_id=SIGNAL_ROOM,
            body="hello from Signal",
        )

        await handler.handle_message(event)

        hub_calls = [
            c for c in puppet_intent.send_text.await_args_list
            if c.kwargs.get("room_id") == HUB_ROOM
            or (c.args and c.args[0] == HUB_ROOM)
        ]
        assert len(hub_calls) >= 1


# ---------------------------------------------------------------------------
# Hub → All portals (fan-out)
# ---------------------------------------------------------------------------


class TestHubToPortals:
    """Messages in the hub are fanned out to every portal room."""

    async def test_hub_message_fans_out_to_all_portals(self, handler, puppet_intent):
        event = _make_message_event(
            sender="@nick:example.com",
            room_id=HUB_ROOM,
            body="hey everyone",
        )

        await handler.handle_message(event)

        target_rooms = set()
        for call in puppet_intent.send_text.await_args_list:
            room = call.args[0] if call.args else call.kwargs.get("room_id")
            target_rooms.add(room)
        assert WHATSAPP_ROOM in target_rooms
        assert SIGNAL_ROOM in target_rooms

    async def test_hub_fanout_uses_puppet_display_name(self, handler, puppet_intent):
        """Puppet display name is just the name — no platform suffix."""
        event = _make_message_event(
            sender="@nick:example.com",
            room_id=HUB_ROOM,
            body="hi all",
        )

        await handler.handle_message(event)

        # get_intent was called with display_name="Nick" (no "(Matrix)" suffix).
        for call in handler._puppet_manager.get_intent.await_args_list:
            assert call.kwargs["display_name"] == "Nick"


# ---------------------------------------------------------------------------
# Portal → Portal (cross-relay)
# ---------------------------------------------------------------------------


class TestPortalToPortal:
    """Messages in one portal are cross-relayed to other portals."""

    async def test_signal_cross_relays_to_whatsapp(self, handler, puppet_intent):
        event = _make_message_event(
            sender="@_signal_abc:example.com",
            room_id=SIGNAL_ROOM,
            body="hi from Signal",
        )

        await handler.handle_message(event)

        target_rooms = set()
        for call in puppet_intent.send_text.await_args_list:
            room = call.args[0] if call.args else call.kwargs.get("room_id")
            target_rooms.add(room)
        assert WHATSAPP_ROOM in target_rooms

    async def test_portal_does_not_echo_to_self(self, handler, puppet_intent):
        event = _make_message_event(
            sender="@_signal_abc:example.com",
            room_id=SIGNAL_ROOM,
            body="no echo",
        )

        await handler.handle_message(event)

        target_rooms = []
        for call in puppet_intent.send_text.await_args_list:
            room = call.args[0] if call.args else call.kwargs.get("room_id")
            target_rooms.append(room)
        assert SIGNAL_ROOM not in target_rooms


# ---------------------------------------------------------------------------
# Loop prevention
# ---------------------------------------------------------------------------


class TestLoopPrevention:
    """All three layers of loop prevention work."""

    async def test_own_message_ignored(self, handler, puppet_intent):
        event = _make_message_event(
            sender=BOT_MXID,
            room_id=WHATSAPP_ROOM,
            body="should be ignored",
        )

        await handler.handle_message(event)

        puppet_intent.send_text.assert_not_awaited()

    async def test_relay_puppet_message_ignored(self, handler, puppet_intent):
        event = _make_message_event(
            sender="@_relay_whatsapp_abc12345:example.com",
            room_id=WHATSAPP_ROOM,
            body="puppet echo",
        )

        await handler.handle_message(event)

        puppet_intent.send_text.assert_not_awaited()

    async def test_bridge_bot_in_portal_ignored(self, handler, puppet_intent):
        event = _make_message_event(
            sender="@whatsappbot:example.com",
            room_id=WHATSAPP_ROOM,
            body="bot status",
        )

        await handler.handle_message(event)

        puppet_intent.send_text.assert_not_awaited()

    async def test_bridge_puppet_in_portal_relayed(self, handler, puppet_intent):
        """Bridge puppets in portal rooms ARE real users — relay them."""
        event = _make_message_event(
            sender="@_whatsapp_12345:example.com",
            room_id=WHATSAPP_ROOM,
            body="real user message",
        )

        await handler.handle_message(event)

        assert puppet_intent.send_text.await_count > 0

    async def test_bridge_puppet_in_hub_ignored(self, handler, puppet_intent):
        """Bridge puppets in the hub are filtered (bridges handle natively)."""
        event = _make_message_event(
            sender="@_whatsapp_12345:example.com",
            room_id=HUB_ROOM,
            body="puppet in hub",
        )

        await handler.handle_message(event)

        puppet_intent.send_text.assert_not_awaited()

    async def test_attributed_message_ignored(self, handler, puppet_intent):
        event = _make_message_event(
            sender="@someone:example.com",
            room_id=WHATSAPP_ROOM,
            body="**Alice (WhatsApp):** already attributed",
        )

        await handler.handle_message(event)

        puppet_intent.send_text.assert_not_awaited()

    async def test_unrelated_room_ignored(self, handler, puppet_intent):
        event = _make_message_event(
            sender="@alice:example.com",
            room_id="!other:example.com",
            body="off-topic",
        )

        await handler.handle_message(event)

        puppet_intent.send_text.assert_not_awaited()


# ---------------------------------------------------------------------------
# Fan-out resilience
# ---------------------------------------------------------------------------


class TestFanOutResilience:
    """Failure to one target does not block delivery to others."""

    async def test_partial_failure_does_not_block(self, handler, puppet_intent):
        event = _make_message_event(
            sender="@nick:example.com",
            room_id=HUB_ROOM,
            body="resilience test",
        )

        # First send fails, second succeeds.
        puppet_intent.send_text.side_effect = [
            RuntimeError("network timeout"),
            "$evt_ok",
        ]

        # Must not raise.
        await handler.handle_message(event)

        # Both portals were attempted.
        assert puppet_intent.send_text.await_count == 2

    async def test_cross_relay_resilience(self):
        """Failure to one cross-relay target doesn't block others."""
        portals = {
            WHATSAPP_ROOM: "WhatsApp",
            SIGNAL_ROOM: "Signal",
            "!telegram:example.com": "Telegram",
        }
        handler, puppet_intent = _make_handler(portal_rooms=portals)

        event = _make_message_event(
            sender="@_signal_abc:example.com",
            room_id=SIGNAL_ROOM,
            body="resilience",
        )

        # Hub OK, first cross-relay fails, second OK.
        puppet_intent.send_text.side_effect = [
            "$evt_hub",
            RuntimeError("timeout"),
            "$evt_ok",
        ]

        await handler.handle_message(event)

        # All 3 targets attempted: hub + 2 other portals.
        assert puppet_intent.send_text.await_count == 3


# ---------------------------------------------------------------------------
# Display name resolution
# ---------------------------------------------------------------------------


class TestDisplayName:
    """The handler resolves display names via homeserver profile lookup."""

    async def test_uses_display_name_from_profile(self, handler, puppet_intent):
        """Profile lookup returns the real name set by the mautrix bridge."""
        event = _make_message_event(
            sender="@_whatsapp_12345:example.com",
            room_id=WHATSAPP_ROOM,
            body="hello",
        )

        await handler.handle_message(event)

        # Verify the puppet was requested with the profile display name.
        call = handler._puppet_manager.get_intent.await_args_list[0]
        assert call.kwargs["display_name"] == "Alice"

    async def test_falls_back_to_localpart_on_profile_failure(self):
        """When profile lookup fails, fall back to the MXID localpart."""
        handler, puppet_intent = _make_handler(
            profiles={"@_unknown_xyz:example.com": None},  # will not match
        )
        event = _make_message_event(
            sender="@_unknown_xyz:example.com",
            room_id=WHATSAPP_ROOM,
            body="hello",
        )

        await handler.handle_message(event)

        call = handler._puppet_manager.get_intent.await_args_list[0]
        assert call.kwargs["display_name"] == "_unknown_xyz"

    async def test_avatar_url_passed_to_puppet(self, puppet_intent):
        """Avatar URL from the profile is forwarded to the puppet manager."""
        handler, puppet_intent = _make_handler(
            profiles={
                "@_whatsapp_12345:example.com": _make_profile(
                    "Alice", avatar_url="mxc://example.com/avatar123",
                ),
            },
        )
        event = _make_message_event(
            sender="@_whatsapp_12345:example.com",
            room_id=WHATSAPP_ROOM,
            body="hello",
        )

        await handler.handle_message(event)

        call = handler._puppet_manager.get_intent.await_args_list[0]
        assert call.kwargs["avatar_url"] == "mxc://example.com/avatar123"
