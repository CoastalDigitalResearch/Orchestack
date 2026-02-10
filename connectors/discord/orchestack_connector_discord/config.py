"""Configuration for the Orchestack Discord connector."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class DiscordSettings(BaseSettings):
    """Discord connector settings loaded from environment variables.

    All variables are prefixed with ``ORCHESTACK_DISCORD_``.  For example
    the bot token is read from ``ORCHESTACK_DISCORD_BOT_TOKEN``.
    """

    model_config = {"env_prefix": "ORCHESTACK_DISCORD_"}

    bot_token: str = Field(
        ...,
        description="Discord bot token (required).",
    )

    guild_ids: list[int] = Field(
        default_factory=list,
        description=("List of guild (server) IDs to monitor. An empty list means all guilds the bot belongs to."),
    )

    channel_ids: list[int] = Field(
        default_factory=list,
        description=("List of channel IDs to monitor. An empty list means all channels in monitored guilds."),
    )

    nats_url: str = Field(
        default="nats://localhost:4222",
        description="NATS server URL.",
    )

    command_prefix: str = Field(
        default="!",
        description="Prefix for bot commands.",
    )
