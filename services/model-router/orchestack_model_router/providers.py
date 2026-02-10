"""Provider abstraction layer for LLM backends."""

from __future__ import annotations

import abc
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from orchestack_model_router.models import (
    ChatMessage,
    ModelRecord,
    ProviderResponse,
    ProviderType,
    TokenUsage,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class BaseProvider(abc.ABC):
    """Protocol every LLM provider must implement."""

    @abc.abstractmethod
    async def chat_completion(
        self,
        messages: list[ChatMessage],
        model: ModelRecord,
        *,
        stream: bool = False,
        **kwargs: Any,
    ) -> ProviderResponse:
        """Send a chat completion request and return the full response."""

    @abc.abstractmethod
    async def chat_completion_stream(
        self,
        messages: list[ChatMessage],
        model: ModelRecord,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Yield SSE-formatted chunks for streaming responses."""

    @abc.abstractmethod
    async def health_check(self, model: ModelRecord) -> bool:
        """Return True if the provider endpoint is reachable and healthy."""


# ---------------------------------------------------------------------------
# OpenAI-compatible provider (OpenAI, vLLM, llama.cpp, etc.)
# ---------------------------------------------------------------------------


class OpenAICompatibleProvider(BaseProvider):
    """Handles any provider exposing the ``/v1/chat/completions`` interface."""

    def __init__(
        self,
        *,
        timeout: float = 120.0,
        connect_timeout: float = 10.0,
    ) -> None:
        self._timeout = timeout
        self._connect_timeout = connect_timeout

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _build_url(endpoint: str, path: str) -> str:
        base = endpoint.rstrip("/")
        return f"{base}{path}"

    @staticmethod
    def _headers(model: ModelRecord) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if model.api_key_ref:
            # In production the key would be resolved via Vault; here we
            # accept a raw key or env-var reference as a convenience.
            headers["Authorization"] = f"Bearer {model.api_key_ref}"
        return headers

    @staticmethod
    def _build_body(
        messages: list[ChatMessage],
        model: ModelRecord,
        *,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model.model_name,
            "messages": [m.model_dump(exclude_none=True) for m in messages],
            "stream": stream,
        }
        # Forward caller-supplied parameters (temperature, max_tokens, etc.)
        for key in ("temperature", "max_tokens", "top_p", "stop", "tools", "tool_choice"):
            if key in kwargs:
                body[key] = kwargs[key]
        return body

    # -- public API ----------------------------------------------------------

    async def chat_completion(
        self,
        messages: list[ChatMessage],
        model: ModelRecord,
        *,
        stream: bool = False,
        **kwargs: Any,
    ) -> ProviderResponse:
        url = self._build_url(model.endpoint, "/v1/chat/completions")
        body = self._build_body(messages, model, stream=False, **kwargs)
        headers = self._headers(model)

        timeout = httpx.Timeout(self._timeout, connect=self._connect_timeout)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0] if data.get("choices") else {}
        message = choice.get("message", {})
        usage_raw = data.get("usage", {})

        return ProviderResponse(
            content=message.get("content"),
            usage=TokenUsage(
                input_tokens=usage_raw.get("prompt_tokens", 0),
                output_tokens=usage_raw.get("completion_tokens", 0),
            ),
            model=data.get("model", model.model_name),
            finish_reason=choice.get("finish_reason"),
            tool_calls=message.get("tool_calls"),
        )

    async def chat_completion_stream(
        self,
        messages: list[ChatMessage],
        model: ModelRecord,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        url = self._build_url(model.endpoint, "/v1/chat/completions")
        body = self._build_body(messages, model, stream=True, **kwargs)
        headers = self._headers(model)

        timeout = httpx.Timeout(self._timeout, connect=self._connect_timeout)
        async with (
            httpx.AsyncClient(timeout=timeout) as client,
            client.stream("POST", url, json=body, headers=headers) as resp,
        ):
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                payload = line[len("data: ") :]
                if payload.strip() == "[DONE]":
                    yield "data: [DONE]\n\n"
                    break
                yield f"data: {payload}\n\n"

    async def health_check(self, model: ModelRecord) -> bool:
        """Probe ``/v1/models`` or ``/health`` to verify liveness."""
        timeout = httpx.Timeout(5.0, connect=3.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            for path in ("/v1/models", "/health", "/healthz"):
                try:
                    resp = await client.get(
                        self._build_url(model.endpoint, path),
                        headers=self._headers(model),
                    )
                    if resp.status_code < 500:
                        return True
                except httpx.HTTPError:
                    continue
        return False


# ---------------------------------------------------------------------------
# Anthropic provider
# ---------------------------------------------------------------------------


class AnthropicProvider(BaseProvider):
    """Handles the Anthropic Messages API."""

    ANTHROPIC_API_URL = "https://api.anthropic.com"
    ANTHROPIC_VERSION = "2023-06-01"

    def __init__(
        self,
        *,
        timeout: float = 120.0,
        connect_timeout: float = 10.0,
    ) -> None:
        self._timeout = timeout
        self._connect_timeout = connect_timeout

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _build_url(endpoint: str, path: str) -> str:
        base = endpoint.rstrip("/")
        return f"{base}{path}"

    @staticmethod
    def _headers(model: ModelRecord) -> dict[str, str]:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "anthropic-version": AnthropicProvider.ANTHROPIC_VERSION,
        }
        if model.api_key_ref:
            headers["x-api-key"] = model.api_key_ref
        return headers

    @staticmethod
    def _convert_messages(messages: list[ChatMessage]) -> tuple[str | None, list[dict[str, Any]]]:
        """Split system message from the rest (Anthropic format)."""
        system_prompt: str | None = None
        converted: list[dict[str, Any]] = []
        for msg in messages:
            if msg.role == "system":
                system_prompt = msg.content
            else:
                entry: dict[str, Any] = {"role": msg.role, "content": msg.content or ""}
                converted.append(entry)
        return system_prompt, converted

    @staticmethod
    def _build_body(
        messages: list[ChatMessage],
        model: ModelRecord,
        *,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        system_prompt, converted = AnthropicProvider._convert_messages(messages)
        body: dict[str, Any] = {
            "model": model.model_name,
            "messages": converted,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "stream": stream,
        }
        if system_prompt:
            body["system"] = system_prompt
        for key in ("temperature", "top_p", "stop_sequences", "tools", "tool_choice"):
            if key in kwargs:
                body[key] = kwargs[key]
        return body

    # -- public API ----------------------------------------------------------

    async def chat_completion(
        self,
        messages: list[ChatMessage],
        model: ModelRecord,
        *,
        stream: bool = False,
        **kwargs: Any,
    ) -> ProviderResponse:
        endpoint = model.endpoint or self.ANTHROPIC_API_URL
        url = self._build_url(endpoint, "/v1/messages")
        body = self._build_body(messages, model, stream=False, **kwargs)
        headers = self._headers(model)

        timeout = httpx.Timeout(self._timeout, connect=self._connect_timeout)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        # Anthropic returns content as a list of blocks.
        content_blocks = data.get("content", [])
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        for block in content_blocks:
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_calls.append(block)

        usage_raw = data.get("usage", {})
        return ProviderResponse(
            content="\n".join(text_parts) if text_parts else None,
            usage=TokenUsage(
                input_tokens=usage_raw.get("input_tokens", 0),
                output_tokens=usage_raw.get("output_tokens", 0),
            ),
            model=data.get("model", model.model_name),
            finish_reason=data.get("stop_reason"),
            tool_calls=tool_calls or None,
        )

    async def chat_completion_stream(
        self,
        messages: list[ChatMessage],
        model: ModelRecord,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        endpoint = model.endpoint or self.ANTHROPIC_API_URL
        url = self._build_url(endpoint, "/v1/messages")
        body = self._build_body(messages, model, stream=True, **kwargs)
        headers = self._headers(model)

        timeout = httpx.Timeout(self._timeout, connect=self._connect_timeout)
        async with (
            httpx.AsyncClient(timeout=timeout) as client,
            client.stream("POST", url, json=body, headers=headers) as resp,
        ):
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                # Anthropic SSE: "event: <type>\ndata: <json>\n\n"
                if line.startswith("data: "):
                    payload = line[len("data: ") :]
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue

                    event_type = chunk.get("type", "")

                    if event_type == "content_block_delta":
                        delta = chunk.get("delta", {})
                        if delta.get("type") == "text_delta":
                            # Re-emit as a simplified SSE chunk that callers can consume.
                            sse_data = json.dumps({"choices": [{"delta": {"content": delta.get("text", "")}}]})
                            yield f"data: {sse_data}\n\n"

                    elif event_type == "message_stop":
                        yield "data: [DONE]\n\n"
                        break

    async def health_check(self, model: ModelRecord) -> bool:
        """Anthropic has no public health endpoint; a lightweight models call suffices."""
        endpoint = model.endpoint or self.ANTHROPIC_API_URL
        timeout = httpx.Timeout(5.0, connect=3.0)
        headers = self._headers(model)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(
                    self._build_url(endpoint, "/v1/models"),
                    headers=headers,
                )
                return resp.status_code < 500
        except httpx.HTTPError:
            return False


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

_PROVIDER_MAP: dict[ProviderType, type[BaseProvider]] = {
    ProviderType.OPENAI_COMPATIBLE: OpenAICompatibleProvider,
    ProviderType.ANTHROPIC: AnthropicProvider,
}

# Singleton instances keyed by provider type.
_provider_instances: dict[ProviderType, BaseProvider] = {}


def get_provider(
    provider_type: ProviderType,
    *,
    timeout: float = 120.0,
    connect_timeout: float = 10.0,
) -> BaseProvider:
    """Return a (cached) provider instance for the given type."""
    if provider_type not in _provider_instances:
        cls = _PROVIDER_MAP.get(provider_type)
        if cls is None:
            raise ValueError(f"Unsupported provider type: {provider_type}")
        _provider_instances[provider_type] = cls(
            timeout=timeout,
            connect_timeout=connect_timeout,
        )
    return _provider_instances[provider_type]
