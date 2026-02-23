"""SQLite-backed event ID mapping for reply and reaction relay.

Every relayed message stores its source→target event ID mapping so that
replies and reactions can reference the correct event in the target room.

Uses ``aiosqlite`` with WAL mode for crash-safe, concurrent-read access —
ideal for a single-process bot on a Raspberry Pi.
"""

from __future__ import annotations

import logging
import time

import aiosqlite

log = logging.getLogger(__name__)

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS event_map (
    source_event_id TEXT NOT NULL,
    source_room_id  TEXT NOT NULL,
    target_event_id TEXT NOT NULL,
    target_room_id  TEXT NOT NULL,
    created_at      REAL NOT NULL,
    PRIMARY KEY (source_event_id, target_room_id)
);
CREATE INDEX IF NOT EXISTS idx_event_map_created
    ON event_map (created_at);
"""


class EventMap:
    """Async SQLite store for source→target event ID mappings.

    Args:
        db_path: Path to the SQLite database file, or ``":memory:"`` for
            in-memory use (tests).
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def open(self) -> None:
        """Open the database and create the schema."""
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        log.info("Event map database opened: %s", self._db_path)

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    async def store(
        self,
        source_event_id: str,
        source_room_id: str,
        target_event_id: str,
        target_room_id: str,
    ) -> None:
        """Store a source→target event mapping."""
        assert self._db is not None
        await self._db.execute(
            "INSERT OR REPLACE INTO event_map "
            "(source_event_id, source_room_id, target_event_id, target_room_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (source_event_id, source_room_id, target_event_id, target_room_id, time.time()),
        )
        await self._db.commit()

    async def lookup(
        self,
        source_event_id: str,
        target_room_id: str,
    ) -> str | None:
        """Look up the target event ID for a source event in a specific room.

        Returns ``None`` if no mapping exists.
        """
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT target_event_id FROM event_map "
            "WHERE source_event_id = ? AND target_room_id = ?",
            (source_event_id, target_room_id),
        )
        row = await cursor.fetchone()
        return row[0] if row else None

    async def cleanup(self, max_age_days: int = 30) -> int:
        """Delete mappings older than *max_age_days*.

        Returns the number of rows deleted.
        """
        assert self._db is not None
        cutoff = time.time() - (max_age_days * 86400)
        cursor = await self._db.execute(
            "DELETE FROM event_map WHERE created_at < ?",
            (cutoff,),
        )
        await self._db.commit()
        removed = cursor.rowcount
        if removed:
            log.info("Cleaned up %d old event mappings", removed)
        return removed
