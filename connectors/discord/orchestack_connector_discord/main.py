"""FastAPI + discord.py entrypoint for the Orchestack Discord connector."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import nats
import uvicorn
from fastapi import FastAPI
from nats.aio.client import Client as NATSClient

from orchestack_connector_discord.config import DiscordSettings
from orchestack_connector_discord.connector import DiscordConnector

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state shared between the lifespan and route handlers.
# ---------------------------------------------------------------------------
_connector: DiscordConnector | None = None
_nc: NATSClient | None = None
_settings: DiscordSettings | None = None


# ---------------------------------------------------------------------------
# NATS helpers
# ---------------------------------------------------------------------------


async def _nats_publish(subject: str, data: bytes) -> None:
    """Publish *data* on *subject* via the module-level NATS connection."""
    if _nc is None or _nc.is_closed:
        logger.error("NATS not connected -- dropping message on %s", subject)
        return
    await _nc.publish(subject, data)


async def _handle_egress(msg: Any) -> None:
    """Handle egress messages arriving from NATS on ``egress.discord.message``.

    Expected JSON payload::

        {
            "channel": "<channel_id>",
            "content": "text to send",
            "embed": { ... },          // optional
            "file_bytes": "<base64>",   // optional
            "file_name": "foo.png"      // optional
        }
    """
    if _connector is None:
        return

    try:
        payload = json.loads(msg.data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.error("Invalid JSON on egress.discord.message")
        return

    channel = payload.get("channel")
    content = payload.get("content", "")
    if not channel:
        logger.error("Egress message missing 'channel' field")
        return

    kwargs: dict[str, Any] = {}
    if "embed" in payload:
        kwargs["embed"] = payload["embed"]
    if "file_bytes" in payload:
        import base64

        kwargs["file_bytes"] = base64.b64decode(payload["file_bytes"])
        kwargs["file_name"] = payload.get("file_name", "attachment")

    await _connector.send(channel, content, **kwargs)


# ---------------------------------------------------------------------------
# FastAPI lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage startup and shutdown of NATS + Discord connections."""
    global _connector, _nc, _settings

    _settings = DiscordSettings()  # type: ignore[call-arg]

    # --- NATS ---
    logger.info("Connecting to NATS at %s ...", _settings.nats_url)
    _nc = await nats.connect(_settings.nats_url)

    # --- Discord connector ---
    _connector = DiscordConnector(
        settings=_settings,
        publish_callback=_nats_publish,
    )
    await _connector.connect()

    # Subscribe to egress subject so we can send outbound messages.
    await _nc.subscribe("egress.discord.message", cb=_handle_egress)
    logger.info("Subscribed to egress.discord.message")

    yield  # --- application is running ---

    # --- Shutdown ---
    logger.info("Shutting down...")
    if _connector is not None:
        await _connector.stop()
    if _nc is not None and not _nc.is_closed:
        await _nc.drain()


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(title="Orchestack Discord Connector", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe -- always returns OK if the process is up."""
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    """Readiness probe -- checks NATS and Discord connectivity."""
    issues: list[str] = []

    if _nc is None or _nc.is_closed:
        issues.append("nats_disconnected")

    if _connector is None:
        issues.append("connector_not_initialised")
    elif _connector._client.is_closed():
        issues.append("discord_disconnected")

    if issues:
        return {"status": "not_ready", "issues": ",".join(issues)}
    return {"status": "ready"}


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the connector service via uvicorn."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    uvicorn.run(
        "orchestack_connector_discord.main:app",
        host="0.0.0.0",
        port=8080,
        log_level="info",
    )


if __name__ == "__main__":
    main()
