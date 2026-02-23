"""Unit tests for the event ID mapping store.

Verifies that :class:`EventMap` correctly stores, looks up, and cleans up
source→target event ID mappings used for reply and reaction relay.

All tests use in-memory SQLite (``:memory:``) for speed.
"""

from __future__ import annotations

import time

import pytest

from appservice.event_map import EventMap


@pytest.fixture()
async def event_map() -> EventMap:
    """An in-memory EventMap, ready to use."""
    em = EventMap(":memory:")
    await em.open()
    yield em
    await em.close()


# ---------------------------------------------------------------------------
# store / lookup
# ---------------------------------------------------------------------------


class TestStoreAndLookup:

    async def test_store_and_lookup(self, event_map: EventMap):
        await event_map.store(
            source_event_id="$src1",
            source_room_id="!portal:example.com",
            target_event_id="$tgt1",
            target_room_id="!hub:example.com",
        )

        result = await event_map.lookup(
            source_event_id="$src1",
            target_room_id="!hub:example.com",
        )

        assert result == "$tgt1"

    async def test_lookup_missing_returns_none(self, event_map: EventMap):
        result = await event_map.lookup(
            source_event_id="$nonexistent",
            target_room_id="!hub:example.com",
        )

        assert result is None

    async def test_lookup_wrong_target_room_returns_none(self, event_map: EventMap):
        await event_map.store(
            source_event_id="$src1",
            source_room_id="!portal:example.com",
            target_event_id="$tgt1",
            target_room_id="!hub:example.com",
        )

        result = await event_map.lookup(
            source_event_id="$src1",
            target_room_id="!other:example.com",
        )

        assert result is None

    async def test_multiple_targets_for_same_source(self, event_map: EventMap):
        """One source event can map to different targets in different rooms."""
        await event_map.store("$src1", "!portal:ex.com", "$tgt_hub", "!hub:ex.com")
        await event_map.store("$src1", "!portal:ex.com", "$tgt_wa", "!wa:ex.com")

        assert await event_map.lookup("$src1", "!hub:ex.com") == "$tgt_hub"
        assert await event_map.lookup("$src1", "!wa:ex.com") == "$tgt_wa"

    async def test_reverse_lookup(self, event_map: EventMap):
        """Can also look up the target event from a different direction."""
        await event_map.store("$src1", "!portal:ex.com", "$tgt1", "!hub:ex.com")

        # Looking up the target as a source should also work (for reactions
        # on relayed messages).
        await event_map.store("$tgt1", "!hub:ex.com", "$tgt_wa", "!wa:ex.com")
        assert await event_map.lookup("$tgt1", "!wa:ex.com") == "$tgt_wa"


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------


class TestCleanup:

    async def test_cleanup_removes_old_entries(self, event_map: EventMap):
        # Insert a mapping, then manually age it.
        await event_map.store("$old", "!p:ex.com", "$old_t", "!h:ex.com")
        # Set created_at to 31 days ago.
        old_ts = time.time() - (31 * 86400)
        await event_map._db.execute(
            "UPDATE event_group_events SET created_at = ? WHERE event_id IN (?, ?)",
            (old_ts, "$old", "$old_t"),
        )
        await event_map._db.commit()

        removed = await event_map.cleanup(max_age_days=30)

        assert removed >= 1
        assert await event_map.lookup("$old", "!h:ex.com") is None

    async def test_cleanup_keeps_recent_entries(self, event_map: EventMap):
        await event_map.store("$new", "!p:ex.com", "$new_t", "!h:ex.com")

        removed = await event_map.cleanup(max_age_days=30)

        assert removed == 0
        assert await event_map.lookup("$new", "!h:ex.com") == "$new_t"
