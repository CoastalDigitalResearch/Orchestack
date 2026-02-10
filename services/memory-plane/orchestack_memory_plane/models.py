"""Pydantic models for the Memory Plane service."""

from __future__ import annotations

import enum
from datetime import UTC, datetime
from typing import Any

import ulid
from pydantic import BaseModel, Field


class MemoryType(enum.StrEnum):
    """Lifecycle tier for a memory entry."""

    ephemeral = "ephemeral"
    short_term = "short_term"
    long_term = "long_term"


def _ulid_now() -> str:
    return str(ulid.new())


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Core domain model
# ---------------------------------------------------------------------------


class MemoryEntry(BaseModel):
    """A single unit of agent memory."""

    id: str = Field(default_factory=_ulid_now, description="ULID primary key")
    tenant_id: str
    session_id: str
    agent_id: str
    content: str
    memory_type: MemoryType = MemoryType.ephemeral
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)
    expires_at: datetime | None = None


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class WriteRequest(BaseModel):
    """Payload accepted by ``POST /v1/memory/write``."""

    tenant_id: str
    session_id: str
    agent_id: str
    content: str
    memory_type: MemoryType = MemoryType.ephemeral
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchRequest(BaseModel):
    """Payload accepted by ``POST /v1/memory/search``."""

    tenant_id: str
    query: str
    session_id: str | None = None
    agent_id: str | None = None
    memory_type: MemoryType | None = None
    limit: int = Field(default=10, ge=1, le=200)


class SearchResult(BaseModel):
    """Response returned by the search endpoint."""

    entries: list[MemoryEntry]
    total: int


class PromoteRequest(BaseModel):
    """Payload accepted by ``POST /v1/memory/promote``."""

    entry_id: str
    target_type: MemoryType

    # Only short_term or long_term are valid promotion targets.  We validate
    # at the application layer rather than restricting the enum so that the
    # error message is clearer.
