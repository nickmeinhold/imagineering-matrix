"""SQLite-backed event ID mapping for reply and reaction relay.

Every relayed message stores an event-group mapping so replies and reactions
can reference the correct event in *any* target room, regardless of which
room the reply/reaction originates from.

Uses ``aiosqlite`` with WAL mode for crash-safe, concurrent-read access —
ideal for a single-process bot on a Raspberry Pi.
"""

from __future__ import annotations

import logging
import time
import uuid

import aiosqlite

log = logging.getLogger(__name__)

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS event_groups (
    group_id   TEXT PRIMARY KEY,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS event_group_events (
    group_id   TEXT NOT NULL,
    room_id    TEXT NOT NULL,
    event_id   TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (group_id, room_id),
    UNIQUE (event_id),
    FOREIGN KEY (group_id) REFERENCES event_groups(group_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_event_group_events_event
    ON event_group_events (event_id);
CREATE INDEX IF NOT EXISTS idx_event_group_events_created
    ON event_group_events (created_at);
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
        await self._maybe_migrate_legacy()
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
        *,
        created_at: float | None = None,
    ) -> None:
        """Store a source→target event mapping.

        The mapping is stored as an event group so lookups can work in any
        direction (replies/reactions from any room).
        """
        assert self._db is not None
        now = created_at or time.time()
        group_id = await self._ensure_group(source_event_id, target_event_id, now)
        await self._upsert_event(group_id, source_room_id, source_event_id, now)
        await self._upsert_event(group_id, target_room_id, target_event_id, now)
        await self._db.commit()

    async def lookup(
        self,
        source_event_id: str,
        target_room_id: str,
    ) -> str | None:
        """Look up the target event ID for a source event in a specific room."""
        assert self._db is not None
        group_row = await self._db.execute(
            "SELECT group_id FROM event_group_events WHERE event_id = ?",
            (source_event_id,),
        )
        group = await group_row.fetchone()
        if not group:
            return None
        cursor = await self._db.execute(
            "SELECT event_id FROM event_group_events "
            "WHERE group_id = ? AND room_id = ?",
            (group[0], target_room_id),
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
            "DELETE FROM event_group_events WHERE created_at < ?",
            (cutoff,),
        )
        await self._db.commit()
        removed = cursor.rowcount
        await self._db.execute(
            "DELETE FROM event_groups "
            "WHERE group_id NOT IN (SELECT DISTINCT group_id FROM event_group_events)",
        )
        await self._db.commit()
        if removed:
            log.info("Cleaned up %d old event mappings", removed)
        return removed

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _upsert_event(
        self,
        group_id: str,
        room_id: str,
        event_id: str,
        created_at: float,
    ) -> None:
        assert self._db is not None
        await self._db.execute(
            "INSERT OR REPLACE INTO event_group_events "
            "(group_id, room_id, event_id, created_at) VALUES (?, ?, ?, ?)",
            (group_id, room_id, event_id, created_at),
        )

    async def _ensure_group(
        self,
        source_event_id: str,
        target_event_id: str,
        created_at: float,
    ) -> str:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT group_id FROM event_group_events WHERE event_id IN (?, ?)",
            (source_event_id, target_event_id),
        )
        group_ids = [row[0] for row in await cursor.fetchall()]
        group_ids = list(dict.fromkeys(group_ids))  # stable dedupe

        if not group_ids:
            group_id = uuid.uuid4().hex
            await self._db.execute(
                "INSERT INTO event_groups (group_id, created_at) VALUES (?, ?)",
                (group_id, created_at),
            )
            return group_id

        group_id = group_ids[0]
        if len(group_ids) > 1:
            await self._merge_groups(group_id, group_ids[1:])
        return group_id

    async def _merge_groups(self, target_group: str, other_groups: list[str]) -> None:
        assert self._db is not None
        for group_id in other_groups:
            cursor = await self._db.execute(
                "SELECT room_id, event_id, created_at FROM event_group_events "
                "WHERE group_id = ?",
                (group_id,),
            )
            rows = await cursor.fetchall()
            for room_id, event_id, created_at in rows:
                existing = await self._db.execute(
                    "SELECT 1 FROM event_group_events WHERE group_id = ? AND room_id = ?",
                    (target_group, room_id),
                )
                if await existing.fetchone():
                    continue
                await self._db.execute(
                    "INSERT OR IGNORE INTO event_group_events "
                    "(group_id, room_id, event_id, created_at) VALUES (?, ?, ?, ?)",
                    (target_group, room_id, event_id, created_at),
                )
            await self._db.execute(
                "DELETE FROM event_group_events WHERE group_id = ?",
                (group_id,),
            )
            await self._db.execute(
                "DELETE FROM event_groups WHERE group_id = ?",
                (group_id,),
            )
        await self._db.commit()

    async def _maybe_migrate_legacy(self) -> None:
        assert self._db is not None
        legacy_exists = await self._table_exists("event_map")
        if not legacy_exists:
            return
        cursor = await self._db.execute(
            "SELECT COUNT(*) FROM event_group_events",
        )
        row = await cursor.fetchone()
        if row and row[0] > 0:
            return

        cursor = await self._db.execute(
            "SELECT source_event_id, source_room_id, target_event_id, target_room_id, created_at "
            "FROM event_map",
        )
        rows = await cursor.fetchall()
        if not rows:
            return
        for source_event_id, source_room_id, target_event_id, target_room_id, created_at in rows:
            await self.store(
                source_event_id,
                source_room_id,
                target_event_id,
                target_room_id,
                created_at=created_at,
            )
        log.info("Migrated %d legacy event mappings", len(rows))

    async def _table_exists(self, table: str) -> bool:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        )
        return await cursor.fetchone() is not None
