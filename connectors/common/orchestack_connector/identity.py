"""Identity mapping service - maps platform sender IDs to Orchestack identities."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

import asyncpg  # type: ignore[import-untyped]
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS connector_identity_mapping (
    id              BIGSERIAL PRIMARY KEY,
    connector_type  TEXT NOT NULL,
    connector_sender_id TEXT NOT NULL,
    oidc_sub        TEXT,
    ldap_groups     TEXT[] DEFAULT '{}',
    display_name    TEXT NOT NULL DEFAULT 'Anonymous',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (connector_type, connector_sender_id)
);
"""

_UPSERT_SQL = """
INSERT INTO connector_identity_mapping
    (connector_type, connector_sender_id, oidc_sub, ldap_groups, display_name)
VALUES ($1, $2, $3, $4, $5)
ON CONFLICT (connector_type, connector_sender_id)
DO UPDATE SET oidc_sub = EXCLUDED.oidc_sub,
              ldap_groups = EXCLUDED.ldap_groups,
              display_name = EXCLUDED.display_name
RETURNING *;
"""

_SELECT_SQL = """
SELECT * FROM connector_identity_mapping
WHERE connector_type = $1 AND connector_sender_id = $2;
"""

_DELETE_SQL = """
DELETE FROM connector_identity_mapping
WHERE connector_type = $1 AND connector_sender_id = $2;
"""

_LIST_SQL = """
SELECT * FROM connector_identity_mapping
WHERE connector_type = $1
ORDER BY created_at;
"""


# ---------------------------------------------------------------------------
# Pydantic model
# ---------------------------------------------------------------------------


class IdentityMapping(BaseModel):
    """A single identity mapping record."""

    connector_type: str
    connector_sender_id: str
    oidc_sub: str | None = None
    ldap_groups: list[str] = Field(default_factory=list)
    display_name: str = "Anonymous"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Anonymous fallback
# ---------------------------------------------------------------------------


def _anonymous_identity(connector_type: str, sender_id: str) -> IdentityMapping:
    return IdentityMapping(
        connector_type=connector_type,
        connector_sender_id=sender_id,
        oidc_sub=None,
        ldap_groups=[],
        display_name="Anonymous",
        created_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Cache entry
# ---------------------------------------------------------------------------


class _CacheEntry:
    __slots__ = ("expires_at", "mapping")

    def __init__(self, mapping: IdentityMapping, ttl: float) -> None:
        self.mapping = mapping
        self.expires_at = time.monotonic() + ttl


# ---------------------------------------------------------------------------
# IdentityMapper
# ---------------------------------------------------------------------------


class IdentityMapper:
    """PostgreSQL-backed identity lookup with an in-memory TTL cache.

    Parameters
    ----------
    database_url:
        asyncpg-compatible DSN.
    cache_ttl_s:
        How long to keep resolved mappings in the in-process cache (seconds).
    """

    def __init__(self, database_url: str, cache_ttl_s: float = 300.0) -> None:
        self._database_url = database_url
        self._cache_ttl_s = cache_ttl_s
        self._pool: asyncpg.Pool | None = None  # type: ignore[type-arg]
        self._cache: dict[tuple[str, str], _CacheEntry] = {}

    # -- lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        """Create connection pool and ensure the mapping table exists."""
        self._pool = await asyncpg.create_pool(dsn=self._database_url, min_size=1, max_size=5)
        async with self._pool.acquire() as conn:
            await conn.execute(_CREATE_TABLE_SQL)
        logger.info("IdentityMapper started - table ensured")

    async def stop(self) -> None:
        """Close the connection pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
        self._cache.clear()

    # -- public API ----------------------------------------------------------

    async def map_sender(self, connector_type: str, sender_id: str) -> IdentityMapping:
        """Resolve a platform sender to an :class:`IdentityMapping`.

        Uses the in-memory cache first, then falls back to PostgreSQL.
        If no row exists the caller gets an *anonymous* identity.
        """
        key = (connector_type, sender_id)

        # 1. cache hit?
        entry = self._cache.get(key)
        if entry is not None and entry.expires_at > time.monotonic():
            return entry.mapping

        # 2. DB lookup
        mapping = await self._db_lookup(connector_type, sender_id)
        if mapping is None:
            mapping = _anonymous_identity(connector_type, sender_id)

        # 3. populate cache
        self._cache[key] = _CacheEntry(mapping, self._cache_ttl_s)
        return mapping

    async def create_mapping(
        self,
        connector_type: str,
        connector_sender_id: str,
        *,
        oidc_sub: str | None = None,
        ldap_groups: list[str] | None = None,
        display_name: str = "Anonymous",
    ) -> IdentityMapping:
        """Create or update an identity mapping and return the result."""
        assert self._pool is not None, "IdentityMapper not started"
        groups = ldap_groups or []
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                _UPSERT_SQL,
                connector_type,
                connector_sender_id,
                oidc_sub,
                groups,
                display_name,
            )
        mapping = self._row_to_mapping(row)
        # bust cache
        self._cache.pop((connector_type, connector_sender_id), None)
        return mapping

    async def delete_mapping(self, connector_type: str, connector_sender_id: str) -> bool:
        """Delete a mapping.  Returns *True* if a row was deleted."""
        assert self._pool is not None, "IdentityMapper not started"
        async with self._pool.acquire() as conn:
            result = await conn.execute(_DELETE_SQL, connector_type, connector_sender_id)
        self._cache.pop((connector_type, connector_sender_id), None)
        return result == "DELETE 1"

    async def list_mappings(self, connector_type: str) -> list[IdentityMapping]:
        """List all mappings for a given connector type."""
        assert self._pool is not None, "IdentityMapper not started"
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(_LIST_SQL, connector_type)
        return [self._row_to_mapping(r) for r in rows]

    # -- internals -----------------------------------------------------------

    async def _db_lookup(self, connector_type: str, sender_id: str) -> IdentityMapping | None:
        assert self._pool is not None, "IdentityMapper not started"
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(_SELECT_SQL, connector_type, sender_id)
        if row is None:
            return None
        return self._row_to_mapping(row)

    @staticmethod
    def _row_to_mapping(row: Any) -> IdentityMapping:
        return IdentityMapping(
            connector_type=row["connector_type"],
            connector_sender_id=row["connector_sender_id"],
            oidc_sub=row["oidc_sub"],
            ldap_groups=list(row["ldap_groups"]) if row["ldap_groups"] else [],
            display_name=row["display_name"],
            created_at=row["created_at"],
        )
