from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class VaultConfig:
    """Configuration for the Vault client."""

    addr: str = "http://localhost:8200"
    token: str | None = None
    role_id: str | None = None
    secret_id: str | None = None
    namespace: str | None = None
    mount_point: str = "secret"

    @classmethod
    def from_env(cls) -> VaultConfig:
        """Load configuration from environment variables."""
        return cls(
            addr=os.getenv("VAULT_ADDR", "http://localhost:8200"),
            token=os.getenv("VAULT_TOKEN"),
            role_id=os.getenv("VAULT_ROLE_ID"),
            secret_id=os.getenv("VAULT_SECRET_ID"),
            namespace=os.getenv("VAULT_NAMESPACE"),
            mount_point=os.getenv("VAULT_MOUNT_POINT", "secret"),
        )
