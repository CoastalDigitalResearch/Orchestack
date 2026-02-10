"""Model Router service entry point.

Exposes a FastAPI application that:
  - Registers / lists / removes model providers.
  - Accepts synchronous routing requests via HTTP (fallback path).
  - Consumes ``router.request`` from NATS JetStream and publishes
    ``router.completed`` or ``router.failed``.
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

import nats
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import StreamingResponse
from nats.aio.client import Client as NATSClient
from nats.aio.msg import Msg

from orchestack_model_router.config import settings
from orchestack_model_router.models import (
    CostPerToken,
    Locality,
    ModelRecord,
    ModelStatus,
    PrivacyClass,
    ProviderType,
    RoutingError,
    RoutingRequest,
    RoutingResponse,
    SizeClass,
)
from orchestack_model_router.router import (
    AllProvidersFailedError,
    CircuitBreaker,
    ModelRegistry,
    NoModelsAvailableError,
    RoutingEngine,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

registry = ModelRegistry()
circuit_breaker = CircuitBreaker()
engine = RoutingEngine(registry, circuit_breaker)

# Will be set during lifespan startup.
_nc: NATSClient | None = None
_nats_sub: Any = None  # NATS subscription handle


# ---------------------------------------------------------------------------
# NATS helpers
# ---------------------------------------------------------------------------


async def _publish(subject: str, payload: dict[str, Any]) -> None:
    """Publish a JSON payload to a NATS subject (best-effort)."""
    if _nc is None or not _nc.is_connected:
        logger.warning("NATS not connected; dropping publish to %s", subject)
        return
    data = json.dumps(payload, default=str).encode()
    await _nc.publish(subject, data)


async def _handle_nats_request(msg: Msg) -> None:
    """Handle an inbound ``router.request`` message from NATS."""
    try:
        raw = json.loads(msg.data.decode())
        request = RoutingRequest.model_validate(raw)
    except Exception:
        logger.exception("Failed to parse router.request message")
        if msg.reply:
            await _nc.publish(msg.reply, b'{"error":"invalid request"}')  # type: ignore[union-attr]
        return

    try:
        result = await engine.route(request)

        # Publish completed event.
        await _publish(
            settings.nats_completed_subject,
            result.model_dump(),
        )

        # Publish metrics sidecar event.
        metrics = engine.build_metrics(
            request,
            await registry.get(result.model_id),  # type: ignore[arg-type]
            result.response,
            result.cost,
            result.latency_ms,
        )
        await _publish(settings.nats_metrics_subject, metrics.model_dump())

        # If the original message used request/reply, respond inline.
        if msg.reply:
            await _nc.publish(  # type: ignore[union-attr]
                msg.reply,
                json.dumps(result.model_dump(), default=str).encode(),
            )

    except (NoModelsAvailableError, AllProvidersFailedError) as exc:
        chain = getattr(exc, "chain_tried", [])
        error_payload = RoutingError(
            request_id=request.request_id,
            error=str(exc),
            fallback_chain_attempted=chain,
        )
        await _publish(settings.nats_failed_subject, error_payload.model_dump())
        if msg.reply:
            await _nc.publish(  # type: ignore[union-attr]
                msg.reply,
                json.dumps(error_payload.model_dump(), default=str).encode(),
            )

    except Exception:
        logger.exception("Unhandled error processing router.request")
        error_payload = RoutingError(
            request_id=request.request_id,
            error="internal error",
        )
        await _publish(settings.nats_failed_subject, error_payload.model_dump())
        if msg.reply:
            await _nc.publish(  # type: ignore[union-attr]
                msg.reply,
                json.dumps(error_payload.model_dump(), default=str).encode(),
            )


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


async def _auto_register_models() -> None:
    """Register models from environment variables at startup."""
    # OpenCode Zen (Kimi K2.5) as primary
    zen_key = os.environ.get("OPENCODE_ZEN_API_KEY", "")
    zen_base = os.environ.get("OPENCODE_ZEN_BASE_URL", "https://opencode.ai/zen/v1")
    if zen_key:
        model = ModelRecord(
            id="opencode-zen-k25",
            provider=ProviderType.OPENAI_COMPATIBLE,
            model_name="kimi-k2.5",
            endpoint=zen_base,
            api_key_ref="env:OPENCODE_ZEN_API_KEY",
            context_length=262144,
            cost_per_token=CostPerToken(input=0.000001, output=0.000002),
            locality=Locality.CLOUD,
            size_class=SizeClass.LARGE,
            capabilities=["chat", "code", "reasoning"],
            privacy_class=PrivacyClass.INTERNAL,
        )
        await registry.register(model)
        logger.info("Auto-registered OpenCode Zen (Kimi K2.5)")

    # Anthropic Claude Sonnet 4.5 as fallback
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if anthropic_key:
        model = ModelRecord(
            id="anthropic-sonnet-45",
            provider=ProviderType.ANTHROPIC,
            model_name="claude-sonnet-4-5-20250929",
            endpoint="https://api.anthropic.com",
            api_key_ref="env:ANTHROPIC_API_KEY",
            context_length=200000,
            cost_per_token=CostPerToken(input=0.000003, output=0.000015),
            locality=Locality.CLOUD,
            size_class=SizeClass.LARGE,
            capabilities=["chat", "code", "reasoning", "vision"],
            privacy_class=PrivacyClass.INTERNAL,
        )
        await registry.register(model)
        logger.info("Auto-registered Anthropic Claude Sonnet 4.5")

    # OpenAI GPT-5.2 Codex as fallback
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if openai_key:
        model = ModelRecord(
            id="openai-gpt52-codex",
            provider=ProviderType.OPENAI_COMPATIBLE,
            model_name="gpt-5.2-codex",
            endpoint="https://api.openai.com/v1",
            api_key_ref="env:OPENAI_API_KEY",
            context_length=128000,
            cost_per_token=CostPerToken(input=0.000003, output=0.000012),
            locality=Locality.CLOUD,
            size_class=SizeClass.LARGE,
            capabilities=["chat", "code", "reasoning"],
            privacy_class=PrivacyClass.INTERNAL,
        )
        await registry.register(model)
        logger.info("Auto-registered OpenAI GPT-5.2 Codex")

    registered = await registry.list_active()
    logger.info("Total registered models: %d", len(registered))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Connect to NATS on startup and clean up on shutdown."""
    global _nc, _nats_sub

    # -- startup ---
    try:
        _nc = await nats.connect(settings.nats_url)
        _nats_sub = await _nc.subscribe(
            settings.nats_request_subject,
            queue=settings.nats_queue_group,
            cb=_handle_nats_request,
        )
        logger.info(
            "Connected to NATS at %s, subscribed to %s (queue=%s)",
            settings.nats_url,
            settings.nats_request_subject,
            settings.nats_queue_group,
        )
    except Exception:
        logger.warning(
            "Could not connect to NATS at %s -- running in HTTP-only mode",
            settings.nats_url,
        )
        _nc = None

    # Auto-register models from env
    await _auto_register_models()

    yield

    # -- shutdown ---
    if _nats_sub is not None:
        await _nats_sub.unsubscribe()
    if _nc is not None and _nc.is_connected:
        await _nc.drain()
        logger.info("NATS connection drained")


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Orchestack Model Router",
    version="0.1.0",
    lifespan=lifespan,
)


