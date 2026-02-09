"""Vault client with auth method abstraction."""

from __future__ import annotations

import os

import hvac


class VaultClient:
    """HashiCorp Vault client with K8s and AppRole auth support."""

    def __init__(self, url: str | None = None, token: str | None = None):
        self._url = url or os.environ.get("VAULT_ADDR", "http://localhost:8200")
        self._token = token or os.environ.get("VAULT_TOKEN")
        self._client = hvac.Client(url=self._url, token=self._token)

    def auth_kubernetes(self, role: str, jwt_path: str = "/var/run/secrets/kubernetes.io/serviceaccount/token"):
        """Authenticate using Kubernetes service account."""
        with open(jwt_path) as f:
            jwt = f.read()
        self._client.auth.kubernetes.login(role=role, jwt=jwt)

    def auth_approle(self, role_id: str, secret_id: str):
        """Authenticate using AppRole."""
        self._client.auth.approle.login(role_id=role_id, secret_id=secret_id)

    def read_secret(self, path: str, mount_point: str = "orchestack") -> dict:
        """Read from KV v2 secrets engine."""
        response = self._client.secrets.kv.v2.read_secret_version(path=path, mount_point=mount_point)
        return response["data"]["data"]

    def write_secret(self, path: str, data: dict, mount_point: str = "orchestack") -> None:
        """Write to KV v2 secrets engine."""
        self._client.secrets.kv.v2.create_or_update_secret(path=path, secret=data, mount_point=mount_point)

    @property
    def is_authenticated(self) -> bool:
        return self._client.is_authenticated()
