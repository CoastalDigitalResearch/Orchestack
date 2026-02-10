"""FastAPI entrypoint for the Orchestack Telegram connector.

Provides health/readiness endpoints, wires NATS pub/sub, and runs the
Telegram bot (polling or webhook) in the background.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import nats
from fastapi import FastAPI
from nats.aio.client import Client as NATSClient

from orchestack_connector_telegram.config import TelegramSettings
from orchestack_connector_telegram.connector import TelegramConnector

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s - %(message)s",
)

# ---------------------------------------------------------------------------
# Module-level state (populated during lifespan)
# ---------------------------------------------------------------------------

_settings: TelegramSettings | None = None
_connector: TelegramConnector | None = None
_nats: NATSClient | None = None
_ready: bool = False


# ---------------------------------------------------------------------------
# NATS helpers
# ---------------------------------------------------------------------------


async def _nats_publish(subject: str, data: bytes) -> None:
    """Publish callback injected into the connector."""
    if _nats is not None and _nats.is_connected:
        await _nats.publish(subject, data)


async def _handle_egress(msg: Any) -> None:
    """Handle messages on ``egress.telegram.message`` from NATS.

    Expected payload (JSON)::

        {
            "chat_id": "123456789",
            "text": "Hello from Orchestack!",
            "parse_mode": "MarkdownV2",        // optional
            "reply_to_message_id": 42,          // optional
            "message_thread_id": 7,             // optional
            "reply_markup": { ... },            // optional inline keyboard
            "file_bytes_b64": "...",            // optional base64 file
            "file_name": "report.pdf",          // optional
            "content_type": "application/pdf"   // optional
        }
    """
    if _connector is None:
        logger.warning("Received egress message but connector is not ready.")
        return

    try:
        payload = json.loads(msg.data.decode())
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.error("Invalid egress payload: %s", msg.data[:200])
        return

    chat_id = payload.get("chat_id")
    text = payload.get("text", "")
    if not chat_id:
        logger.error("Egress message missing 'chat_id'.")
        return

    kwargs: dict[str, Any] = {}

    if "parse_mode" in payload:
        kwargs["parse_mode"] = payload["parse_mode"]
    if "reply_to_message_id" in payload:
        kwargs["reply_to_message_id"] = int(payload["reply_to_message_id"])
    if "message_thread_id" in payload:
        kwargs["message_thread_id"] = int(payload["message_thread_id"])
    if "reply_markup" in payload:
        kwargs["reply_markup"] = payload["reply_markup"]

    # File attachment (base64 encoded).
    if "file_bytes_b64" in payload:
        import base64

        kwargs["file_bytes"] = base64.b64decode(payload["file_bytes_b64"])
        kwargs["file_name"] = payload.get("file_name", "attachment")
        kwargs["content_type"] = payload.get("content_type", "application/octet-stream")

    await _connector.send(str(chat_id), text, **kwargs)


# ---------------------------------------------------------------------------
# FastAPI lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start NATS, the Telegram connector, and egress subscriber on boot;
    tear everything down on shutdown."""
    global _settings, _connector, _nats, _ready

    _settings = TelegramSettings()

    # 1. Connect to NATS.
    logger.info("Connecting to NATS at %s ...", _settings.nats_url)
    _nats = await nats.connect(_settings.nats_url)
    logger.info("NATS connected.")

    # 2. Build and start the Telegram connector.
    _connector = TelegramConnector(
        settings=_settings,
        publish_callback=_nats_publish,
    )
    await _connector.start()

    # 3. Subscribe to egress subject.
    await _nats.subscribe("egress.telegram.message", cb=_handle_egress)
    logger.info("Subscribed to egress.telegram.message on NATS.")

    _ready = True
    logger.info("Telegram connector is ready.")

    yield

    # --- shutdown ---
    _ready = False
    logger.info("Shutting down Telegram connector...")
    if _connector is not None:
        await _connector.stop()
    if _nats is not None and _nats.is_connected:
        await _nats.drain()
        await _nats.close()
    logger.info("Telegram connector shut down cleanly.")


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Orchestack Telegram Connector",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe -- returns 200 if the process is alive."""
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict[str, str | bool]:
    """Readiness probe -- returns 200 only when NATS and the Telegram
    bot are fully operational."""
    nats_ok = _nats is not None and _nats.is_connected
    bot_ok = _connector is not None and _connector._running
    if nats_ok and bot_ok and _ready:
        return {"status": "ready", "nats": nats_ok, "bot": bot_ok}
    return {"status": "not_ready", "nats": nats_ok, "bot": bot_ok}


# ---------------------------------------------------------------------------
# Direct invocation with uvicorn
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the connector with uvicorn when invoked directly."""
    import uvicorn

    uvicorn.run(
        "orchestack_connector_telegram.main:app",
        host="0.0.0.0",
        port=8080,
        log_level="info",
    )


if __name__ == "__main__":
    main()
