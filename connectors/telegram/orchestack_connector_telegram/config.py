"""Configuration for the Orchestack Telegram connector."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class TelegramSettings(BaseSettings):
    """Telegram connector settings loaded from environment variables.

    All variables are prefixed with ``ORCHESTACK_TELEGRAM_``.  For example
    the bot token is read from ``ORCHESTACK_TELEGRAM_BOT_TOKEN``.
    """

    model_config = {"env_prefix": "ORCHESTACK_TELEGRAM_"}

    bot_token: str = Field(
        ...,
        description="Telegram Bot API token (required). Obtain from @BotFather.",
    )

    nats_url: str = Field(
        default="nats://localhost:4222",
        description="NATS server URL.",
    )

    allowed_chat_ids: list[int] = Field(
        default_factory=list,
        description=(
            "List of Telegram chat IDs the bot is allowed to respond in. An empty list means all chats are allowed."
        ),
    )

    webhook_url: str | None = Field(
        default=None,
        description=(
            "Public URL for Telegram webhook delivery. If set and use_polling is False, the bot uses webhook mode."
        ),
    )

    webhook_port: int = Field(
        default=8443,
        description="Port for the webhook HTTP server.",
    )

    use_polling: bool = Field(
        default=True,
        description=(
            "Use long polling (True) or webhook mode (False). Polling is the default and simplest for development."
        ),
    )
