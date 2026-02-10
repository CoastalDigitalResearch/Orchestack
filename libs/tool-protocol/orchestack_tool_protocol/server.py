"""Tool server helpers -- NATS subscription handler and FastAPI router."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

import nats
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from orchestack_tool_protocol.client import ToolRequest, ToolResponse
from orchestack_tool_protocol.descriptor import ToolDescriptor

# Type alias for a tool handler function.
# It receives a ToolRequest and must return a ToolResponse.
ToolHandler = Callable[[ToolRequest], Awaitable[ToolResponse]]


# ---------------------------------------------------------------------------
# NATS server
# ---------------------------------------------------------------------------


class NATSToolServer:
    """Register tool handlers on NATS subjects ``tools.{tool_id}.call``."""

    def __init__(self, nats_url: str = "nats://127.0.0.1:4222") -> None:
        self._nats_url = nats_url
        self._nc: nats.NATS | None = None
        self._handlers: dict[str, ToolHandler] = {}
        self._subs: list[Any] = []

    async def connect(self) -> None:
        self._nc = await nats.connect(self._nats_url)

    async def close(self) -> None:
        for sub in self._subs:
            await sub.unsubscribe()
        self._subs.clear()
        if self._nc:
            await self._nc.close()
            self._nc = None

    def register(self, descriptor: ToolDescriptor, handler: ToolHandler) -> None:
        """Register a handler for the given tool descriptor."""
        self._handlers[descriptor.tool_id] = handler

    async def start(self) -> None:
        """Subscribe to NATS subjects for all registered tools."""
        if self._nc is None:
            await self.connect()
        assert self._nc is not None

        for tool_id, handler in self._handlers.items():
            subject = f"tools.{tool_id}.call"

            async def _on_message(msg: Any, _handler: ToolHandler = handler, _tid: str = tool_id) -> None:
                t0 = time.monotonic()
                try:
                    req = ToolRequest.model_validate_json(msg.data)
                    resp = await _handler(req)
                    resp.duration_ms = (time.monotonic() - t0) * 1000
                except Exception as exc:
                    resp = ToolResponse(
                        tool_id=_tid,
                        error=str(exc),
                        duration_ms=(time.monotonic() - t0) * 1000,
                    )
                await msg.respond(resp.model_dump_json().encode())

            sub = await self._nc.subscribe(subject, cb=_on_message)
            self._subs.append(sub)


# ---------------------------------------------------------------------------
# HTTP / FastAPI server
# ---------------------------------------------------------------------------


class HTTPToolServer:
    """FastAPI router that exposes tool endpoints at ``/tools/{tool_id}/call``."""

    def __init__(self) -> None:
        self._handlers: dict[str, ToolHandler] = {}
        self._descriptors: dict[str, ToolDescriptor] = {}
        self.router = APIRouter(prefix="/tools", tags=["tools"])

        # Wire up the catch-all route
        self.router.add_api_route(
            "/{tool_id}/call",
            self._handle_call,
            methods=["POST"],
            response_model=ToolResponse,
        )
        self.router.add_api_route(
            "",
            self._handle_list,
            methods=["GET"],
        )

    def register(self, descriptor: ToolDescriptor, handler: ToolHandler) -> None:
        """Register a handler for the given tool descriptor."""
        self._handlers[descriptor.tool_id] = handler
        self._descriptors[descriptor.tool_id] = descriptor

    async def _handle_call(self, tool_id: str, request: Request) -> JSONResponse:
        """Handle POST /tools/{tool_id}/call."""
        handler = self._handlers.get(tool_id)
        if handler is None:
            return JSONResponse(
                status_code=404,
                content=ToolResponse(
                    tool_id=tool_id,
                    error=f"Tool '{tool_id}' not registered",
                ).model_dump(),
            )

        body = await request.json()
        req = ToolRequest(tool_id=tool_id, **body)

        t0 = time.monotonic()
        try:
            resp = await handler(req)
            resp.duration_ms = (time.monotonic() - t0) * 1000
        except Exception as exc:
            resp = ToolResponse(
                tool_id=tool_id,
                error=str(exc),
                duration_ms=(time.monotonic() - t0) * 1000,
            )

        return JSONResponse(content=resp.model_dump())

    async def _handle_list(self) -> JSONResponse:
        """Handle GET /tools -- return registered tool descriptors."""
        return JSONResponse(content=[d.model_dump() for d in self._descriptors.values()])
