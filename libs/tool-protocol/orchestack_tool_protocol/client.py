"""Tool invocation clients -- NATS request/reply and HTTP POST."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import httpx
import nats
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Request / Response envelopes
# ---------------------------------------------------------------------------


class ToolRequest(BaseModel):
    """Canonical request envelope sent to a tool."""

    tool_id: str = Field(..., description="Target tool identifier")
    input: dict[str, Any] = Field(default_factory=dict, description="Tool input payload")
    idempotency_key: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        description="Unique key for deduplication",
    )
    capability_grant_id: str | None = Field(
        default=None,
        description="Capability grant authorising this invocation",
    )
    trace_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        description="Distributed tracing identifier",
    )


class ToolResponse(BaseModel):
    """Canonical response envelope returned by a tool."""

    tool_id: str = Field(..., description="Responding tool identifier")
    output: dict[str, Any] = Field(default_factory=dict, description="Tool output payload")
    error: str | None = Field(default=None, description="Error message, if any")
    duration_ms: float = Field(default=0.0, description="Wall-clock execution time in ms")


# ---------------------------------------------------------------------------
# NATS client
# ---------------------------------------------------------------------------


class NATSToolClient:
    """Invoke tools via NATS request/reply on ``tools.{tool_id}.call``."""

    def __init__(self, nats_url: str = "nats://127.0.0.1:4222") -> None:
        self._nats_url = nats_url
        self._nc: nats.NATS | None = None

    async def connect(self) -> None:
        self._nc = await nats.connect(self._nats_url)

    async def close(self) -> None:
        if self._nc:
            await self._nc.close()
            self._nc = None

    async def call(
        self,
        request: ToolRequest,
        timeout: float = 30.0,
    ) -> ToolResponse:
        """Send a tool request and wait for the reply.

        Raises ``TimeoutError`` if no reply arrives within *timeout* seconds.
        """
        if self._nc is None:
            await self.connect()
        assert self._nc is not None

        subject = f"tools.{request.tool_id}.call"
        payload = request.model_dump_json().encode()

        t0 = time.monotonic()
        try:
            msg = await self._nc.request(subject, payload, timeout=timeout)
        except nats.errors.TimeoutError:
            elapsed = (time.monotonic() - t0) * 1000
            return ToolResponse(
                tool_id=request.tool_id,
                error=f"NATS request timed out after {timeout}s",
                duration_ms=elapsed,
            )

        elapsed = (time.monotonic() - t0) * 1000
        data = json.loads(msg.data)
        return ToolResponse(
            tool_id=request.tool_id,
            output=data.get("output", {}),
            error=data.get("error"),
            duration_ms=elapsed,
        )


# ---------------------------------------------------------------------------
# HTTP client (for Podman / sidecar mode)
# ---------------------------------------------------------------------------


class HTTPToolClient:
    """Invoke tools via HTTP POST for local / Podman-mode execution."""

    def __init__(self, base_url: str = "http://127.0.0.1:9100") -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(60.0))

    async def close(self) -> None:
        await self._client.aclose()

    async def call(
        self,
        request: ToolRequest,
        timeout: float = 30.0,
    ) -> ToolResponse:
        """POST a tool request to ``/tools/{tool_id}/call``."""
        url = f"{self._base_url}/tools/{request.tool_id}/call"
        payload = request.model_dump_json()

        t0 = time.monotonic()
        try:
            resp = await self._client.post(
                url,
                content=payload,
                headers={"Content-Type": "application/json"},
                timeout=timeout,
            )
            resp.raise_for_status()
        except httpx.TimeoutException:
            elapsed = (time.monotonic() - t0) * 1000
            return ToolResponse(
                tool_id=request.tool_id,
                error=f"HTTP request timed out after {timeout}s",
                duration_ms=elapsed,
            )
        except httpx.HTTPStatusError as exc:
            elapsed = (time.monotonic() - t0) * 1000
            return ToolResponse(
                tool_id=request.tool_id,
                error=f"HTTP {exc.response.status_code}: {exc.response.text}",
                duration_ms=elapsed,
            )

        elapsed = (time.monotonic() - t0) * 1000
        data = resp.json()
        return ToolResponse(
            tool_id=request.tool_id,
            output=data.get("output", {}),
            error=data.get("error"),
            duration_ms=elapsed,
        )
