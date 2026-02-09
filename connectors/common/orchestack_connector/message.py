"""Normalized message format for all connectors."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AttachmentRef(BaseModel):
    """Reference to an attachment stored in object storage."""

    filename: str
    content_type: str
    size_bytes: int
    payload_ref: str  # s3://<bucket>/<key>


class NormalizedMessage(BaseModel):
    """Common normalized message format per RFC-001 ingress."""

    message_id: str
    connector_type: str  # discord, slack, email, telegram, webchat
    connector_account_id: str
    thread_id: str
    sender_id: str
    sender_display_name: str
    content: str
    attachments: list[AttachmentRef] = Field(default_factory=list)
    timestamp: datetime
    reply_to: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
