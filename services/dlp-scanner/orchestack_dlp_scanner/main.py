"""DLP Scanner service entry point.

Exposes REST endpoints for on-demand scanning and redaction, and
optionally subscribes to NATS JetStream subjects for in-flight message
scanning.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from typing import Any

import nats
from fastapi import FastAPI
from nats.aio.client import Client as NATSClient

from .config import settings
from .models import RedactRequest, ScanRequest, ScanResult
from .scanner import DLPScanner

logger = logging.getLogger("orchestack.dlp_scanner")

# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

scanner = DLPScanner()

# Load custom patterns if configured.
if settings.custom_patterns_path:
    try:
        scanner.load_custom_patterns(settings.custom_patterns_path)
        logger.info("Loaded custom patterns from %s", settings.custom_patterns_path)
    except Exception:
        logger.exception("Failed to load custom patterns from %s", settings.custom_patterns_path)

_nats_client: NATSClient | None = None
_nats_task: asyncio.Task | None = None


# ---------------------------------------------------------------------------
# NATS subscriber
# ---------------------------------------------------------------------------


async def _nats_subscribe(nc: NATSClient) -> None:
    """Subscribe to ``ingress.>`` and scan every message that arrives."""
    try:
        js = nc.jetstream()

        # Create or bind to the DLP consumer on the ``ingress.>`` subject.
        # ``deliver_policy`` = "all" ensures we don't miss messages on a
        # fresh start; in production you would tune this.
        sub = await js.subscribe(
            "ingress.>",
            durable="dlp-scanner",
            ordered_consumer=False,
        )
        logger.info("Subscribed to ingress.> on NATS JetStream")

        async for msg in sub.messages:
            if not settings.scan_enabled:
                await msg.ack()
                continue

            try:
                content = msg.data.decode("utf-8", errors="replace")
                result = scanner.scan(content, content_type="message")

                if result.findings:
                    logger.info(
                        "DLP findings on %s: risk=%s tags=%s",
                        msg.subject,
                        result.risk_level,
                        result.tags,
                    )

                    # Publish the scan result to a companion subject so
                    # downstream consumers can react.
                    await nc.publish(
                        f"dlp.result.{msg.subject}",
                        result.model_dump_json().encode(),
                    )
            except Exception:
                logger.exception("Error scanning NATS message on %s", msg.subject)
            finally:
                await msg.ack()

    except asyncio.CancelledError:
        logger.info("NATS subscriber task cancelled")
    except Exception:
        logger.exception("NATS subscriber encountered an error")


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage NATS connection over the application lifespan."""
    global _nats_client, _nats_task

    # --- startup ---
    try:
        nc = await nats.connect(settings.nats_url)
        _nats_client = nc
        _nats_task = asyncio.create_task(_nats_subscribe(nc))
        logger.info("Connected to NATS at %s", settings.nats_url)
    except Exception:
        logger.warning(
            "Could not connect to NATS at %s -- running in HTTP-only mode",
            settings.nats_url,
        )
        _nats_client = None

    yield

    # --- shutdown ---
    if _nats_task is not None:
        _nats_task.cancel()
        with suppress(asyncio.CancelledError):
            await _nats_task

    if _nats_client is not None and _nats_client.is_connected:
        await _nats_client.drain()
        logger.info("NATS connection drained")


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Orchestack DLP Scanner",
    version="0.1.0",
    lifespan=lifespan,
)


# -- Health / readiness -------------------------------------------------------


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict[str, Any]:
    nats_ok = _nats_client is not None and _nats_client.is_connected
    return {
        "status": "ok" if nats_ok else "degraded",
        "nats_connected": nats_ok,
        "scan_enabled": settings.scan_enabled,
    }


# -- Scan endpoint ------------------------------------------------------------


@app.post("/v1/scan", response_model=ScanResult)
async def scan_content(req: ScanRequest) -> ScanResult:
    """Scan content for PII, secrets, and sensitive data patterns."""
    if not settings.scan_enabled:
        return ScanResult()

    result = scanner.scan(req.content, content_type=req.content_type)

    # Optionally attach redacted content based on global redact mode.
    if settings.redact_mode != "tag_only" and result.findings:
        result.redacted_content = scanner.redact(
            req.content,
            result.findings,
            mode=settings.redact_mode,
        )

    return result


# -- Redact endpoint ----------------------------------------------------------


@app.post("/v1/redact")
async def redact_content(req: RedactRequest) -> dict[str, str]:
    """Redact sensitive data from content given a list of findings."""
    redacted = scanner.redact(req.content, req.findings, mode=req.mode)
    return {"redacted_content": redacted}


# -- Patterns endpoint --------------------------------------------------------


@app.get("/v1/patterns")
async def list_patterns() -> list[dict]:
    """List all active scan patterns."""
    return scanner.list_patterns()
