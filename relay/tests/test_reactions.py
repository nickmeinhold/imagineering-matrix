"""Acceptance tests for reaction relay with event ID mapping.

Verifies that emoji reactions are relayed to the correct message in target
rooms via the event map, with proper loop prevention and graceful handling
of unmapped events.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from appservice.event_map import EventMap
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


def _make_reaction_event(
    sender: str,
    room_id: str,
    reacted_to: str,
    key: str = "\U0001f44d",
) -> MagicMock:
    """Build a mock reaction event."""
    event = MagicMock()
    event.sender = sender
    event.room_id = room_id
    event.event_id = "$reaction_evt"
    event.content.relates_to.event_id = reacted_to
    event.content.relates_to.key = key
    return event


def _make_handler(
    event_map: EventMap,
) -> tuple[RelayHandler, AsyncMock]:
    """Build a RelayHandler with mocked puppet manager and event map."""
    appservice = MagicMock()
    appservice.bot_mxid = BOT_MXID

    puppet_manager = AsyncMock()
    puppet_intent = AsyncMock()
    puppet_intent.react = AsyncMock(return_value="$reaction_relayed")
    puppet_manager.get_intent.return_value = puppet_intent

    handler = RelayHandler(
        appservice=appservice,
        puppet_manager=puppet_manager,
        portal_rooms=PORTAL_ROOMS,
        hub_room_id=HUB_ROOM,
        event_map=event_map,
    )

    return handler, puppet_intent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
async def event_map() -> EventMap:
    em = EventMap(":memory:")
    await em.open()
    yield em
    await em.close()


# ---------------------------------------------------------------------------
# Reaction relay: portal → hub + other portals
# ---------------------------------------------------------------------------


class TestReactionFromPortal:
    """Reactions in a portal room are relayed to the hub and other portals."""

    async def test_reaction_relayed_to_hub(self, event_map: EventMap):
        handler, puppet_intent = _make_handler(event_map)

        # Pre-populate: $wa_msg was relayed to $hub_msg in the hub.
        await event_map.store("$wa_msg", WHATSAPP_ROOM, "$hub_msg", HUB_ROOM)

        event = _make_reaction_event(
            sender="@_whatsapp_12345:example.com",
            room_id=WHATSAPP_ROOM,
            reacted_to="$wa_msg",
            key="\U0001f44d",
        )

        await handler.handle_reaction(event)

        # react() should have been called with the hub event.
        puppet_intent.react.assert_any_await(HUB_ROOM, "$hub_msg", "\U0001f44d")

    async def test_reaction_relayed_to_other_portals(self, event_map: EventMap):
        handler, puppet_intent = _make_handler(event_map)

        await event_map.store("$wa_msg", WHATSAPP_ROOM, "$hub_msg", HUB_ROOM)
        await event_map.store("$wa_msg", WHATSAPP_ROOM, "$sig_msg", SIGNAL_ROOM)

        event = _make_reaction_event(
            sender="@_whatsapp_12345:example.com",
            room_id=WHATSAPP_ROOM,
            reacted_to="$wa_msg",
            key="\u2764\ufe0f",
        )

        await handler.handle_reaction(event)

        puppet_intent.react.assert_any_await(SIGNAL_ROOM, "$sig_msg", "\u2764\ufe0f")


# ---------------------------------------------------------------------------
# Reaction relay: hub → portals
# ---------------------------------------------------------------------------


class TestReactionFromHub:
    """Reactions in the hub are fanned out to portal rooms."""

    async def test_hub_reaction_relayed_to_portals(self, event_map: EventMap):
        handler, puppet_intent = _make_handler(event_map)

        await event_map.store("$hub_msg", HUB_ROOM, "$wa_msg", WHATSAPP_ROOM)
        await event_map.store("$hub_msg", HUB_ROOM, "$sig_msg", SIGNAL_ROOM)

        event = _make_reaction_event(
            sender="@nick:example.com",
            room_id=HUB_ROOM,
            reacted_to="$hub_msg",
            key="\U0001f44d",
        )

        await handler.handle_reaction(event)

        assert puppet_intent.react.await_count == 2
        target_rooms = {c.args[0] for c in puppet_intent.react.await_args_list}
        assert WHATSAPP_ROOM in target_rooms
        assert SIGNAL_ROOM in target_rooms


# ---------------------------------------------------------------------------
# Loop prevention
# ---------------------------------------------------------------------------


class TestReactionLoopPrevention:

    async def test_own_reaction_ignored(self, event_map: EventMap):
        handler, puppet_intent = _make_handler(event_map)

        event = _make_reaction_event(
            sender=BOT_MXID,
            room_id=WHATSAPP_ROOM,
            reacted_to="$some_msg",
        )

        await handler.handle_reaction(event)

        puppet_intent.react.assert_not_awaited()

    async def test_relay_puppet_reaction_ignored(self, event_map: EventMap):
        handler, puppet_intent = _make_handler(event_map)

        event = _make_reaction_event(
            sender="@_relay_whatsapp_abc12345:example.com",
            room_id=WHATSAPP_ROOM,
            reacted_to="$some_msg",
        )

        await handler.handle_reaction(event)

        puppet_intent.react.assert_not_awaited()

    async def test_bridge_bot_reaction_ignored(self, event_map: EventMap):
        handler, puppet_intent = _make_handler(event_map)

        event = _make_reaction_event(
            sender="@whatsappbot:example.com",
            room_id=WHATSAPP_ROOM,
            reacted_to="$some_msg",
        )

        await handler.handle_reaction(event)

        puppet_intent.react.assert_not_awaited()

    async def test_bridge_puppet_reaction_in_hub_ignored(self, event_map: EventMap):
        handler, puppet_intent = _make_handler(event_map)

        event = _make_reaction_event(
            sender="@_whatsapp_12345:example.com",
            room_id=HUB_ROOM,
            reacted_to="$some_msg",
        )

        await handler.handle_reaction(event)

        puppet_intent.react.assert_not_awaited()

    async def test_unrelated_room_reaction_ignored(self, event_map: EventMap):
        handler, puppet_intent = _make_handler(event_map)

        event = _make_reaction_event(
            sender="@alice:example.com",
            room_id="!other:example.com",
            reacted_to="$some_msg",
        )

        await handler.handle_reaction(event)

        puppet_intent.react.assert_not_awaited()


# ---------------------------------------------------------------------------
# Unmapped events
# ---------------------------------------------------------------------------


class TestUnmappedReactions:

    async def test_reaction_to_unmapped_event_silently_skipped(self, event_map: EventMap):
        handler, puppet_intent = _make_handler(event_map)

        event = _make_reaction_event(
            sender="@_whatsapp_12345:example.com",
            room_id=WHATSAPP_ROOM,
            reacted_to="$unknown_msg",
        )

        # Must not raise.
        await handler.handle_reaction(event)

        puppet_intent.react.assert_not_awaited()


# ---------------------------------------------------------------------------
# Resilience
# ---------------------------------------------------------------------------


class TestReactionResilience:

    async def test_partial_failure_does_not_block(self, event_map: EventMap):
        handler, puppet_intent = _make_handler(event_map)

        await event_map.store("$hub_msg", HUB_ROOM, "$wa_msg", WHATSAPP_ROOM)
        await event_map.store("$hub_msg", HUB_ROOM, "$sig_msg", SIGNAL_ROOM)

        puppet_intent.react.side_effect = [
            RuntimeError("network timeout"),
            "$ok",
        ]

        event = _make_reaction_event(
            sender="@nick:example.com",
            room_id=HUB_ROOM,
            reacted_to="$hub_msg",
        )

        # Must not raise.
        await handler.handle_reaction(event)

        assert puppet_intent.react.await_count == 2


# ---------------------------------------------------------------------------
# No event map
# ---------------------------------------------------------------------------


class TestNoEventMap:

    async def test_reaction_without_event_map_is_noop(self):
        """Without an event map, reactions are silently ignored."""
        appservice = MagicMock()
        appservice.bot_mxid = BOT_MXID
        puppet_manager = AsyncMock()
        puppet_intent = AsyncMock()
        puppet_manager.get_intent.return_value = puppet_intent

        handler = RelayHandler(
            appservice=appservice,
            puppet_manager=puppet_manager,
            portal_rooms=PORTAL_ROOMS,
            hub_room_id=HUB_ROOM,
            event_map=None,
        )

        event = _make_reaction_event(
            sender="@alice:example.com",
            room_id=WHATSAPP_ROOM,
            reacted_to="$some_msg",
        )

        await handler.handle_reaction(event)

        puppet_intent.react.assert_not_awaited()
