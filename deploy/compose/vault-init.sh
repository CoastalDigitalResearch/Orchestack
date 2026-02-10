#!/usr/bin/env sh
set -e

VAULT_ADDR="${VAULT_ADDR:-http://vault:8200}"
VAULT_TOKEN="${VAULT_TOKEN:-orchestack-dev-token}"
export VAULT_ADDR VAULT_TOKEN

echo "==> Waiting for Vault..."
until vault status > /dev/null 2>&1; do
    sleep 1
done
echo "==> Vault is ready."

# Enable KV v2 secrets engine at 'secret/' (already enabled in dev mode,
# but this is idempotent for production).
vault secrets enable -path=secret -version=2 kv 2>/dev/null || true

# Create Orchestack-specific policy.
vault policy write orchestack-service - <<'POLICY'
# Read/write connector secrets.
path "secret/data/orchestack/connectors/*" {
    capabilities = ["create", "update", "read", "delete", "list"]
}
path "secret/metadata/orchestack/connectors/*" {
    capabilities = ["list", "read", "delete"]
}

# Read/write model provider secrets.
path "secret/data/orchestack/models/*" {
    capabilities = ["create", "update", "read", "delete", "list"]
}
path "secret/metadata/orchestack/models/*" {
    capabilities = ["list", "read", "delete"]
}

# Read/write agent secrets.
path "secret/data/orchestack/agents/*" {
    capabilities = ["create", "update", "read", "delete", "list"]
}
path "secret/metadata/orchestack/agents/*" {
    capabilities = ["list", "read", "delete"]
}

# Transit engine for MinIO encryption keys.
path "transit/encrypt/minio-*" {
    capabilities = ["update"]
}
path "transit/decrypt/minio-*" {
    capabilities = ["update"]
}
POLICY

# Enable AppRole auth method (idempotent).
vault auth enable approle 2>/dev/null || true

# Create AppRole for Orchestack services.
vault write auth/approle/role/orchestack-service \
    token_policies="orchestack-service" \
    token_ttl=1h \
    token_max_ttl=4h \
    secret_id_ttl=0

# Retrieve and display the role_id for dev convenience.
ROLE_ID=$(vault read -field=role_id auth/approle/role/orchestack-service/role-id)
echo "==> AppRole role_id: ${ROLE_ID}"

# Generate a secret_id.
SECRET_ID=$(vault write -field=secret_id -f auth/approle/role/orchestack-service/secret-id)
echo "==> AppRole secret_id: ${SECRET_ID}"

# Seed example connector secrets for dev.
vault kv put secret/orchestack/connectors/discord/dev-bot \
    bot_token="dev-discord-token-placeholder" || true

vault kv put secret/orchestack/models/openai \
    api_key="dev-openai-key-placeholder" || true

vault kv put secret/orchestack/models/anthropic \
    api_key="dev-anthropic-key-placeholder" || true

echo "==> Vault initialization complete."
