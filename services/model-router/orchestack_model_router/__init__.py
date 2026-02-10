"""Orchestack Model Router - LLM routing and load balancing service."""

from orchestack_model_router.config import Settings, settings
from orchestack_model_router.models import (
    ChatMessage,
    CostPerToken,
    LatencyRequirement,
    Locality,
    ModelRecord,
    ModelStatus,
    PrivacyClass,
    ProviderResponse,
    ProviderType,
    RoutingError,
    RoutingMetrics,
    RoutingRequest,
    RoutingResponse,
    SizeClass,
    TokenUsage,
)
from orchestack_model_router.providers import (
    AnthropicProvider,
    BaseProvider,
    OpenAICompatibleProvider,
    get_provider,
)
from orchestack_model_router.router import (
    AllProvidersFailedError,
    CircuitBreaker,
    ModelRegistry,
    NoModelsAvailableError,
    RoutingEngine,
)

__all__ = [
    # router
    "AllProvidersFailedError",
    # providers
    "AnthropicProvider",
    "BaseProvider",
    # models
    "ChatMessage",
    "CircuitBreaker",
    "CostPerToken",
    "LatencyRequirement",
    "Locality",
    "ModelRecord",
    "ModelRegistry",
    "ModelStatus",
    "NoModelsAvailableError",
    "OpenAICompatibleProvider",
    "PrivacyClass",
    "ProviderResponse",
    "ProviderType",
    "RoutingEngine",
    "RoutingError",
    "RoutingMetrics",
    "RoutingRequest",
    "RoutingResponse",
    # config
    "Settings",
    "SizeClass",
    "TokenUsage",
    "get_provider",
    "settings",
]
