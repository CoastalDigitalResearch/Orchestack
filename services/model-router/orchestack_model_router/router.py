"""Routing engine -- selects the best model for a given request."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

from orchestack_model_router.config import settings
from orchestack_model_router.models import (
    Locality,
    ModelRecord,
    ModelStatus,
    ProviderResponse,
    RoutingMetrics,
    RoutingRequest,
    RoutingResponse,
    SizeClass,
)
from orchestack_model_router.providers import get_provider

logger = logging.getLogger(__name__)

# Ordering used when sorting candidates inside the fallback chain.
_SIZE_ORDER: dict[SizeClass, int] = {
    SizeClass.SMALL: 0,
    SizeClass.MEDIUM: 1,
    SizeClass.LARGE: 2,
}

# Privacy tags that must never leave the local network.
_SENSITIVE_TAGS = frozenset({"sensitive", "restricted", "pii", "phi"})


# ---------------------------------------------------------------------------
# Circuit Breaker (per-provider)
# ---------------------------------------------------------------------------


@dataclass
class _CircuitState:
    """Per-provider circuit breaker state."""

    failure_count: int = 0
    last_failure_time: float = 0.0
    state: str = "closed"  # closed | open | half_open


class CircuitBreaker:
    """Simple circuit breaker keyed by ``(provider_type, endpoint)``."""

    def __init__(
        self,
        failure_threshold: int | None = None,
        recovery_timeout: float | None = None,
        half_open_max_calls: int | None = None,
    ) -> None:
        self._failure_threshold = failure_threshold or settings.circuit_breaker_failure_threshold
        self._recovery_timeout = recovery_timeout or settings.circuit_breaker_recovery_timeout
        self._half_open_max_calls = half_open_max_calls or settings.circuit_breaker_half_open_max_calls
        self._states: dict[str, _CircuitState] = {}
        self._lock = asyncio.Lock()

    def _key(self, model: ModelRecord) -> str:
        return f"{model.provider.value}::{model.endpoint}"

    async def is_available(self, model: ModelRecord) -> bool:
        """Return True if the circuit is closed or half-open (trial allowed)."""
        async with self._lock:
            cs = self._states.get(self._key(model))
            if cs is None:
                return True
            if cs.state == "closed":
                return True
            if cs.state == "open":
                if (time.monotonic() - cs.last_failure_time) >= self._recovery_timeout:
                    cs.state = "half_open"
                    return True
                return False
            # half_open -- allow a trial call
            return True

    async def record_success(self, model: ModelRecord) -> None:
        async with self._lock:
            key = self._key(model)
            cs = self._states.get(key)
            if cs is not None:
                cs.failure_count = 0
                cs.state = "closed"

    async def record_failure(self, model: ModelRecord) -> None:
        async with self._lock:
            key = self._key(model)
            cs = self._states.setdefault(key, _CircuitState())
            cs.failure_count += 1
            cs.last_failure_time = time.monotonic()
            if cs.failure_count >= self._failure_threshold:
                cs.state = "open"
                logger.warning(
                    "Circuit OPEN for %s (failures=%d)",
                    key,
                    cs.failure_count,
                )


# ---------------------------------------------------------------------------
# Model Registry (in-memory; will be backed by Postgres later)
# ---------------------------------------------------------------------------


class ModelRegistry:
    """Thread-safe in-memory registry of :class:`ModelRecord` instances."""

    def __init__(self) -> None:
        self._models: dict[str, ModelRecord] = {}
        self._lock = asyncio.Lock()

    async def register(self, model: ModelRecord) -> ModelRecord:
        async with self._lock:
            self._models[model.id] = model
        return model

    async def unregister(self, model_id: str) -> ModelRecord | None:
        async with self._lock:
            return self._models.pop(model_id, None)

    async def get(self, model_id: str) -> ModelRecord | None:
        return self._models.get(model_id)

    async def list_all(self) -> list[ModelRecord]:
        return list(self._models.values())

    async def list_active(self) -> list[ModelRecord]:
        return [m for m in self._models.values() if m.status == ModelStatus.ACTIVE]


# ---------------------------------------------------------------------------
# Routing Engine
# ---------------------------------------------------------------------------


class RoutingEngine:
    """Selects the best model for a :class:`RoutingRequest` and calls it.

    Selection order:
      1. **Privacy** -- never send sensitive data to a cloud provider.
      2. **Cost** -- prefer cheapest model that meets requirements.
      3. **Quality / capability** -- model must have required capabilities.
      4. **Context length** -- model must support the requested context.
      5. **Latency** -- prefer local models for low-latency requests.

    Fallback chain (default):
      smallest-local -> larger-local -> smallest-cloud -> larger-cloud
    """

    def __init__(
        self,
        registry: ModelRegistry,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        self.registry = registry
        self.circuit_breaker = circuit_breaker or CircuitBreaker()

    # -- candidate selection -------------------------------------------------

    async def _build_candidate_chain(
        self,
        request: RoutingRequest,
    ) -> list[ModelRecord]:
        """Return an ordered list of candidate models for *request*."""
        all_models = await self.registry.list_active()
        if not all_models:
            return []

        # If the caller asked for a specific model, try it first.
        preferred: ModelRecord | None = None
        if request.preferred_model_id:
            preferred = await self.registry.get(request.preferred_model_id)

        # ---- privacy filter ------------------------------------------------
        requires_local = bool(set(request.privacy_tags) & _SENSITIVE_TAGS)

        candidates: list[ModelRecord] = []
        for model in all_models:
            # Exclude cloud models when privacy demands local.
            if requires_local and model.locality == Locality.CLOUD:
                continue
            # Exclude models whose privacy class is less permissive than the
            # data's tags require. (A model marked "public" should not receive
            # "sensitive" data.)
            if requires_local and model.privacy_class.value not in (
                "sensitive",
                "restricted",
            ):
                continue
            # Capability gate.
            if request.task_complexity_hint == "complex" and model.size_class == SizeClass.SMALL:
                continue
            # Context length gate.
            if request.context_length_needed and model.context_length < request.context_length_needed:
                continue
            # Circuit breaker gate.
            if not await self.circuit_breaker.is_available(model):
                continue
            candidates.append(model)

        # ---- sort into fallback order --------------------------------------
        # Primary: locality (local first), secondary: size (small first),
        # tertiary: cost (cheapest first).
        def _sort_key(m: ModelRecord) -> tuple[int, int, float]:
            locality_order = 0 if m.locality == Locality.LOCAL else 1
            size_order = _SIZE_ORDER.get(m.size_class, 99)
            cost = m.cost_per_token.input + m.cost_per_token.output
            return (locality_order, size_order, cost)

        candidates.sort(key=_sort_key)

        # Latency hint: for LOW latency push smaller/local even more.
        # (The sort above already favours local-small, which is the right
        # default; no additional re-ordering needed.)

        # If caller requested a preferred model and it survived filtering,
        # move it to the front.
        if preferred and preferred in candidates:
            candidates.remove(preferred)
            candidates.insert(0, preferred)

        return candidates

    # -- execution -----------------------------------------------------------

    async def route(self, request: RoutingRequest) -> RoutingResponse:
        """Select a model, call the provider, return the response.

        Walks the fallback chain on provider errors.
        """
        candidates = await self._build_candidate_chain(request)
        if not candidates:
            raise NoModelsAvailableError("No models available that satisfy the request constraints.")

        errors: list[str] = []
        chain_tried: list[str] = []

        for model in candidates:
            chain_tried.append(model.id)
            provider = get_provider(
                model.provider,
                timeout=settings.provider_request_timeout,
                connect_timeout=settings.provider_connect_timeout,
            )

            t0 = time.monotonic()
            try:
                resp = await provider.chat_completion(
                    request.messages,
                    model,
                    stream=False,
                    **request.extra_params,
                )
            except Exception as exc:
                await self.circuit_breaker.record_failure(model)
                err_msg = f"Provider error for {model.id} ({model.model_name}): {exc}"
                logger.warning(err_msg)
                errors.append(err_msg)
                continue

            latency_ms = (time.monotonic() - t0) * 1000
            await self.circuit_breaker.record_success(model)

            cost = self._compute_cost(model, resp)

            return RoutingResponse(
                request_id=request.request_id,
                model_id=model.id,
                provider=model.provider,
                model_name=model.model_name,
                response=resp,
                cost=cost,
                latency_ms=latency_ms,
                fallback_chain_used=chain_tried,
            )

        # All candidates failed.
        raise AllProvidersFailedError(
            f"All providers failed. Attempted: {chain_tried}. Errors: {errors}",
            chain_tried=chain_tried,
        )

    async def route_stream(
        self,
        request: RoutingRequest,
    ) -> tuple[ModelRecord, AsyncIterator[str]]:
        """Select a model and return a streaming iterator.

        Returns a ``(model, stream)`` tuple so that the caller can track
        which model was chosen.
        """
        candidates = await self._build_candidate_chain(request)
        if not candidates:
            raise NoModelsAvailableError("No models available that satisfy the request constraints.")

        errors: list[str] = []
        for model in candidates:
            provider = get_provider(
                model.provider,
                timeout=settings.provider_request_timeout,
                connect_timeout=settings.provider_connect_timeout,
            )
            try:
                stream = provider.chat_completion_stream(
                    request.messages,
                    model,
                    **request.extra_params,
                )
                # We cannot fully verify the stream here without consuming it,
                # so we return it optimistically. The caller should handle
                # stream-level errors.
                return model, stream
            except Exception as exc:
                await self.circuit_breaker.record_failure(model)
                errors.append(f"{model.id}: {exc}")
                continue

        raise AllProvidersFailedError(
            f"All providers failed for streaming. Errors: {errors}",
            chain_tried=[m.id for m in candidates],
        )

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _compute_cost(model: ModelRecord, resp: ProviderResponse) -> float:
        """Compute the USD cost for a completion based on model pricing."""
        return (
            resp.usage.input_tokens * model.cost_per_token.input
            + resp.usage.output_tokens * model.cost_per_token.output
        )

    def build_metrics(
        self,
        request: RoutingRequest,
        model: ModelRecord,
        resp: ProviderResponse,
        cost: float,
        latency_ms: float,
    ) -> RoutingMetrics:
        return RoutingMetrics(
            request_id=request.request_id,
            tenant_id=request.tenant_id,
            model_id=model.id,
            model_name=model.model_name,
            provider=model.provider,
            locality=model.locality,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            cost=cost,
            latency_ms=latency_ms,
        )


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class NoModelsAvailableError(Exception):
    """Raised when no registered model satisfies the routing constraints."""


class AllProvidersFailedError(Exception):
    """Raised when every candidate in the fallback chain failed."""

    def __init__(self, message: str, *, chain_tried: list[str] | None = None) -> None:
        super().__init__(message)
        self.chain_tried = chain_tried or []
