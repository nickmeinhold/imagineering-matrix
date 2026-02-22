"""Acceptance tests for multi-portal relay support.

Verifies that the relay bot can bridge N portal rooms (e.g. WhatsApp + Signal)
into the superbridge hub room, with fan-out from hub to all portals, per-portal
labels, loop prevention, and resilience to partial failures.

All tests call ``make_on_message`` with 4 args (client, my_user_id,
portal_rooms, hub_room).  Against the current 2-arg signature this produces
``TypeError`` — RED phase.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from tests.conftest import FakeEvent, FakeRoom, FakeUser, MY_USER

# Room IDs used across the multi-portal test suite.
WHATSAPP_ROOM = "!whatsapp:example.com"
SIGNAL_ROOM = "!signal:example.com"
HUB_ROOM = "!hub:example.com"

PORTAL_ROOMS = {
    WHATSAPP_ROOM: "WhatsApp",
    SIGNAL_ROOM: "Signal",
}


@pytest.fixture()
def client() -> AsyncMock:
    mock = AsyncMock()
    mock.room_send = AsyncMock()
    return mock


@pytest.fixture()
def on_message(client: AsyncMock):
    """Multi-portal on_message callback with two portal rooms."""
    import relay_bot

    return relay_bot.make_on_message(client, MY_USER, PORTAL_ROOMS, HUB_ROOM)


# ---------------------------------------------------------------------------
# Portal → Hub
# ---------------------------------------------------------------------------


class TestPortalToHub:
    """Messages arriving in a portal room are relayed to the hub."""

    async def test_whatsapp_portal_relays_to_hub(
        self, on_message, client: AsyncMock,
    ):
        """A WhatsApp portal message reaches the hub with 'WhatsApp' label."""
        room = FakeRoom(
            room_id=WHATSAPP_ROOM,
            users={"@alice:example.com": FakeUser(display_name="Alice")},
        )
        event = FakeEvent(sender="@alice:example.com", body="hello from WA")

        await on_message(room, event)

        # Hub is among the targets (plus cross-relay to other portals).
        hub_calls = [
            c for c in client.room_send.await_args_list if c[0][0] == HUB_ROOM
        ]
        assert len(hub_calls) == 1
        assert hub_calls[0][1]["content"]["body"] == "**Alice (WhatsApp):** hello from WA"

    async def test_signal_portal_relays_to_hub(
        self, on_message, client: AsyncMock,
    ):
        """A Signal portal message reaches the hub with 'Signal' label."""
        room = FakeRoom(
            room_id=SIGNAL_ROOM,
            users={"@bob:example.com": FakeUser(display_name="Bob")},
        )
        event = FakeEvent(sender="@bob:example.com", body="hello from Signal")

        await on_message(room, event)

        # Hub is among the targets (plus cross-relay to other portals).
        hub_calls = [
            c for c in client.room_send.await_args_list if c[0][0] == HUB_ROOM
        ]
        assert len(hub_calls) == 1
        assert hub_calls[0][1]["content"]["body"] == "**Bob (Signal):** hello from Signal"


# ---------------------------------------------------------------------------
# Hub → All portals (fan-out)
# ---------------------------------------------------------------------------


class TestHubToPortals:
    """Messages arriving in the hub are fanned out to every portal room."""

    async def test_hub_message_fans_out_to_all_portals(
        self, on_message, client: AsyncMock,
    ):
        """A hub message is sent to BOTH portal rooms."""
        room = FakeRoom(
            room_id=HUB_ROOM,
            users={"@nick:example.com": FakeUser(display_name="Nick")},
        )
        event = FakeEvent(sender="@nick:example.com", body="hey everyone")

        await on_message(room, event)

        assert client.room_send.await_count == 2
        target_rooms = {c[0][0] for c in client.room_send.await_args_list}
        assert target_rooms == {WHATSAPP_ROOM, SIGNAL_ROOM}

    async def test_hub_fanout_uses_platform_label(
        self, on_message, client: AsyncMock,
    ):
        """Fan-out messages carry the sender's inferred platform label.

        Bridge puppets are filtered by layer 2, so we use a native Matrix user
        and verify the label is 'Matrix'.
        """
        room = FakeRoom(
            room_id=HUB_ROOM,
            users={"@carol:example.com": FakeUser(display_name="Carol")},
        )
        event = FakeEvent(sender="@carol:example.com", body="hi all")

        await on_message(room, event)

        bodies = [
            c[1]["content"]["body"]
            for c in client.room_send.await_args_list
        ]
        assert len(bodies) == 2
        for body in bodies:
            assert body == "**Carol (Matrix):** hi all"

    async def test_hub_fanout_with_matrix_user(
        self, on_message, client: AsyncMock,
    ):
        """A native Matrix user's hub message is labeled 'Matrix' in portals."""
        room = FakeRoom(
            room_id=HUB_ROOM,
            users={"@nick:example.com": FakeUser(display_name="Nick")},
        )
        event = FakeEvent(sender="@nick:example.com", body="from Element")

        await on_message(room, event)

        bodies = [
            c[1]["content"]["body"]
            for c in client.room_send.await_args_list
        ]
        for body in bodies:
            assert body == "**Nick (Matrix):** from Element"


