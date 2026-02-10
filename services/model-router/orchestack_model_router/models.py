"""Pydantic models for the Model Router service."""

from __future__ import annotations

import enum
from datetime import UTC, datetime
from typing import Any

import ulid
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Locality(enum.StrEnum):
    """Where the model is hosted."""

    LOCAL = "local"
    CLOUD = "cloud"


class SizeClass(enum.StrEnum):
    """Rough grouping used by the fallback chain."""

    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


class PrivacyClass(enum.StrEnum):
    """Data sensitivity class the model is allowed to see."""

    PUBLIC = "public"
    INTERNAL = "internal"
    SENSITIVE = "sensitive"
    RESTRICTED = "restricted"


class ModelStatus(enum.StrEnum):
    """Operational status of a registered model."""

    ACTIVE = "active"
    DRAINING = "draining"
    DISABLED = "disabled"


class LatencyRequirement(enum.StrEnum):
    """Latency preference expressed by the caller."""

    LOW = "low"  # interactive / streaming
    NORMAL = "normal"
    HIGH = "high"  # batch, can wait


class ProviderType(enum.StrEnum):
    """Supported provider protocols."""

    OPENAI_COMPATIBLE = "openai_compatible"
    ANTHROPIC = "anthropic"


# ---------------------------------------------------------------------------
# Model Registration
# ---------------------------------------------------------------------------


class CostPerToken(BaseModel):
    """Per-token cost in USD (or smallest currency unit)."""

    input: float = 0.0
    output: float = 0.0


class ModelRecord(BaseModel):
    """A registered model available for routing."""

    id: str = Field(default_factory=lambda: str(ulid.new()))
    provider: ProviderType
    model_name: str
    endpoint: str
    api_key_ref: str | None = None  # Vault path or env-var name
    context_length: int = 4096
    cost_per_token: CostPerToken = Field(default_factory=CostPerToken)
    locality: Locality = Locality.LOCAL
    size_class: SizeClass = SizeClass.SMALL
    capabilities: list[str] = Field(default_factory=list)
    privacy_class: PrivacyClass = PrivacyClass.PUBLIC
    status: ModelStatus = ModelStatus.ACTIVE
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Routing Request / Response
# ---------------------------------------------------------------------------


class ChatMessage(BaseModel):
    """Single chat message (OpenAI-style)."""

    role: str  # "system", "user", "assistant", "tool"
    content: str | None = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


class RoutingRequest(BaseModel):
    """Inbound routing request - either via NATS or HTTP."""

    request_id: str = Field(default_factory=lambda: str(ulid.new()))
    messages: list[ChatMessage]
    privacy_tags: list[str] = Field(default_factory=list)
    budget_remaining: float | None = None  # USD
    task_complexity_hint: str | None = None  # "simple", "moderate", "complex"
    latency_requirement: LatencyRequirement = LatencyRequirement.NORMAL
    context_length_needed: int | None = None
    capability_grant_id: str | None = None
    preferred_model_id: str | None = None
    stream: bool = False
    extra_params: dict[str, Any] = Field(default_factory=dict)

    # Envelope metadata (set when arriving via NATS)
    tenant_id: str | None = None
    correlation_id: str | None = None


class TokenUsage(BaseModel):
    """Token consumption for a single completion."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class ProviderResponse(BaseModel):
    """Raw response from a provider."""

    content: str | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
    model: str = ""
    finish_reason: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


class RoutingResponse(BaseModel):
    """Full response returned after routing + provider call."""

    request_id: str
    model_id: str
    provider: ProviderType
    model_name: str
    response: ProviderResponse
    cost: float = 0.0  # computed cost for this call
    latency_ms: float = 0.0
    fallback_chain_used: list[str] = Field(default_factory=list)


class RoutingError(BaseModel):
    """Emitted on router.failed."""

    request_id: str
    error: str
    fallback_chain_attempted: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class RoutingMetrics(BaseModel):
    """Published on router.metrics after every successful completion."""

    request_id: str
    tenant_id: str | None = None
    model_id: str
    model_name: str
    provider: ProviderType
    locality: Locality
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    latency_ms: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
