"""FastAPI + Slack Socket Mode entrypoint for the Orchestack Slack connector."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from typing import Any

import nats
from fastapi import FastAPI
from nats.aio.client import Client as NATSClient

from orchestack_connector.message import NormalizedMessage
from orchestack_connector_slack.config import SlackConnectorSettings
from orchestack_connector_slack.connector import SlackConnector

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state (populated during lifespan)
# ---------------------------------------------------------------------------
_connector: SlackConnector | None = None
_nc: NATSClient | None = None

INGRESS_SUBJECT = "ingress.slack.message"
EGRESS_SUBJECT = "egress.slack.message"


# ---------------------------------------------------------------------------
# NATS helpers
# ---------------------------------------------------------------------------


async def _publish_to_nats(msg: NormalizedMessage) -> None:
    """Publish a normalised message to the NATS ingress subject."""
    if _nc is None or _nc.is_closed:
        logger.error("NATS connection unavailable; dropping message %s", msg.message_id)
        return
    payload = msg.model_dump_json().encode()
    await _nc.publish(INGRESS_SUBJECT, payload)
    logger.debug("Published message %s to %s", msg.message_id, INGRESS_SUBJECT)


async def _handle_egress(raw: Any) -> None:
    """Handle an egress message from NATS and send it via Slack."""
    if _connector is None:
        logger.error("Connector not initialised; ignoring egress message")
        return
    try:
        data = json.loads(raw.data.decode())
        channel: str = data["channel"]
        text: str = data["text"]
        thread_ts: str | None = data.get("thread_ts")
        await _connector.send(channel, text, thread_ts=thread_ts)
        logger.debug("Sent egress message to channel %s", channel)
    except Exception:
        logger.exception("Failed to handle egress message")


# ---------------------------------------------------------------------------
# FastAPI lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage NATS connection, egress subscription, and Socket Mode handler."""
    global _connector, _nc

    settings = SlackConnectorSettings()  # type: ignore[call-arg]

    # --- NATS connection ---
    logger.info("Connecting to NATS at %s", settings.nats_url)
    _nc = await nats.connect(settings.nats_url)

    # --- Connector ---
    _connector = SlackConnector(settings, publish_callback=_publish_to_nats)
    await _connector.connect()

    # --- Egress subscription ---
    sub = await _nc.subscribe(EGRESS_SUBJECT, cb=_handle_egress)
    logger.info("Subscribed to %s for egress messages", EGRESS_SUBJECT)

    # --- Socket Mode in background ---
    socket_task = asyncio.create_task(_start_socket_mode(_connector))

    try:
        yield
    finally:
        # --- Graceful shutdown ---
        logger.info("Shutting down Slack connector")
        socket_task.cancel()
        with suppress(asyncio.CancelledError):
            await socket_task

        await _connector.stop()

        await sub.unsubscribe()
        if _nc is not None and not _nc.is_closed:
            await _nc.drain()

        _connector = None
        _nc = None
        logger.info("Slack connector shutdown complete")


async def _start_socket_mode(connector: SlackConnector) -> None:
    """Run the Socket Mode handler until cancelled."""
    try:
        await connector.listen()
    except asyncio.CancelledError:
        logger.info("Socket Mode handler cancelled")


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Orchestack Slack Connector",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    """Readiness probe — checks NATS and connector are alive."""
    errors: list[str] = []

    if _nc is None or _nc.is_closed:
        errors.append("NATS connection is not available")

    if _connector is None or not _connector._running:
        errors.append("Slack connector is not running")

    if errors:
        return {"status": "not_ready", "errors": "; ".join(errors)}
    return {"status": "ready"}


# ---------------------------------------------------------------------------
# Standalone execution
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the connector as a standalone service."""
    import uvicorn

    settings = SlackConnectorSettings()  # type: ignore[call-arg]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    )
    uvicorn.run(
        "orchestack_connector_slack.main:app",
        host="0.0.0.0",
        port=settings.health_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
