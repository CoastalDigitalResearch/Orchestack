"""Pydantic models for the DLP Scanner service."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ScanRequest(BaseModel):
    """Payload submitted to the scan endpoint."""

    content: str
    content_type: Literal["message", "code", "file"] = "message"
    context: dict | None = None


class Finding(BaseModel):
    """A single piece of sensitive data discovered during a scan."""

    category: Literal[
        "pii",
        "phi",
        "credential",
        "api_key",
        "secret",
        "ssn",
        "email",
        "phone",
        "credit_card",
        "ip_address",
        "jwt",
    ]
    matched_text: str
    start: int
    end: int
    confidence: float = Field(ge=0.0, le=1.0)


class ScanResult(BaseModel):
    """Aggregated result of a DLP scan."""

    findings: list[Finding] = Field(default_factory=list)
    risk_level: Literal["none", "low", "medium", "high", "critical"] = "none"
    tags: set[str] = Field(default_factory=set)
    redacted_content: str | None = None


class RedactRequest(BaseModel):
    """Request to redact sensitive data from content."""

    content: str
    findings: list[Finding]
    mode: Literal["mask", "remove"] = "mask"
