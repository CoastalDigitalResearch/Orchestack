"""ToolDescriptor -- the canonical Pydantic model for an Orchestack tool."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class RiskClass(StrEnum):
    """How dangerous a tool invocation can be."""

    READ_ONLY = "read_only"
    WRITE_LOCAL = "write_local"
    WRITE_EXTERNAL = "write_external"
    DESTRUCTIVE = "destructive"


class Idempotency(StrEnum):
    """Whether repeated calls produce the same result."""

    IDEMPOTENT = "idempotent"
    NON_IDEMPOTENT = "non_idempotent"


class DataClassification(StrEnum):
    """Sensitivity level of data the tool handles."""

    PUBLIC = "public"
    INTERNAL = "internal"
    SENSITIVE = "sensitive"
    RESTRICTED = "restricted"


class AuditLevel(StrEnum):
    """How much detail to log for each invocation."""

    NONE = "none"
    METADATA = "metadata"
    FULL = "full"


class ToolDescriptor(BaseModel):
    """Full descriptor for a single Orchestack tool.

    This model mirrors the ToolDescriptor definition in the
    extension-manifest JSON Schema.
    """

    tool_id: str = Field(
        ...,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$",
        description="Globally unique tool identifier",
    )
    name: str = Field(..., description="Human-readable tool name")
    description: str = Field(..., description="What the tool does")

    input_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON Schema describing the tool input",
    )
    output_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON Schema describing the tool output",
    )

    risk_class: RiskClass = Field(
        default=RiskClass.READ_ONLY,
        description="Risk classification for the tool",
    )
    idempotency: Idempotency = Field(
        default=Idempotency.NON_IDEMPOTENT,
        description="Whether repeated invocations produce the same result",
    )
    required_capabilities: list[str] = Field(
        default_factory=list,
        description="Runtime capabilities required (e.g. fs.read, net.egress)",
    )
    data_classification: DataClassification = Field(
        default=DataClassification.INTERNAL,
        description="Data sensitivity classification",
    )
    audit_level: AuditLevel = Field(
        default=AuditLevel.METADATA,
        description="Audit logging level for invocations",
    )
