"""Common connector configuration via environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class ConnectorSettings(BaseSettings):
    """Shared settings for every Orchestack connector.

    All values can be overridden with environment variables prefixed by
    ``ORCHESTACK_CONNECTOR_`` (case-insensitive).  For example::

        ORCHESTACK_CONNECTOR_NATS_URL=nats://nats.prod:4222
    """

    model_config = {"env_prefix": "ORCHESTACK_CONNECTOR_"}

    # --- NATS ---
    nats_url: str = "nats://localhost:4222"

    # --- PostgreSQL (identity mapping) ---
    database_url: str = "postgresql://orchestack:orchestack@localhost:5432/orchestack"

    # --- MinIO / S3 ---
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "orchestack-attachments"
    minio_secure: bool = False

    # --- Vault (optional, for future secret injection) ---
    vault_addr: str = "http://localhost:8200"
    vault_token_path: str = "/var/run/secrets/vault/token"

    # --- Tuning knobs ---
    max_attachment_size_bytes: int = 10 * 1024 * 1024  # 10 MiB
    heartbeat_interval_s: int = 30
    reconnect_base_wait_s: float = 2.0
    reconnect_max_wait_s: float = 60.0
    health_port: int = 8080