# -- Health ---------------------------------------------------------------


@app.get("/healthz")
async def healthz():
    """Liveness probe."""
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    """Readiness probe -- reports NATS connectivity."""
    nats_ok = _nc is not None and _nc.is_connected
    model_count = len(await registry.list_active())
    status = "ok" if nats_ok else "degraded"
    return {
        "status": status,
        "nats_connected": nats_ok,
        "registered_models": model_count,
    }


# -- Model CRUD -----------------------------------------------------------


@app.post("/v1/models/register", response_model=ModelRecord, status_code=201)
async def register_model(record: ModelRecord):
    """Register a new model for routing."""
    existing = await registry.get(record.id)
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"Model {record.id} already registered")
    model = await registry.register(record)
    logger.info("Registered model %s (%s via %s)", model.id, model.model_name, model.provider.value)
    return model


@app.get("/v1/models", response_model=list[ModelRecord])
async def list_models(status: ModelStatus | None = None):
    """List all registered models, optionally filtered by status."""
    models = await registry.list_all()
    if status is not None:
        models = [m for m in models if m.status == status]
    return models


@app.get("/v1/models/{model_id}", response_model=ModelRecord)
async def get_model(model_id: str):
    """Retrieve a single model by ID."""
    model = await registry.get(model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")
    return model


@app.delete("/v1/models/{model_id}", status_code=204)
async def delete_model(model_id: str):
    """Remove a model from the registry."""
    removed = await registry.unregister(model_id)
    if removed is None:
        raise HTTPException(status_code=404, detail="Model not found")
    logger.info("Unregistered model %s", model_id)
    return Response(status_code=204)


# -- Synchronous routing (HTTP fallback) -----------------------------------


@app.post("/v1/router/request", response_model=RoutingResponse)
async def route_request(request: RoutingRequest):
    """Synchronous routing endpoint -- HTTP fallback when NATS is unavailable."""
    try:
        result = await engine.route(request)
    except NoModelsAvailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AllProvidersFailedError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": str(exc),
                "fallback_chain_attempted": exc.chain_tried,
            },
        ) from exc

    # Publish metrics if NATS is available.
    model = await registry.get(result.model_id)
    if model is not None:
        metrics = engine.build_metrics(
            request,
            model,
            result.response,
            result.cost,
            result.latency_ms,
        )
        await _publish(settings.nats_metrics_subject, metrics.model_dump())

    return result


@app.post("/v1/router/request/stream")
async def route_request_stream(request: RoutingRequest):
    """Streaming routing endpoint -- returns SSE chunks."""
    try:
        model, stream = await engine.route_stream(request)
    except NoModelsAvailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AllProvidersFailedError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": str(exc),
                "fallback_chain_attempted": exc.chain_tried,
            },
        ) from exc

    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Orchestack-Model-Id": model.id,
            "X-Orchestack-Model-Name": model.model_name,
        },
    )
