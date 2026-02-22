"""Shared fixtures and fake types for relay bot tests."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from unittest.mock import AsyncMock

import pytest

# --- Environment variables required at import time by relay_bot.py ---
# Set before the module is first imported so module-level code succeeds.

os.environ.setdefault("MATRIX_HOMESERVER", "http://localhost:8008")
os.environ.setdefault("MATRIX_USER", "@relaybot:example.com")
os.environ.setdefault("MATRIX_PASSWORD", "test-password")
os.environ.setdefault("WHATSAPP_ROOM_ID", "!whatsapp:example.com")
os.environ.setdefault("HUB_ROOM_ID", "!hub:example.com")

# Now it's safe to import the module.
import relay_bot  # noqa: E402

# Canonical IDs used throughout the test suite.
MY_USER = "@relaybot:example.com"
WHATSAPP_ROOM = "!whatsapp:example.com"
HUB_ROOM = "!hub:example.com"


# ---------------------------------------------------------------------------
# Lightweight fakes (clearer than unittest.mock specs)
# ---------------------------------------------------------------------------


@dataclass
class FakeUser:
    """Minimal stand-in for ``nio.MatrixUser``."""

    display_name: str | None = None


@dataclass
class FakeRoom:
    """Minimal stand-in for ``nio.MatrixRoom``."""

    room_id: str
    users: dict[str, FakeUser] = field(default_factory=dict)


@dataclass
class FakeEvent:
    """Minimal stand-in for ``nio.RoomMessageText``."""

    sender: str
    body: str


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client() -> AsyncMock:
    """An ``AsyncMock`` standing in for ``nio.AsyncClient``."""
    mock = AsyncMock()
    mock.room_send = AsyncMock()
    return mock


@pytest.fixture()
def on_message(client: AsyncMock):
    """The relay callback, ready to call as ``await on_message(room, event)``."""
    return relay_bot.make_on_message(
        client, MY_USER, {WHATSAPP_ROOM: "WhatsApp"}, HUB_ROOM,
    )


@pytest.fixture()
def wa_room() -> FakeRoom:
    """A ``FakeRoom`` representing the WhatsApp portal room."""
    return FakeRoom(room_id=WHATSAPP_ROOM)


@pytest.fixture()
def hub_room() -> FakeRoom:
    """A ``FakeRoom`` representing the superbridge hub room."""
    return FakeRoom(room_id=HUB_ROOM)
