-- Orchestack Database Schema
-- Covers RFC-001 (Event/State), RFC-002 (Policy), RFC-005 (Extensions)
-- All tables include tenant_id for future multi-tenancy

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- =============================================================================
-- CORE ENTITIES (RFC-001)
-- =============================================================================

CREATE TABLE tenants (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    timezone        TEXT NOT NULL DEFAULT 'UTC',
    settings        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE workspaces (
    id              TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL REFERENCES tenants(id),
    name            TEXT NOT NULL,
    description     TEXT,
    settings        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_workspaces_tenant ON workspaces(tenant_id);

CREATE TABLE agents (
    id                  TEXT PRIMARY KEY,
    tenant_id           TEXT NOT NULL REFERENCES tenants(id),
    workspace_id        TEXT NOT NULL REFERENCES workspaces(id),
    name                TEXT NOT NULL,
    agent_type          TEXT NOT NULL CHECK (agent_type IN ('assistant', 'background', 'system', 'connector')),
    status              TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'suspended')),
    agent_definition_id TEXT,
    settings            JSONB NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_agents_tenant ON agents(tenant_id);
CREATE INDEX idx_agents_workspace ON agents(workspace_id);

CREATE TABLE sessions (
    id                          TEXT PRIMARY KEY,
    tenant_id                   TEXT NOT NULL REFERENCES tenants(id),
    agent_id                    TEXT NOT NULL REFERENCES agents(id),
    connector_type              TEXT NOT NULL,
    connector_account_id        TEXT NOT NULL,
    thread_id                   TEXT NOT NULL,
    next_ingress_seq            BIGINT NOT NULL DEFAULT 1,
    last_processed_ingress_seq  BIGINT NOT NULL DEFAULT 0,
    status                      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'idle', 'closed')),
    metadata                    JSONB NOT NULL DEFAULT '{}',
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_sessions_tenant ON sessions(tenant_id);
CREATE INDEX idx_sessions_agent ON sessions(agent_id);
CREATE UNIQUE INDEX idx_sessions_connector_thread ON sessions(tenant_id, connector_type, connector_account_id, thread_id);

CREATE TABLE ingress_messages (
    id              TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL REFERENCES tenants(id),
    session_id      TEXT NOT NULL REFERENCES sessions(id),
    ingress_seq     BIGINT NOT NULL,
    event_id        TEXT NOT NULL,
    payload_ref     TEXT,
    sender_id       TEXT NOT NULL,
    content_preview TEXT,
    status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'processed', 'failed')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX idx_ingress_unique ON ingress_messages(tenant_id, session_id, ingress_seq);
CREATE INDEX idx_ingress_session_seq ON ingress_messages(session_id, ingress_seq);

