"""Slack-specific connector settings loaded from environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class SlackConnectorSettings(BaseSettings):
    """Configuration for the Orchestack Slack connector.

    Every field can be set via an environment variable with the
    ``ORCHESTACK_SLACK_`` prefix (case-insensitive).  For example::

        ORCHESTACK_SLACK_BOT_TOKEN=xoxb-...
        ORCHESTACK_SLACK_APP_TOKEN=xapp-...
        ORCHESTACK_SLACK_SIGNING_SECRET=abc123
    """

    model_config = {"env_prefix": "ORCHESTACK_SLACK_"}

    # --- Slack credentials (required) ---
    bot_token: str
    """Bot user OAuth token (xoxb-...)."""

    app_token: str
    """App-level token for Socket Mode (xapp-...)."""

    signing_secret: str
    """Signing secret used to verify requests from Slack."""

    # --- NATS ---
    nats_url: str = "nats://localhost:4222"

    # --- Channel filtering (optional) ---
    channel_ids: list[str] | None = None
    """If set, only messages from these channel IDs are forwarded."""

    # --- Identity ---
    account_id: str = "default"
    """Unique identifier for this connector instance."""

    # --- Tuning ---
    health_port: int = 8080
    """Port for the FastAPI health/readiness endpoints."""
