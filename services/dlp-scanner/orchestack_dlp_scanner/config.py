"""DLP Scanner configuration via environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Configuration for the DLP Scanner service.

    All settings can be overridden via environment variables prefixed
    with ``ORCHESTACK_DLP_``.  For example, ``ORCHESTACK_DLP_NATS_URL``.
    """

    nats_url: str = "nats://localhost:4222"
    scan_enabled: bool = True
    redact_mode: str = "mask"  # mask, remove, tag_only
    custom_patterns_path: str | None = None

    model_config = {"env_prefix": ""}


settings = Settings()
