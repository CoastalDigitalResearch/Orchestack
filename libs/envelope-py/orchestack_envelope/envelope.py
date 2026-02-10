"""Event envelope model per RFC-001 §5.1."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import ulid
from pydantic import BaseModel, Field


class Actor(BaseModel):
    """Entity that produced the event."""

    type: str  # "user", "agent", "system", "connector"
    id: str
    name: str | None = None


class TraceContext(BaseModel):
    """W3C traceparent/tracestate for distributed tracing."""

    traceparent: str | None = None
    tracestate: str | None = None


class Envelope(BaseModel):
    """RFC-001 §5.1 Event Envelope."""

    version: str = "1.0"
    event_id: str = Field(default_factory=lambda: str(ulid.new()))
    event_type: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    actor: Actor
    tenant_id: str
    correlation_id: str | None = None
    idempotency_key: str | None = None
    priority: int = 0
    payload_ref: str | None = None
    schema_ref: str | None = Field(None, alias="schema")
    trace: TraceContext | None = None
    payload: dict[str, Any] | None = None

    model_config = {"populate_by_name": True}

    def to_json(self) -> str:
        return self.model_dump_json(by_alias=True, exclude_none=True)

    @classmethod
    def from_json(cls, data: str | bytes) -> Envelope:
        return cls.model_validate_json(data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, exclude_none=True)
