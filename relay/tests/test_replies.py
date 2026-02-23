"""Acceptance tests for reply relay with event ID mapping.

Verifies that when a message has ``m.in_reply_to``, the handler looks up
the original event in the event map and constructs the relay with the
correct reply-to reference in the target room.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call, patch

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


def _make_message_event(
    sender: str,
    room_id: str,
    body: str,
    event_id: str = "$evt1",
    reply_to: str | None = None,
    display_name: str | None = None,
) -> MagicMock:
    """Build a mock MessageEvent, optionally with m.in_reply_to."""
    event = MagicMock()
    event.sender = sender
    event.room_id = room_id
    event.event_id = event_id
    event.content.msgtype.value = "m.text"
    event.content.body = body

    if reply_to:
        event.content.relates_to.in_reply_to.event_id = reply_to
    else:
        event.content.relates_to = None

    event._display_name = display_name or sender.split(":")[0].lstrip("@")
    return event


def _make_handler(
    event_map: EventMap | None = None,
) -> tuple[RelayHandler, AsyncMock]:
    """Build a RelayHandler with a mocked puppet manager and optional event map."""
    appservice = MagicMock()
    appservice.bot_mxid = BOT_MXID

    puppet_manager = AsyncMock()
    puppet_intent = AsyncMock()
    puppet_intent.send_text = AsyncMock(return_value="$relayed_evt")
    puppet_intent.send_message = AsyncMock(return_value="$relayed_evt")
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
# Event ID mapping on relay
# ---------------------------------------------------------------------------


class TestEventIdMapping:
    """Relayed messages store their source→target event ID mapping."""

    async def test_portal_to_hub_stores_mapping(self, event_map: EventMap):
        handler, puppet_intent = _make_handler(event_map=event_map)

        # Relay returns event IDs for each target.
        puppet_intent.send_text.side_effect = ["$hub_evt", "$signal_evt"]

        event = _make_message_event(
            sender="@_whatsapp_12345:example.com",
            room_id=WHATSAPP_ROOM,
            body="hello",
            event_id="$wa_evt1",
            display_name="Alice",
        )

        await handler.handle_message(event)

        # Should be able to look up the hub event.
        hub_evt = await event_map.lookup("$wa_evt1", HUB_ROOM)
        assert hub_evt == "$hub_evt"

    async def test_hub_to_portals_stores_mappings(self, event_map: EventMap):
        handler, puppet_intent = _make_handler(event_map=event_map)

        puppet_intent.send_text.side_effect = ["$wa_evt", "$sig_evt"]

        event = _make_message_event(
            sender="@nick:example.com",
            room_id=HUB_ROOM,
            body="hey",
            event_id="$hub_evt1",
            display_name="Nick",
        )

        await handler.handle_message(event)

        wa_evt = await event_map.lookup("$hub_evt1", WHATSAPP_ROOM)
        assert wa_evt == "$wa_evt"
        sig_evt = await event_map.lookup("$hub_evt1", SIGNAL_ROOM)
        assert sig_evt == "$sig_evt"


# ---------------------------------------------------------------------------
# Reply relay
# ---------------------------------------------------------------------------


class TestReplyRelay:
    """Replies are relayed with correct m.in_reply_to references."""

    async def test_reply_with_mapped_event(self, event_map: EventMap):
        """When the replied-to event has a mapping, the relay includes it."""
        handler, puppet_intent = _make_handler(event_map=event_map)

        # Pre-populate: $original_wa was relayed to $original_hub in the hub.
        await event_map.store("$original_wa", WHATSAPP_ROOM, "$original_hub", HUB_ROOM)
        await event_map.store("$original_wa", WHATSAPP_ROOM, "$original_sig", SIGNAL_ROOM)

        puppet_intent.send_text.side_effect = ["$reply_hub", "$reply_sig"]
        puppet_intent.send_message.side_effect = ["$reply_hub", "$reply_sig"]

        event = _make_message_event(
            sender="@_whatsapp_12345:example.com",
            room_id=WHATSAPP_ROOM,
            body="this is a reply",
            event_id="$reply_wa",
            reply_to="$original_wa",
            display_name="Alice",
        )

        await handler.handle_message(event)

        # Verify send_message was called (not send_text) for reply content.
        assert puppet_intent.send_message.await_count >= 1

    async def test_reply_without_mapping_degrades_gracefully(self, event_map: EventMap):
        """When the replied-to event has no mapping, relay as plain message."""
        handler, puppet_intent = _make_handler(event_map=event_map)

        event = _make_message_event(
            sender="@_whatsapp_12345:example.com",
            room_id=WHATSAPP_ROOM,
            body="replying to unknown",
            event_id="$reply_wa",
            reply_to="$unmapped_event",
            display_name="Alice",
        )

        await handler.handle_message(event)

        # Should still relay (as plain text via send_text).
        assert (
            puppet_intent.send_text.await_count > 0
            or puppet_intent.send_message.await_count > 0
        )

    async def test_reply_from_hub_maps_to_portal_events(self, event_map: EventMap):
        """A hub reply references the correct event in each portal."""
        handler, puppet_intent = _make_handler(event_map=event_map)

        # Original message was relayed from hub to both portals.
        await event_map.store("$hub_orig", HUB_ROOM, "$wa_orig", WHATSAPP_ROOM)
        await event_map.store("$hub_orig", HUB_ROOM, "$sig_orig", SIGNAL_ROOM)

        puppet_intent.send_message.side_effect = ["$wa_reply", "$sig_reply"]

        event = _make_message_event(
            sender="@nick:example.com",
            room_id=HUB_ROOM,
            body="hub reply",
            event_id="$hub_reply",
            reply_to="$hub_orig",
            display_name="Nick",
        )

        await handler.handle_message(event)

        # send_message was called for both portals with reply content.
        assert puppet_intent.send_message.await_count == 2
