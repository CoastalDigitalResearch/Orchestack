"""FastAPI entrypoint for the Orchestack Email connector."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import nats
from fastapi import FastAPI
from nats.aio.client import Client as NATSClient

from orchestack_connector_email.config import EmailSettings
from orchestack_connector_email.connector import EmailConnector

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state (populated during lifespan)
# ---------------------------------------------------------------------------

_settings: EmailSettings | None = None
_connector: EmailConnector | None = None
_nc: NATSClient | None = None


def _get_settings() -> EmailSettings:
    global _settings
    if _settings is None:
        _settings = EmailSettings()  # type: ignore[call-arg]
    return _settings


# ---------------------------------------------------------------------------
# NATS helpers
# ---------------------------------------------------------------------------

INGRESS_SUBJECT = "ingress.email.message"
EGRESS_SUBJECT = "egress.email.message"


async def _publish_ingress(nc: NATSClient, msg_json: str) -> None:
    """Publish a normalized inbound email to the NATS ingress subject."""
    await nc.publish(INGRESS_SUBJECT, msg_json.encode())
    logger.debug("Published to %s", INGRESS_SUBJECT)


async def _handle_egress(raw_msg: Any) -> None:
    """Handle an outbound email message received from NATS."""
    if _connector is None:
        logger.error("Received egress message but connector is not initialized")
        return

    try:
        payload = json.loads(raw_msg.data.decode())
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.exception("Failed to decode egress message payload")
        return

    to_address: str = payload.get("channel", payload.get("to", ""))
    body: str = payload.get("content", payload.get("message", ""))
    subject: str = payload.get("subject", "")
    in_reply_to: str | None = payload.get("in_reply_to")
    references: str | None = payload.get("references")
    attachments: list[dict[str, Any]] = payload.get("attachments", [])

    if not to_address:
        logger.warning("Egress message missing recipient address, skipping")
        return

    await _connector.send(
        channel=to_address,
        message=body,
        subject=subject,
        in_reply_to=in_reply_to,
        references=references,
        attachments=attachments,
    )


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage startup and shutdown of the email connector."""
    global _connector, _nc

    settings = _get_settings()

    # --- NATS ---
    _nc = await nats.connect(settings.nats_url)
    logger.info("Connected to NATS at %s", settings.nats_url)

    # Subscribe to egress
    await _nc.subscribe(EGRESS_SUBJECT, cb=_handle_egress)
    logger.info("Subscribed to %s", EGRESS_SUBJECT)

    # --- Connector ---
    _connector = EmailConnector(settings)

    # Monkey-patch _on_message so it publishes to NATS
    async def _publish_on_message(normalized: Any) -> None:
        if _nc is not None:
            await _publish_ingress(_nc, normalized.model_dump_json())

    _connector._on_message = _publish_on_message  # type: ignore[assignment]

    await _connector.connect()
    await _connector.listen()
    logger.info("Email connector started")

    yield

    # --- Shutdown ---
    logger.info("Shutting down email connector")
    if _connector is not None:
        await _connector.stop()
    if _nc is not None:
        await _nc.drain()
        _nc = None


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Orchestack Email Connector", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    """Readiness probe - checks that IMAP and NATS are connected."""
    issues: list[str] = []

    if _connector is None or _connector._imap is None:
        issues.append("imap_not_connected")
    if _nc is None or _nc.is_closed:
        issues.append("nats_not_connected")

    if issues:
        return {"status": "not_ready", "issues": ",".join(issues)}
    return {"status": "ready"}


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the connector with uvicorn."""
    import uvicorn

    _get_settings()
    uvicorn.run(
        "orchestack_connector_email.main:app",
        host="0.0.0.0",
        port=8080,
        log_level="info",
    )


if __name__ == "__main__":
    main()
