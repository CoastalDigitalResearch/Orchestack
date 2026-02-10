from __future__ import annotations

import logging
from typing import Any

import hvac

from orchestack_vault.config import VaultConfig

logger = logging.getLogger(__name__)


class VaultError(Exception):
    """Raised when a Vault operation fails."""


class VaultClient:
    """Wrapper around hvac providing Orchestack-specific Vault operations.

    Supports token auth (dev/CI) and AppRole auth (production).
    Provides typed helpers for the KV v2 paths used by Orchestack services.
    """

    # Standard KV v2 path prefixes.
    PATH_CONNECTORS = "orchestack/connectors"
    PATH_MODELS = "orchestack/models"
    PATH_AGENTS = "orchestack/agents"

    def __init__(self, config: VaultConfig | None = None) -> None:
        cfg = config or VaultConfig.from_env()
        self._mount = cfg.mount_point
        self._client = hvac.Client(url=cfg.addr, namespace=cfg.namespace)
        self._authenticate(cfg)

    def _authenticate(self, cfg: VaultConfig) -> None:
        """Authenticate to Vault using token or AppRole."""
        if cfg.token:
            self._client.token = cfg.token
        elif cfg.role_id and cfg.secret_id:
            resp = self._client.auth.approle.login(
                role_id=cfg.role_id,
                secret_id=cfg.secret_id,
            )
            self._client.token = resp["auth"]["client_token"]
            logger.info("authenticated to Vault via AppRole")
        else:
            logger.warning("no Vault credentials provided; client may not be authenticated")

    @property
    def is_authenticated(self) -> bool:
        """Check whether the client has a valid token."""
        try:
            return self._client.is_authenticated()
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Generic KV v2 operations
    # ------------------------------------------------------------------

    def read_secret(self, path: str) -> dict[str, Any]:
        """Read a secret from KV v2. Returns the data dict."""
        try:
            resp = self._client.secrets.kv.v2.read_secret_version(
                path=path,
                mount_point=self._mount,
            )
            return resp["data"]["data"]
        except hvac.exceptions.InvalidPath as exc:
            raise VaultError(f"secret not found: {path}") from exc
        except Exception as exc:
            raise VaultError(f"failed to read secret {path}: {exc}") from exc

    def write_secret(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        """Write a secret to KV v2. Returns version metadata."""
        try:
            resp = self._client.secrets.kv.v2.create_or_update_secret(
                path=path,
                secret=data,
                mount_point=self._mount,
            )
            return resp["data"]
        except Exception as exc:
            raise VaultError(f"failed to write secret {path}: {exc}") from exc

    def delete_secret(self, path: str) -> None:
        """Delete all versions of a secret."""
        try:
            self._client.secrets.kv.v2.delete_metadata_and_all_versions(
                path=path,
                mount_point=self._mount,
            )
        except Exception as exc:
            raise VaultError(f"failed to delete secret {path}: {exc}") from exc

    def list_secrets(self, path: str) -> list[str]:
        """List secret keys under a path."""
        try:
            resp = self._client.secrets.kv.v2.list_secrets(
                path=path,
                mount_point=self._mount,
            )
            return resp["data"]["keys"]
        except hvac.exceptions.InvalidPath:
            return []
        except Exception as exc:
            raise VaultError(f"failed to list secrets at {path}: {exc}") from exc

    # ------------------------------------------------------------------
    # Typed helpers for Orchestack paths
    # ------------------------------------------------------------------

    def get_connector_secret(self, connector_type: str, account_id: str) -> dict[str, Any]:
        """Read connector credentials."""
        path = f"{self.PATH_CONNECTORS}/{connector_type}/{account_id}"
        return self.read_secret(path)

    def set_connector_secret(self, connector_type: str, account_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Store connector credentials."""
        path = f"{self.PATH_CONNECTORS}/{connector_type}/{account_id}"
        return self.write_secret(path, data)

    def get_model_secret(self, provider: str) -> dict[str, Any]:
        """Read model provider API keys."""
        path = f"{self.PATH_MODELS}/{provider}"
        return self.read_secret(path)

    def set_model_secret(self, provider: str, data: dict[str, Any]) -> dict[str, Any]:
        """Store model provider API keys."""
        path = f"{self.PATH_MODELS}/{provider}"
        return self.write_secret(path, data)

    def get_agent_secret(self, agent_id: str) -> dict[str, Any]:
        """Read agent-specific secrets."""
        path = f"{self.PATH_AGENTS}/{agent_id}"
        return self.read_secret(path)

    def set_agent_secret(self, agent_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Store agent-specific secrets."""
        path = f"{self.PATH_AGENTS}/{agent_id}"
        return self.write_secret(path, data)
