from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class StorageConfig:
    """Configuration for the S3-compatible storage client."""

    endpoint: str = "http://localhost:9000"
    access_key: str = "orchestack"
    secret_key: str = "orchestack-dev"
    region: str = "us-east-1"
    use_ssl: bool = False

    @classmethod
    def from_env(cls) -> StorageConfig:
        """Load configuration from environment variables."""
        endpoint = os.getenv("MINIO_ENDPOINT", "localhost:9000")
        use_ssl = os.getenv("MINIO_USE_SSL", "false").lower() == "true"
        scheme = "https" if use_ssl else "http"
        if not endpoint.startswith(("http://", "https://")):
            endpoint = f"{scheme}://{endpoint}"

        return cls(
            endpoint=endpoint,
            access_key=os.getenv("MINIO_ACCESS_KEY", "orchestack"),
            secret_key=os.getenv("MINIO_SECRET_KEY", "orchestack-dev"),
            region=os.getenv("MINIO_REGION", "us-east-1"),
            use_ssl=use_ssl,
        )
