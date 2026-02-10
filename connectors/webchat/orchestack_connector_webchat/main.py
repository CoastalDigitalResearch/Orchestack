"""FastAPI application for the Orchestack Webchat connector.

Provides REST endpoints, a WebSocket endpoint, CORS middleware, health
checks, and NATS integration for ingress/egress message routing.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import Any

import httpx
import nats
from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from nats.aio.client import Client as NATSClient
from pydantic import BaseModel

from orchestack_connector_webchat.config import WebchatSettings
from orchestack_connector_webchat.connector import WebchatConnector
from orchestack_connector_webchat.dashboard import DASHBOARD_HTML
from orchestack_connector_webchat.widget import WIDGET_HTML

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global state (populated during lifespan)
# ---------------------------------------------------------------------------
settings = WebchatSettings()
connector: WebchatConnector | None = None
nc: NATSClient | None = None


# ---------------------------------------------------------------------------
# NATS publish helper
# ---------------------------------------------------------------------------


async def _nats_publish(subject: str, data: bytes) -> None:
    """Publish *data* to the given NATS *subject*."""
    if nc is not None and nc.is_connected:
        await nc.publish(subject, data)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    """Application lifespan: start NATS + connector, subscribe to egress."""
    global connector, nc

    # --- Start NATS ---
    try:
        nc = await nats.connect(settings.nats_url)
        logger.info("Connected to NATS at %s", settings.nats_url)
    except Exception:
        logger.warning(
            "Could not connect to NATS at %s; running without message bus.",
            settings.nats_url,
        )
        nc = None

    # --- Start connector ---
    connector = WebchatConnector(settings=settings, publish_callback=_nats_publish)
    await connector.connect()

    # --- Subscribe to egress ---
    if nc is not None:
        await nc.subscribe("egress.webchat.message", cb=_handle_egress)
        await nc.subscribe("egress.message", cb=_handle_egress)
        logger.info("Subscribed to egress.webchat.message and egress.message")

    yield

    # --- Shutdown ---
    if connector is not None:
        await connector.stop()
    if nc is not None and nc.is_connected:
        await nc.drain()
        logger.info("NATS connection drained")


async def _handle_egress(msg: Any) -> None:
    """Forward an egress NATS message to the matching WebSocket session."""
    if connector is None:
        return
    try:
        payload = json.loads(msg.data)
        session_id: str = payload.get("session_id", payload.get("thread_id", ""))
        if not session_id:
            logger.warning("Egress message missing session_id/thread_id")
            return
        await connector.send(session_id, msg.data.decode())
    except Exception:
        logger.exception("Error handling egress message")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Orchestack Webchat Connector",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Optional OIDC authentication
# ---------------------------------------------------------------------------


async def _verify_oidc_token(
    authorization: str | None = Header(default=None),
) -> str | None:
    """Validate the bearer token if OIDC is configured."""
    if settings.oidc_issuer is None:
        return None
    if authorization is None or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.split(" ", 1)[1]
    if not token:
        raise HTTPException(status_code=401, detail="Empty bearer token")
    return token


# ---------------------------------------------------------------------------
# Health endpoints
# ---------------------------------------------------------------------------


@app.get("/healthz")
async def healthz() -> JSONResponse:
    """Liveness probe."""
    return JSONResponse({"status": "ok"})


@app.get("/readyz")
async def readyz() -> JSONResponse:
    """Readiness probe -- checks NATS connectivity."""
    nats_ready = nc is not None and nc.is_connected
    if not nats_ready:
        return JSONResponse({"status": "not_ready", "nats": False}, status_code=503)
    return JSONResponse({"status": "ready", "nats": True})


# ---------------------------------------------------------------------------
# Widget & Dashboard endpoints
# ---------------------------------------------------------------------------


@app.get("/widget", response_class=HTMLResponse)
async def widget() -> HTMLResponse:
    """Serve the embeddable webchat widget."""
    return HTMLResponse(content=WIDGET_HTML)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    """Serve the multi-agent dashboard."""
    return HTMLResponse(content=DASHBOARD_HTML)


# ---------------------------------------------------------------------------
# System status proxy endpoint
# ---------------------------------------------------------------------------

SERVICE_HEALTH_URLS = {
    "session-scheduler": "http://session-scheduler:8080/healthz",
    "task-dispatcher": "http://task-dispatcher:8080/healthz",
    "policy-evaluator": "http://policy-evaluator:8080/healthz",
    "loop-runner": "http://loop-runner:8080/healthz",
    "model-router": "http://model-router:8080/healthz",
    "budget-accounting": "http://budget-accounting:8080/healthz",
    "memory-plane": "http://memory-plane:8080/healthz",
    "dlp-scanner": "http://dlp-scanner:8080/healthz",
    "nats": "http://nats:8222/healthz",
}


@app.get("/v1/system/status")
async def system_status() -> JSONResponse:
    """Poll healthz of all internal services and return status map."""
    results: dict[str, bool] = {}
    async with httpx.AsyncClient(timeout=3.0) as client:
        for name, url in SERVICE_HEALTH_URLS.items():
            try:
                resp = await client.get(url)
                results[name] = resp.status_code == 200
            except Exception:
                results[name] = False
    return JSONResponse(results)


# ---------------------------------------------------------------------------
# Agents endpoint
# ---------------------------------------------------------------------------


@app.get("/v1/agents")
async def list_agents() -> JSONResponse:
    """Return the list of configured agents from the database."""
    # In production this would query the agents table via asyncpg.
    # For now, return the seeded agents list for the dashboard.
    agents = [
        {"id": "00000000-0000-0000-0000-00000000a001", "name": "Homarus", "status": "active", "role": "Chief of Staff"},
        {"id": "00000000-0000-0000-0000-00000000a002", "name": "Ken", "status": "active", "role": "Software Architect"},
        {"id": "00000000-0000-0000-0000-00000000a003", "name": "Mercer", "status": "active", "role": "Financial Operator"},
        {"id": "00000000-0000-0000-0000-00000000a004", "name": "Rory", "status": "active", "role": "Revenue Growth"},
        {"id": "00000000-0000-0000-0000-00000000a005", "name": "Scarlet", "status": "active", "role": "Red Hat Operations"},
        {"id": "00000000-0000-0000-0000-00000000a006", "name": "Ive", "status": "active", "role": "UI/UX Architect"},
        {"id": "00000000-0000-0000-0000-00000000a007", "name": "Mark", "status": "active", "role": "Creative Director"},
    ]
    return JSONResponse(agents)


# ---------------------------------------------------------------------------
# REST session management
# ---------------------------------------------------------------------------


class CreateSessionRequest(BaseModel):
    """Request body for creating a new chat session."""

    display_name: str = "Anonymous"
    agent_id: str | None = None


class CreateSessionResponse(BaseModel):
    """Response body after session creation."""

    session_id: str
    created: bool


class SessionStatusResponse(BaseModel):
    """Response body for session status queries."""

    session_id: str
    active: bool
    has_websocket: bool


class SendMessageRequest(BaseModel):
    """Request body for sending a chat message via REST."""

    content: str
    attachments: list[dict[str, Any]] = []
    reply_to: str | None = None
    extra: dict[str, Any] = {}


class SendMessageResponse(BaseModel):
    """Response body after a message send attempt."""

    message_id: str | None
    accepted: bool
    reason: str | None = None


@app.post("/v1/chat/sessions", response_model=CreateSessionResponse)
async def create_session(
    body: CreateSessionRequest,
    sub: str | None = Depends(_verify_oidc_token),
) -> CreateSessionResponse:
    """Create a new chat session (REST alternative to WebSocket auto-create)."""
    assert connector is not None
    session = connector.create_session(
        display_name=body.display_name,
        authenticated_sub=sub,
        agent_id=body.agent_id,
    )
    return CreateSessionResponse(session_id=session.session_id, created=True)


@app.get("/v1/chat/sessions/{session_id}", response_model=SessionStatusResponse)
async def get_session(session_id: str) -> SessionStatusResponse:
    """Return the status of an existing session."""
    assert connector is not None
    session = connector.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionStatusResponse(
        session_id=session.session_id,
        active=not session.is_expired(settings.session_timeout_s),
        has_websocket=session.websocket is not None,
    )


@app.post(
    "/v1/chat/sessions/{session_id}/messages",
    response_model=SendMessageResponse,
)
async def send_message_rest(
    session_id: str,
    body: SendMessageRequest,
) -> SendMessageResponse:
    """Send a message via REST (alternative to sending over WebSocket)."""
    assert connector is not None
    session = connector.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    data: dict[str, Any] = {
        "content": body.content,
        "attachments": body.attachments,
        "reply_to": body.reply_to,
        "extra": body.extra,
    }
    normalized = await connector.handle_incoming(session_id, data)
    if normalized is None:
        return SendMessageResponse(
            message_id=None,
            accepted=False,
            reason="Message rejected (rate limit or validation failure)",
        )
    return SendMessageResponse(message_id=normalized.message_id, accepted=True)


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


@app.websocket("/ws/{session_id}")
async def websocket_with_session(websocket: WebSocket, session_id: str) -> None:
    """WebSocket endpoint with a pre-created session ID."""
    assert connector is not None
    await websocket.accept()

    # Attach to existing session or create a new one with the given ID.
    if not connector.attach_websocket(session_id, websocket):
        session = connector.create_session(websocket=websocket)
        # Override the auto-generated ID so the client's ID is honoured.
        connector.sessions.pop(session.session_id, None)
        session.session_id = session_id
        connector.sessions[session_id] = session

    try:
        await _ws_loop(websocket, session_id)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: session %s", session_id)
    finally:
        session_obj = connector.get_session(session_id)
        if session_obj is not None:
            session_obj.websocket = None


@app.websocket("/ws")
async def websocket_auto_session(websocket: WebSocket) -> None:
    """WebSocket endpoint that auto-generates a session on connect."""
    assert connector is not None
    await websocket.accept()

    session = connector.create_session(websocket=websocket)
    session_id = session.session_id

    # Tell the client its session ID so it can persist it.
    await websocket.send_text(json.dumps({"type": "session", "session_id": session_id}))

    try:
        await _ws_loop(websocket, session_id)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: session %s", session_id)
    finally:
        session_obj = connector.get_session(session_id)
        if session_obj is not None:
            session_obj.websocket = None


async def _ws_loop(websocket: WebSocket, session_id: str) -> None:
    """Read messages from a WebSocket and process them."""
    assert connector is not None
    while True:
        raw = await websocket.receive_text()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            await websocket.send_text(json.dumps({"type": "error", "detail": "Invalid JSON"}))
            continue

        msg_type = data.get("type", "message")

        if msg_type == "ping":
            await websocket.send_text(json.dumps({"type": "pong"}))
            continue

        normalized = await connector.handle_incoming(session_id, data)
        if normalized is None:
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "error",
                        "detail": "Message rejected (rate limit or validation)",
                    }
                )
            )
        else:
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "ack",
                        "message_id": normalized.message_id,
                    }
                )
            )