# ---------------------------------------------------------------------------
# Single-portal backward compatibility
# ---------------------------------------------------------------------------


class TestSinglePortal:
    """A single-portal config behaves like the original WhatsApp-only bot."""

    @pytest.fixture()
    def on_message_single(self, client: AsyncMock):
        import relay_bot

        return relay_bot.make_on_message(
            client, MY_USER, {WHATSAPP_ROOM: "WhatsApp"}, HUB_ROOM,
        )

    async def test_single_portal_to_hub(
        self, on_message_single, client: AsyncMock,
    ):
        room = FakeRoom(
            room_id=WHATSAPP_ROOM,
            users={"@alice:example.com": FakeUser(display_name="Alice")},
        )
        event = FakeEvent(sender="@alice:example.com", body="hi")

        await on_message_single(room, event)

        client.room_send.assert_awaited_once()
        assert client.room_send.await_args[0][0] == HUB_ROOM

    async def test_single_hub_to_portal(
        self, on_message_single, client: AsyncMock,
    ):
        room = FakeRoom(
            room_id=HUB_ROOM,
            users={"@nick:example.com": FakeUser(display_name="Nick")},
        )
        event = FakeEvent(sender="@nick:example.com", body="hey")

        await on_message_single(room, event)

        client.room_send.assert_awaited_once()
        assert client.room_send.await_args[0][0] == WHATSAPP_ROOM


# ---------------------------------------------------------------------------
# Loop prevention in multi-portal context
# ---------------------------------------------------------------------------


class TestMultiPortalLoopPrevention:
    """All three loop-prevention layers work for every portal room."""

    async def test_own_message_in_signal_portal_ignored(
        self, on_message, client: AsyncMock,
    ):
        """Layer 1: bot's own messages are ignored in the Signal portal."""
        room = FakeRoom(room_id=SIGNAL_ROOM)
        event = FakeEvent(sender=MY_USER, body="echo")

        await on_message(room, event)

        client.room_send.assert_not_awaited()

    async def test_bridge_puppet_in_signal_portal_ignored(
        self, on_message, client: AsyncMock,
    ):
        """Layer 2: bridge puppet messages are ignored in the Signal portal."""
        room = FakeRoom(room_id=SIGNAL_ROOM)
        event = FakeEvent(sender="@_signal_456:example.com", body="puppet")

        await on_message(room, event)

        client.room_send.assert_not_awaited()

    async def test_attributed_message_in_signal_portal_ignored(
        self, on_message, client: AsyncMock,
    ):
        """Layer 3: already-attributed messages are ignored in Signal portal."""
        room = FakeRoom(room_id=SIGNAL_ROOM)
        event = FakeEvent(
            sender="@someone:example.com",
            body="**Alice (WhatsApp):** already attributed",
        )

        await on_message(room, event)

        client.room_send.assert_not_awaited()

    async def test_unrelated_room_still_ignored(
        self, on_message, client: AsyncMock,
    ):
        """Rooms that are neither a portal nor the hub are still ignored."""
        room = FakeRoom(room_id="!random:example.com")
        event = FakeEvent(sender="@alice:example.com", body="off-topic")

        await on_message(room, event)

        client.room_send.assert_not_awaited()


# ---------------------------------------------------------------------------
# Fan-out resilience
# ---------------------------------------------------------------------------


