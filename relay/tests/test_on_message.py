"""Acceptance tests for the on_message relay callback.

These cover the end-to-end behaviour of the relay: messages forwarded in both
directions, all three loop-prevention layers, unrelated-room filtering, and
error resilience.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from tests.conftest import FakeEvent, FakeRoom, FakeUser, HUB_ROOM, MY_USER, WHATSAPP_ROOM


# -- Tier 1: happy-path relay ------------------------------------------------


async def test_whatsapp_message_relayed_to_hub(
    on_message, client: AsyncMock, wa_room: FakeRoom,
):
    """A regular WhatsApp user's message is relayed to the hub room."""
    wa_room.users["@alice:example.com"] = FakeUser(display_name="Alice")
    event = FakeEvent(sender="@alice:example.com", body="hello from WhatsApp")

    await on_message(wa_room, event)

    client.room_send.assert_awaited_once()
    call_kwargs = client.room_send.await_args
    assert call_kwargs[0][0] == HUB_ROOM
    body = call_kwargs[1]["content"]["body"]
    assert body == "**Alice (WhatsApp):** hello from WhatsApp"


async def test_hub_message_relayed_to_whatsapp(
    on_message, client: AsyncMock, hub_room: FakeRoom,
):
    """A native Matrix user's message in the hub is relayed to WhatsApp."""
    hub_room.users["@nick:example.com"] = FakeUser(display_name="Nick")
    event = FakeEvent(sender="@nick:example.com", body="hey from Element")

    await on_message(hub_room, event)

    client.room_send.assert_awaited_once()
    call_kwargs = client.room_send.await_args
    assert call_kwargs[0][0] == WHATSAPP_ROOM
    body = call_kwargs[1]["content"]["body"]
    assert body == "**Nick (Matrix):** hey from Element"


# -- Tier 1: loop prevention layer 1 — own messages --------------------------


async def test_own_messages_ignored(
    on_message, client: AsyncMock, wa_room: FakeRoom,
):
    """The bot must ignore its own messages to prevent infinite loops."""
    event = FakeEvent(sender=MY_USER, body="I should not be relayed")

    await on_message(wa_room, event)

    client.room_send.assert_not_awaited()


# -- Tier 1: loop prevention layer 2 — bridge bots / puppets -----------------


async def test_bridge_bot_messages_ignored(
    on_message, client: AsyncMock, wa_room: FakeRoom,
):
    """Messages from bridge bot accounts are not relayed."""
    event = FakeEvent(sender="@whatsappbot:example.com", body="status update")

    await on_message(wa_room, event)

    client.room_send.assert_not_awaited()


async def test_whatsapp_puppet_messages_ignored(
    on_message, client: AsyncMock, hub_room: FakeRoom,
):
    """WhatsApp puppet users (e.g. ``@_whatsapp_123:…``) are ignored."""
    event = FakeEvent(sender="@_whatsapp_12345:example.com", body="puppeted msg")

    await on_message(hub_room, event)

    client.room_send.assert_not_awaited()


async def test_discord_puppet_messages_ignored(
    on_message, client: AsyncMock, hub_room: FakeRoom,
):
    """Discord puppet users (e.g. ``@_discord_789:…``) are ignored."""
    event = FakeEvent(sender="@_discord_789:example.com", body="puppeted msg")

    await on_message(hub_room, event)

    client.room_send.assert_not_awaited()


# -- Tier 1: loop prevention layer 3 — attribution patterns ------------------


async def test_bold_attribution_ignored(
    on_message, client: AsyncMock, wa_room: FakeRoom,
):
    """Messages already wrapped in bold attribution are not re-relayed."""
    event = FakeEvent(
        sender="@someone:example.com",
        body="**Alice (WhatsApp):** already attributed",
    )

    await on_message(wa_room, event)

    client.room_send.assert_not_awaited()


async def test_plain_colon_attribution_ignored(
    on_message, client: AsyncMock, wa_room: FakeRoom,
):
    """Plain ``Name: msg`` attribution (Discord relay mode) is not re-relayed."""
    event = FakeEvent(
        sender="@someone:example.com",
        body="Alice: hello from Discord relay",
    )

    await on_message(wa_room, event)

    client.room_send.assert_not_awaited()


# -- Tier 1: unrelated room --------------------------------------------------


async def test_unrelated_room_ignored(on_message, client: AsyncMock):
    """Messages from rooms that are neither WhatsApp nor hub are ignored."""
    other_room = FakeRoom(room_id="!other:example.com")
    event = FakeEvent(sender="@alice:example.com", body="off-topic")

    await on_message(other_room, event)

    client.room_send.assert_not_awaited()


# -- Tier 1: error resilience ------------------------------------------------


async def test_room_send_exception_logged_not_raised(
    on_message, client: AsyncMock, wa_room: FakeRoom,
):
    """If ``room_send`` raises, the exception is logged but not propagated."""
    wa_room.users["@alice:example.com"] = FakeUser(display_name="Alice")
    event = FakeEvent(sender="@alice:example.com", body="boom")
    client.room_send.side_effect = RuntimeError("network down")

    # Must not raise.
    await on_message(wa_room, event)

    client.room_send.assert_awaited_once()
