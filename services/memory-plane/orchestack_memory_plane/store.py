"""Postgres-backed memory store using asyncpg."""

from __future__ import annotations

import json
import logging

import asyncpg

from .models import MemoryEntry, MemoryType, SearchRequest, SearchResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQL constants
# ---------------------------------------------------------------------------

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS memory_entries (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    agent_id    TEXT NOT NULL,
    content     TEXT NOT NULL,
    memory_type TEXT NOT NULL DEFAULT 'ephemeral',
    metadata    JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_memory_tenant   ON memory_entries (tenant_id);
CREATE INDEX IF NOT EXISTS idx_memory_session  ON memory_entries (session_id);
CREATE INDEX IF NOT EXISTS idx_memory_agent    ON memory_entries (agent_id);
CREATE INDEX IF NOT EXISTS idx_memory_type     ON memory_entries (memory_type);
CREATE INDEX IF NOT EXISTS idx_memory_expires  ON memory_entries (expires_at)
    WHERE expires_at IS NOT NULL;
"""

INSERT_SQL = """
INSERT INTO memory_entries (id, tenant_id, session_id, agent_id, content, memory_type, metadata, created_at, expires_at)
VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9)
RETURNING *;
"""

GET_SQL = "SELECT * FROM memory_entries WHERE id = $1;"

UPDATE_TYPE_SQL = """
UPDATE memory_entries
   SET memory_type = $2,
       expires_at  = NULL
 WHERE id = $1
RETURNING *;
"""

DELETE_EXPIRED_SQL = """
DELETE FROM memory_entries
 WHERE expires_at IS NOT NULL
   AND expires_at < now()
;
"""


def _row_to_entry(row: asyncpg.Record) -> MemoryEntry:
    """Convert a database row into a ``MemoryEntry``."""
    data = dict(row)
    # asyncpg returns jsonb columns as str or dict depending on version;
    # normalise to dict.
    meta = data.get("metadata")
    if isinstance(meta, str):
        data["metadata"] = json.loads(meta)
    return MemoryEntry(**data)


class MemoryStore:
    """Async Postgres persistence layer for memory entries."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # -- lifecycle -----------------------------------------------------------

    async def ensure_schema(self) -> None:
        """Create the table and indexes if they do not exist."""
        async with self._pool.acquire() as conn:
            await conn.execute(CREATE_TABLE_SQL)
        logger.info("memory_entries schema ensured")

    # -- CRUD ----------------------------------------------------------------

    async def write(self, entry: MemoryEntry) -> MemoryEntry:
        """Persist a new memory entry and return it."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                INSERT_SQL,
                entry.id,
                entry.tenant_id,
                entry.session_id,
                entry.agent_id,
                entry.content,
                entry.memory_type.value,
                json.dumps(entry.metadata),
                entry.created_at,
                entry.expires_at,
            )
        return _row_to_entry(row)

    async def get(self, entry_id: str) -> MemoryEntry | None:
        """Fetch a single entry by its ULID, or ``None`` if missing."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(GET_SQL, entry_id)
        if row is None:
            return None
        return _row_to_entry(row)

    async def search(self, request: SearchRequest) -> SearchResult:
        """Text search over memory entries.

        Uses ``ILIKE`` for now; a future iteration will switch to
        pgvector / full-text search.
        """
        clauses: list[str] = ["tenant_id = $1"]
        params: list[object] = [request.tenant_id]
        idx = 2

        if request.session_id is not None:
            clauses.append(f"session_id = ${idx}")
            params.append(request.session_id)
            idx += 1

        if request.agent_id is not None:
            clauses.append(f"agent_id = ${idx}")
            params.append(request.agent_id)
            idx += 1

        if request.memory_type is not None:
            clauses.append(f"memory_type = ${idx}")
            params.append(request.memory_type.value)
            idx += 1

        clauses.append(f"content ILIKE ${idx}")
        params.append(f"%{request.query}%")
        idx += 1

        where = " AND ".join(clauses)

        # Total count (without LIMIT).
        count_sql = f"SELECT count(*) FROM memory_entries WHERE {where}"
        # Actual rows.
        select_sql = f"SELECT * FROM memory_entries WHERE {where} ORDER BY created_at DESC LIMIT ${idx}"
        params.append(request.limit)

        async with self._pool.acquire() as conn:
            total: int = await conn.fetchval(count_sql, *params[:-1])
            rows = await conn.fetch(select_sql, *params)

        entries = [_row_to_entry(r) for r in rows]
        return SearchResult(entries=entries, total=total)

    async def promote(self, entry_id: str, target_type: MemoryType) -> MemoryEntry | None:
        """Promote an entry to a higher memory tier.

        Returns the updated entry, or ``None`` if *entry_id* was not found.
        Promotion also clears ``expires_at`` so that the entry is no longer
        subject to automatic expiry.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(UPDATE_TYPE_SQL, entry_id, target_type.value)
        if row is None:
            return None
        return _row_to_entry(row)

    async def delete_expired(self) -> int:
        """Remove all entries whose ``expires_at`` is in the past.

        Returns the number of deleted rows.
        """
        async with self._pool.acquire() as conn:
            result: str = await conn.execute(DELETE_EXPIRED_SQL)
        # asyncpg returns e.g. "DELETE 5"
        parts = result.split()
        return int(parts[-1]) if len(parts) > 1 else 0