CREATE TABLE tasks (
    id                  TEXT PRIMARY KEY,
    tenant_id           TEXT NOT NULL REFERENCES tenants(id),
    session_id          TEXT NOT NULL REFERENCES sessions(id),
    agent_id            TEXT NOT NULL REFERENCES agents(id),
    parent_task_id      TEXT REFERENCES tasks(id),
    ingress_message_id  TEXT REFERENCES ingress_messages(id),
    status              TEXT NOT NULL DEFAULT 'new'
                        CHECK (status IN ('new', 'queued', 'running', 'waiting_approval', 'completed', 'failed', 'cancelled', 'timed_out')),
    budget_id           TEXT,
    capability_grant_id TEXT,
    priority            INT NOT NULL DEFAULT 0,
    max_wall_time_s     INT NOT NULL DEFAULT 3600,
    depth               INT NOT NULL DEFAULT 0,
    metadata            JSONB NOT NULL DEFAULT '{}',
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    version             INT NOT NULL DEFAULT 1,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_tasks_tenant ON tasks(tenant_id);
CREATE INDEX idx_tasks_session ON tasks(session_id);
CREATE INDEX idx_tasks_agent ON tasks(agent_id);
CREATE INDEX idx_tasks_parent ON tasks(parent_task_id);
CREATE INDEX idx_tasks_status ON tasks(tenant_id, status);

CREATE TABLE runs (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL REFERENCES tenants(id),
    task_id     TEXT NOT NULL REFERENCES tasks(id),
    attempt     INT NOT NULL DEFAULT 1,
    status      TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed')),
    error_msg   TEXT,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_runs_task ON runs(task_id);
CREATE UNIQUE INDEX idx_runs_task_attempt ON runs(tenant_id, task_id, attempt);

CREATE TABLE steps (
    id              TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL REFERENCES tenants(id),
    run_id          TEXT NOT NULL REFERENCES runs(id),
    task_id         TEXT NOT NULL REFERENCES tasks(id),
    step_seq        INT NOT NULL,
    step_type       TEXT NOT NULL CHECK (step_type IN ('model_call', 'tool_call', 'memory_read', 'memory_write', 'approval_wait', 'connector_send')),
    status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'failed', 'skipped')),
    idempotency_key TEXT,
    input_ref       TEXT,
    output_ref      TEXT,
    token_count     INT,
    cost_usd        DECIMAL(12, 6),
    duration_ms     INT,
    metadata        JSONB NOT NULL DEFAULT '{}',
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_steps_run ON steps(run_id);
CREATE INDEX idx_steps_task ON steps(task_id);
CREATE UNIQUE INDEX idx_steps_idempotency ON steps(tenant_id, idempotency_key) WHERE idempotency_key IS NOT NULL;

CREATE TABLE artifacts (
    id              TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL REFERENCES tenants(id),
    task_id         TEXT REFERENCES tasks(id),
    step_id         TEXT REFERENCES steps(id),
    name            TEXT NOT NULL,
    content_type    TEXT NOT NULL,
    size_bytes      BIGINT NOT NULL,
    payload_ref     TEXT NOT NULL,
    sha256          TEXT NOT NULL,
    retention_class TEXT NOT NULL DEFAULT 'standard' CHECK (retention_class IN ('ephemeral', 'standard', 'long_term', 'permanent')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_artifacts_task ON artifacts(task_id);
CREATE INDEX idx_artifacts_step ON artifacts(step_id);

CREATE TABLE approval_requests (
    id              TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL REFERENCES tenants(id),
    task_id         TEXT NOT NULL REFERENCES tasks(id),
    step_id         TEXT REFERENCES steps(id),
    request_type    TEXT NOT NULL,
    description     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'denied', 'expired')),
    required_approvals INT NOT NULL DEFAULT 1,
    current_approvals  INT NOT NULL DEFAULT 0,
    approver_groups JSONB NOT NULL DEFAULT '[]',
    expires_at      TIMESTAMPTZ NOT NULL,
    decided_at      TIMESTAMPTZ,
    decided_by      TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_approvals_task ON approval_requests(task_id);
CREATE INDEX idx_approvals_status ON approval_requests(tenant_id, status);
CREATE INDEX idx_approvals_expires ON approval_requests(expires_at) WHERE status = 'pending';

-- =============================================================================
-- BUDGET ENTITIES
-- =============================================================================

CREATE TABLE budgets (
    id              TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL REFERENCES tenants(id),
    scope           TEXT NOT NULL CHECK (scope IN ('tenant', 'agent', 'task')),
    scope_id        TEXT NOT NULL,
    daily_limit_usd DECIMAL(12, 4),
    monthly_limit_usd DECIMAL(12, 4),
    soft_threshold  DECIMAL(5, 4) NOT NULL DEFAULT 0.8,
    hard_threshold  DECIMAL(5, 4) NOT NULL DEFAULT 1.0,
    spend_today_usd DECIMAL(12, 6) NOT NULL DEFAULT 0,
    spend_month_usd DECIMAL(12, 6) NOT NULL DEFAULT 0,
    last_daily_reset  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_monthly_reset TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_budgets_tenant ON budgets(tenant_id);
CREATE INDEX idx_budgets_scope ON budgets(scope, scope_id);

CREATE TABLE budget_transactions (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL REFERENCES tenants(id),
    budget_id   TEXT NOT NULL REFERENCES budgets(id),
    task_id     TEXT REFERENCES tasks(id),
    step_id     TEXT REFERENCES steps(id),
    model_name  TEXT NOT NULL,
    provider    TEXT NOT NULL,
    input_tokens  INT NOT NULL DEFAULT 0,
    output_tokens INT NOT NULL DEFAULT 0,
    cost_usd    DECIMAL(12, 6) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_budget_tx_budget ON budget_transactions(budget_id);
CREATE INDEX idx_budget_tx_time ON budget_transactions(recorded_at);
CREATE INDEX idx_budget_tx_model ON budget_transactions(model_name);
CREATE INDEX idx_budget_tx_provider ON budget_transactions(provider);

-- =============================================================================
-- POLICY ENTITIES (RFC-002)
-- =============================================================================

CREATE TABLE org_policies (
    id              TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL REFERENCES tenants(id),
    name            TEXT NOT NULL,
    description     TEXT,
    policy_data     JSONB NOT NULL,
    is_default      BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_org_policies_tenant ON org_policies(tenant_id);

CREATE TABLE agent_definitions (
    id                      TEXT PRIMARY KEY,
    tenant_id               TEXT NOT NULL REFERENCES tenants(id),
    agent_id                TEXT NOT NULL REFERENCES agents(id),
    agent_definition_ref    TEXT,
    policy_data             JSONB NOT NULL,
    system_prompt           TEXT,
    tools_allowed           JSONB NOT NULL DEFAULT '[]',
    model_preferences       JSONB NOT NULL DEFAULT '{}',
    memory_config           JSONB NOT NULL DEFAULT '{}',
    sandbox_profile         TEXT,
    version                 INT NOT NULL DEFAULT 1,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_agent_defs_tenant ON agent_definitions(tenant_id);
CREATE INDEX idx_agent_defs_agent ON agent_definitions(agent_id);

CREATE TABLE subagent_templates (
    id                      TEXT PRIMARY KEY,
    tenant_id               TEXT NOT NULL REFERENCES tenants(id),
    agent_definition_id     TEXT NOT NULL REFERENCES agent_definitions(id),
    name                    TEXT NOT NULL,
    max_depth               INT NOT NULL DEFAULT 2,
    max_concurrent_children INT NOT NULL DEFAULT 8,
    max_wall_time_s         INT NOT NULL DEFAULT 3600,
    max_cost_usd            DECIMAL(12, 4),
    tools_allowed           JSONB NOT NULL DEFAULT '[]',
    memory_sharing          JSONB NOT NULL DEFAULT '{"share_l0": false, "share_l1": false}',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_subagent_tpl_def ON subagent_templates(agent_definition_id);

CREATE TABLE capability_grants (
    id                  TEXT PRIMARY KEY,
    tenant_id           TEXT NOT NULL REFERENCES tenants(id),
    task_id             TEXT NOT NULL REFERENCES tasks(id),
    agent_id            TEXT NOT NULL REFERENCES agents(id),
    tools_allowed       JSONB NOT NULL DEFAULT '[]',
    model_classes       JSONB NOT NULL DEFAULT '[]',
    memory_layers       JSONB NOT NULL DEFAULT '[]',
    sandbox_profile     TEXT,
    quotas              JSONB NOT NULL DEFAULT '{}',
    is_break_glass      BOOLEAN NOT NULL DEFAULT false,
    expires_at          TIMESTAMPTZ NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_grants_task ON capability_grants(task_id);
CREATE INDEX idx_grants_agent ON capability_grants(agent_id);
CREATE INDEX idx_grants_expires ON capability_grants(expires_at);

-- =============================================================================
-- IDENTITY MAPPING
-- =============================================================================

CREATE TABLE identity_mappings (
    id                      TEXT PRIMARY KEY,
    tenant_id               TEXT NOT NULL REFERENCES tenants(id),
    connector_type          TEXT NOT NULL,
    connector_sender_id     TEXT NOT NULL,
    oidc_sub                TEXT,
    ldap_groups             JSONB NOT NULL DEFAULT '[]',
    role                    TEXT NOT NULL DEFAULT 'anonymous',
    display_name            TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX idx_identity_mapping_unique ON identity_mappings(tenant_id, connector_type, connector_sender_id);

-- =============================================================================
-- MODEL REGISTRY
-- =============================================================================

CREATE TABLE models (
    id              TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL REFERENCES tenants(id),
    provider        TEXT NOT NULL,
    model_name      TEXT NOT NULL,
    endpoint        TEXT NOT NULL,
    context_length  INT NOT NULL,
    cost_per_input_token  DECIMAL(12, 8),
    cost_per_output_token DECIMAL(12, 8),
    locality        TEXT NOT NULL CHECK (locality IN ('local', 'cloud')),
    size_class      TEXT NOT NULL CHECK (size_class IN ('small', 'medium', 'large')),
    capabilities    JSONB NOT NULL DEFAULT '[]',
    privacy_class   TEXT NOT NULL DEFAULT 'internal' CHECK (privacy_class IN ('public', 'internal', 'sensitive', 'restricted')),
    status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'draining')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_models_tenant ON models(tenant_id);
CREATE INDEX idx_models_status ON models(status);

-- =============================================================================
-- EXTENSION ENTITIES (RFC-005)
-- =============================================================================

CREATE TABLE extensions (
    id              TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL REFERENCES tenants(id),
    name            TEXT NOT NULL,
    version         TEXT NOT NULL,
    extension_type  TEXT NOT NULL CHECK (extension_type IN ('tool', 'skill', 'memory', 'storage', 'loop', 'schedule', 'connector')),
    digest          TEXT NOT NULL,
    trust_tier      INT NOT NULL CHECK (trust_tier BETWEEN 0 AND 3),
    enabled         BOOLEAN NOT NULL DEFAULT true,
    manifest        JSONB NOT NULL,
    status          TEXT NOT NULL DEFAULT 'installed' CHECK (status IN ('pending', 'installing', 'installed', 'failed', 'disabled')),
    installed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_extensions_tenant ON extensions(tenant_id);
CREATE INDEX idx_extensions_type ON extensions(extension_type);
CREATE UNIQUE INDEX idx_extensions_name_version ON extensions(tenant_id, name, version);

CREATE TABLE tool_descriptors (
    id              TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL REFERENCES tenants(id),
    extension_id    TEXT NOT NULL REFERENCES extensions(id) ON DELETE CASCADE,
    tool_id         TEXT NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL,
    input_schema    JSONB NOT NULL,
    output_schema   JSONB,
    risk_class      TEXT NOT NULL DEFAULT 'low' CHECK (risk_class IN ('low', 'medium', 'high', 'critical')),
    idempotent      BOOLEAN NOT NULL DEFAULT false,
    required_capabilities JSONB NOT NULL DEFAULT '[]',
    data_classification TEXT NOT NULL DEFAULT 'internal',
    audit_level     TEXT NOT NULL DEFAULT 'standard' CHECK (audit_level IN ('none', 'standard', 'full')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_tool_desc_extension ON tool_descriptors(extension_id);
CREATE UNIQUE INDEX idx_tool_desc_tool_id ON tool_descriptors(tenant_id, tool_id);

CREATE TABLE skill_specs (
    id              TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL REFERENCES tenants(id),
    extension_id    TEXT NOT NULL REFERENCES extensions(id) ON DELETE CASCADE,
    skill_id        TEXT NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL,
    steps           JSONB NOT NULL,
    parameters_schema JSONB,
    guardrails      JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_skill_specs_extension ON skill_specs(extension_id);
CREATE UNIQUE INDEX idx_skill_specs_skill_id ON skill_specs(tenant_id, skill_id);

CREATE TABLE memory_plugin_endpoints (
    id              TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL REFERENCES tenants(id),
    extension_id    TEXT NOT NULL REFERENCES extensions(id) ON DELETE CASCADE,
    plugin_id       TEXT NOT NULL,
    endpoint_url    TEXT NOT NULL,
    capabilities    JSONB NOT NULL DEFAULT '[]',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_memory_plugins_extension ON memory_plugin_endpoints(extension_id);

CREATE TABLE storage_driver_endpoints (
    id              TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL REFERENCES tenants(id),
    extension_id    TEXT NOT NULL REFERENCES extensions(id) ON DELETE CASCADE,
    driver_id       TEXT NOT NULL,
    endpoint_url    TEXT NOT NULL,
    driver_type     TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_storage_drivers_extension ON storage_driver_endpoints(extension_id);

CREATE TABLE loop_specs (
    id              TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL REFERENCES tenants(id),
    extension_id    TEXT NOT NULL REFERENCES extensions(id) ON DELETE CASCADE,
    loop_id         TEXT NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT,
    spec            JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_loop_specs_extension ON loop_specs(extension_id);
CREATE UNIQUE INDEX idx_loop_specs_loop_id ON loop_specs(tenant_id, loop_id);

CREATE TABLE schedule_specs (
    id                  TEXT PRIMARY KEY,
    tenant_id           TEXT NOT NULL REFERENCES tenants(id),
    extension_id        TEXT REFERENCES extensions(id) ON DELETE CASCADE,
    schedule_id         TEXT NOT NULL,
    name                TEXT NOT NULL,
    cron_expression     TEXT NOT NULL,
    timezone            TEXT NOT NULL DEFAULT 'UTC',
    concurrency_policy  TEXT NOT NULL DEFAULT 'single_flight' CHECK (concurrency_policy IN ('single_flight', 'allow_overlap')),
    missed_run_policy   TEXT NOT NULL DEFAULT 'skip' CHECK (missed_run_policy IN ('catch_up', 'skip')),
    task_template       JSONB NOT NULL,
    enabled             BOOLEAN NOT NULL DEFAULT true,
    last_run_at         TIMESTAMPTZ,
    next_run_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_schedule_specs_extension ON schedule_specs(extension_id);
CREATE UNIQUE INDEX idx_schedule_specs_id ON schedule_specs(tenant_id, schedule_id);

-- =============================================================================
-- AUDIT
-- =============================================================================

CREATE TABLE audit_events (
    id              TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    actor_type      TEXT NOT NULL,
    actor_id        TEXT NOT NULL,
    task_id         TEXT,
    step_id         TEXT,
    description     TEXT NOT NULL,
    input_hash      TEXT,
    output_hash     TEXT,
    content_preview TEXT,
    sandbox_id      TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_audit_tenant_time ON audit_events(tenant_id, created_at DESC);
CREATE INDEX idx_audit_event_type ON audit_events(event_type);
CREATE INDEX idx_audit_task ON audit_events(task_id);
CREATE INDEX idx_audit_actor ON audit_events(actor_type, actor_id);

CREATE TABLE dead_letter_queue (
    id              TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL,
    stream          TEXT NOT NULL,
    subject         TEXT NOT NULL,
    payload         JSONB NOT NULL,
    error_msg       TEXT NOT NULL,
    failure_count   INT NOT NULL DEFAULT 1,
    status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'retried', 'discarded')),
    first_failed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_failed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at     TIMESTAMPTZ
);

CREATE INDEX idx_dlq_status ON dead_letter_queue(status);
CREATE INDEX idx_dlq_stream ON dead_letter_queue(stream);

-- =============================================================================
-- SEED DATA
-- =============================================================================

INSERT INTO tenants (id, name, timezone)
VALUES ('tenant-default', 'Default Tenant', 'UTC');

INSERT INTO workspaces (id, tenant_id, name, description)
VALUES ('workspace-default', 'tenant-default', 'Default Workspace', 'Default workspace for the default tenant');

INSERT INTO org_policies (id, tenant_id, name, description, policy_data, is_default)
VALUES ('policy-default', 'tenant-default', 'Default Organization Policy', 'Base guardrails for all agents', '{
    "max_subagent_depth": 2,
    "max_concurrent_children": 8,
    "max_wall_time_s": 3600,
    "allowed_model_classes": ["small", "medium", "large"],
    "allowed_memory_layers": ["L0", "L1", "L2"],
    "default_sandbox_profile": "code",
    "network_egress": "deny_all",
    "dlp_mode": "block",
    "break_glass_enabled": true,
    "break_glass_duration_s": 14400,
    "break_glass_approvals_required": 2
}', true);

INSERT INTO budgets (id, tenant_id, scope, scope_id, daily_limit_usd, monthly_limit_usd)
VALUES ('budget-default', 'tenant-default', 'tenant', 'tenant-default', 50.00, 1000.00);
