"""Shared fixtures for relay appservice tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from appservice.event_map import EventMap

# Canonical IDs used across the test suite.
BOT_MXID = "@relay-bot:example.com"
DOMAIN = "example.com"
WHATSAPP_ROOM = "!whatsapp:example.com"
SIGNAL_ROOM = "!signal:example.com"
HUB_ROOM = "!hub:example.com"

PORTAL_ROOMS = {
    WHATSAPP_ROOM: "WhatsApp",
    SIGNAL_ROOM: "Signal",
}