class TestFanOutResilience:
    """Failures sending to one portal must not block delivery to others."""

    async def test_partial_failure_does_not_block_other_portals(
        self, on_message, client: AsyncMock,
    ):
        """If sending to the first portal fails, the second still receives."""
        room = FakeRoom(
            room_id=HUB_ROOM,
            users={"@nick:example.com": FakeUser(display_name="Nick")},
        )
        event = FakeEvent(sender="@nick:example.com", body="resilience test")

        # First call fails, second succeeds.
        client.room_send.side_effect = [
            RuntimeError("network timeout"),
            AsyncMock(),
        ]

        # Must not raise.
        await on_message(room, event)

        # Both portals were attempted.
        assert client.room_send.await_count == 2


# ---------------------------------------------------------------------------
# Portal → Portal (cross-relay)
# ---------------------------------------------------------------------------


class TestPortalToPortal:
    """Messages arriving in one portal are cross-relayed to other portals."""

    async def test_signal_portal_cross_relays_to_whatsapp(
        self, on_message, client: AsyncMock,
    ):
        """A Signal portal message is sent to the WhatsApp portal."""
        room = FakeRoom(
            room_id=SIGNAL_ROOM,
            users={"@bob:example.com": FakeUser(display_name="Bob")},
        )
        event = FakeEvent(sender="@bob:example.com", body="hi from Signal")

        await on_message(room, event)

        target_rooms = {c[0][0] for c in client.room_send.await_args_list}
        assert WHATSAPP_ROOM in target_rooms

    async def test_whatsapp_portal_cross_relays_to_signal(
        self, on_message, client: AsyncMock,
    ):
        """A WhatsApp portal message is sent to the Signal portal."""
        room = FakeRoom(
            room_id=WHATSAPP_ROOM,
            users={"@alice:example.com": FakeUser(display_name="Alice")},
        )
        event = FakeEvent(sender="@alice:example.com", body="hi from WA")

        await on_message(room, event)

        target_rooms = {c[0][0] for c in client.room_send.await_args_list}
        assert SIGNAL_ROOM in target_rooms

    async def test_portal_does_not_echo_to_self(
        self, on_message, client: AsyncMock,
    ):
        """The source portal is skipped — no echo back to itself."""
        room = FakeRoom(
            room_id=SIGNAL_ROOM,
            users={"@bob:example.com": FakeUser(display_name="Bob")},
        )
        event = FakeEvent(sender="@bob:example.com", body="no echo")

        await on_message(room, event)

        target_rooms = [c[0][0] for c in client.room_send.await_args_list]
        assert SIGNAL_ROOM not in target_rooms

    async def test_cross_relay_uses_source_portal_label(
        self, on_message, client: AsyncMock,
    ):
        """Cross-relayed message carries the *source* portal's label."""
        room = FakeRoom(
            room_id=SIGNAL_ROOM,
            users={"@bob:example.com": FakeUser(display_name="Bob")},
        )
        event = FakeEvent(sender="@bob:example.com", body="labeled msg")

        await on_message(room, event)

        # Find the call targeting the WhatsApp portal.
        for call in client.room_send.await_args_list:
            if call[0][0] == WHATSAPP_ROOM:
                body = call[1]["content"]["body"]
                assert body == "**Bob (Signal):** labeled msg"
                break
        else:
            pytest.fail("No cross-relay call to WhatsApp portal found")

    async def test_cross_relay_resilience(
        self, on_message, client: AsyncMock,
    ):
        """Failure sending to one cross-relay target doesn't block others."""
        # Use 3 portals to test resilience (hub + 2 cross-relay targets).
        import relay_bot

        third_room = "!telegram_portal:example.com"
        portals = {
            WHATSAPP_ROOM: "WhatsApp",
            SIGNAL_ROOM: "Signal",
            third_room: "Telegram",
        }
        on_msg = relay_bot.make_on_message(client, MY_USER, portals, HUB_ROOM)

        room = FakeRoom(
            room_id=SIGNAL_ROOM,
            users={"@bob:example.com": FakeUser(display_name="Bob")},
        )
        event = FakeEvent(sender="@bob:example.com", body="resilience")

        # Hub send succeeds, first cross-relay fails, second succeeds.
        client.room_send.side_effect = [
            AsyncMock(),                      # → hub
            RuntimeError("network timeout"),  # → WhatsApp (or Telegram)
            AsyncMock(),                      # → Telegram (or WhatsApp)
        ]

        await on_msg(room, event)

        # All 3 targets attempted: hub + 2 other portals.
        assert client.room_send.await_count == 3
