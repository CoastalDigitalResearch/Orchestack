"""Memory Plane configuration via environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Service configuration.

    All values can be overridden with environment variables prefixed with
    ``ORCHESTACK_`` (e.g. ``ORCHESTACK_NATS_URL``).
    """

    nats_url: str = "nats://localhost:4222"
    database_url: str = "postgresql://orchestack:orchestack@localhost:5432/orchestack"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "homarus-memory"

    model_config = {"env_prefix": ""}


settings = Settings()
