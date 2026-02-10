"""Configuration for the Model Router service."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Model Router configuration, populated from environment variables."""

    model_config = {"env_prefix": "ORCHESTACK_", "case_sensitive": False}

    # NATS
    nats_url: str = "nats://localhost:4222"
    nats_request_subject: str = "router.request"
    nats_completed_subject: str = "router.completed"
    nats_failed_subject: str = "router.failed"
    nats_metrics_subject: str = "router.metrics"
    nats_queue_group: str = "model-router"

    # Database
    database_url: str = "postgresql+asyncpg://orchestack:orchestack@localhost:5432/orchestack"

    # Service
    service_name: str = "orchestack-model-router"
    service_host: str = "0.0.0.0"
    service_port: int = 8080
    log_level: str = "INFO"

    # Circuit breaker defaults
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_timeout: float = 60.0  # seconds
    circuit_breaker_half_open_max_calls: int = 1

    # Provider timeouts
    provider_request_timeout: float = 120.0  # seconds
    provider_connect_timeout: float = 10.0  # seconds

    # Routing defaults
    default_max_retries: int = 3


settings = Settings()
