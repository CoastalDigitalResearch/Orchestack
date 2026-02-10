"""Tests for orchestack-vault (unit tests without real Vault)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from orchestack_vault.client import VaultClient
from orchestack_vault.config import VaultConfig


@pytest.fixture
def mock_hvac():
    """Patch hvac.Client and return the mock instance."""
    with patch("orchestack_vault.client.hvac.Client") as mock_client:
        instance = mock_client.return_value
        instance.is_authenticated.return_value = True
        # Mock KV v2 interface
        kv = instance.secrets.kv.v2
        yield instance, kv


class TestVaultConfig:
    def test_defaults(self):
        cfg = VaultConfig()
        assert cfg.addr == "http://localhost:8200"
        assert cfg.token is None
        assert cfg.mount_point == "secret"

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("VAULT_ADDR", "http://vault.example.com:8200")
        monkeypatch.setenv("VAULT_TOKEN", "test-token")
        monkeypatch.setenv("VAULT_MOUNT_POINT", "kv")

        cfg = VaultConfig.from_env()
        assert cfg.addr == "http://vault.example.com:8200"
        assert cfg.token == "test-token"
        assert cfg.mount_point == "kv"

    def test_from_env_approle(self, monkeypatch):
        monkeypatch.setenv("VAULT_ROLE_ID", "role-123")
        monkeypatch.setenv("VAULT_SECRET_ID", "secret-456")

        cfg = VaultConfig.from_env()
        assert cfg.role_id == "role-123"
        assert cfg.secret_id == "secret-456"


class TestVaultClientAuth:
    def test_token_auth(self, mock_hvac):
        client_mock, _ = mock_hvac
        cfg = VaultConfig(token="my-token")
        VaultClient(cfg)
        assert client_mock.token == "my-token"

    def test_approle_auth(self, mock_hvac):
        client_mock, _ = mock_hvac
        client_mock.auth.approle.login.return_value = {"auth": {"client_token": "generated-token"}}
        cfg = VaultConfig(role_id="role-1", secret_id="secret-1")
        VaultClient(cfg)
        client_mock.auth.approle.login.assert_called_once_with(role_id="role-1", secret_id="secret-1")

    def test_is_authenticated(self, mock_hvac):
        _client_mock, _ = mock_hvac
        cfg = VaultConfig(token="t")
        vc = VaultClient(cfg)
        assert vc.is_authenticated is True


class TestVaultClientKV:
    def test_read_secret(self, mock_hvac):
        _, kv = mock_hvac
        kv.read_secret_version.return_value = {"data": {"data": {"api_key": "sk-123"}}}
        cfg = VaultConfig(token="t")
        vc = VaultClient(cfg)
        data = vc.read_secret("test/path")
        assert data == {"api_key": "sk-123"}

    def test_write_secret(self, mock_hvac):
        _, kv = mock_hvac
        kv.create_or_update_secret.return_value = {"data": {"version": 1}}
        cfg = VaultConfig(token="t")
        vc = VaultClient(cfg)
        result = vc.write_secret("test/path", {"key": "value"})
        assert result["version"] == 1

    def test_list_secrets(self, mock_hvac):
        _, kv = mock_hvac
        kv.list_secrets.return_value = {"data": {"keys": ["a", "b"]}}
        cfg = VaultConfig(token="t")
        vc = VaultClient(cfg)
        keys = vc.list_secrets("test")
        assert keys == ["a", "b"]

    def test_delete_secret(self, mock_hvac):
        _, kv = mock_hvac
        cfg = VaultConfig(token="t")
        vc = VaultClient(cfg)
        vc.delete_secret("test/path")
        kv.delete_metadata_and_all_versions.assert_called_once()


class TestVaultClientHelpers:
    def test_connector_secret_roundtrip(self, mock_hvac):
        _, kv = mock_hvac
        kv.create_or_update_secret.return_value = {"data": {"version": 1}}
        kv.read_secret_version.return_value = {"data": {"data": {"bot_token": "xoxb-123"}}}
        cfg = VaultConfig(token="t")
        vc = VaultClient(cfg)

        vc.set_connector_secret("slack", "bot-1", {"bot_token": "xoxb-123"})
        data = vc.get_connector_secret("slack", "bot-1")
        assert data["bot_token"] == "xoxb-123"

    def test_model_secret(self, mock_hvac):
        _, kv = mock_hvac
        kv.read_secret_version.return_value = {"data": {"data": {"api_key": "sk-ant-123"}}}
        cfg = VaultConfig(token="t")
        vc = VaultClient(cfg)

        data = vc.get_model_secret("anthropic")
        assert data["api_key"] == "sk-ant-123"

    def test_agent_secret(self, mock_hvac):
        _, kv = mock_hvac
        kv.read_secret_version.return_value = {"data": {"data": {"custom_key": "val"}}}
        cfg = VaultConfig(token="t")
        vc = VaultClient(cfg)

        data = vc.get_agent_secret("agent-007")
        assert data["custom_key"] == "val"
