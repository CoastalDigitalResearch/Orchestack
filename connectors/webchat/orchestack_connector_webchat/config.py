"""Configuration for the Orchestack Webchat connector."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class WebchatSettings(BaseSettings):
    """Webchat connector settings loaded from environment variables.

    All variables are prefixed with ``ORCHESTACK_WEBCHAT_``.  For example
    the NATS URL is read from ``ORCHESTACK_WEBCHAT_NATS_URL``.
    """

    model_config = {"env_prefix": "ORCHESTACK_WEBCHAT_"}

    nats_url: str = Field(
        default="nats://localhost:4222",
        description="NATS server URL.",
    )

    cors_origins: list[str] = Field(
        default=["*"],
        description=("Allowed CORS origins.  Defaults to ['*'] (allow all) for development convenience."),
    )

    max_message_length: int = Field(
        default=10000,
        description="Maximum allowed length (characters) for a single chat message.",
    )

    rate_limit_per_minute: int = Field(
        default=30,
        description="Maximum number of messages a single session may send per minute.",
    )

    session_timeout_s: int = Field(
        default=3600,
        description=("Seconds of inactivity after which a session is considered expired and may be cleaned up."),
    )

    oidc_issuer: str | None = Field(
        default=None,
        description=(
            "OIDC issuer URL for token validation.  When set, the connector "
            "runs in authenticated mode and requires a valid JWT."
        ),
    )

    oidc_audience: str | None = Field(
        default=None,
        description=("Expected OIDC audience claim.  Only used when *oidc_issuer* is set."),
    )
