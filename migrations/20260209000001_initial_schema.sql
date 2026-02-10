-- =============================================================================
-- Orchestack Initial Schema Migration
-- Covers RFC-001 (Event/State), RFC-002 (Policy), RFC-005 (Extensions)
-- All tables include tenant_id for multi-tenancy (FK to tenants)
-- =============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- =============================================================================
-- CORE ENTITIES (RFC-001 Section 9)
-- =============================================================================

CREATE TABLE tenants (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_tenants_slug ON tenants (slug);

-- -------------------------------------------------------------------------

CREATE TABLE workspaces (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_workspaces_tenant ON workspaces (tenant_id);

-- -------------------------------------------------------------------------

CREATE TABLE agents (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    workspace_id         UUID NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    name                 TEXT NOT NULL,
    agent_definition_ref TEXT,
    status               TEXT NOT NULL DEFAULT 'active',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_agents_tenant ON agents (tenant_id);
CREATE INDEX idx_agents_workspace ON agents (workspace_id);
CREATE INDEX idx_agents_status ON agents (tenant_id, status);

-- -------------------------------------------------------------------------

CREATE TABLE sessions (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id                   UUID NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    agent_id                    UUID NOT NULL REFERENCES agents (id) ON DELETE CASCADE,
    connector_type              TEXT NOT NULL,
    connector_account_id        TEXT NOT NULL,
    thread_id                   TEXT NOT NULL,
    next_ingress_seq            BIGINT NOT NULL DEFAULT 1,
    last_processed_ingress_seq  BIGINT NOT NULL DEFAULT 0,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_sessions_connector_thread
        UNIQUE (tenant_id, connector_type, connector_account_id, thread_id)
);

CREATE INDEX idx_sessions_tenant ON sessions (tenant_id);
CREATE INDEX idx_sessions_agent ON sessions (agent_id);

-- -------------------------------------------------------------------------

CREATE TABLE ingress_messages (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    session_id   UUID NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    ingress_seq  BIGINT NOT NULL,
    payload_ref  TEXT,
    content      TEXT,
    sender_id    TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_ingress_tenant_session_seq
        UNIQUE (tenant_id, session_id, ingress_seq)
);

CREATE INDEX idx_ingress_session ON ingress_messages (session_id);
CREATE INDEX idx_ingress_session_seq ON ingress_messages (session_id, ingress_seq);

-- -------------------------------------------------------------------------

CREATE TABLE tasks (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    session_id          UUID NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    agent_id            UUID NOT NULL REFERENCES agents (id) ON DELETE CASCADE,
    parent_task_id      UUID REFERENCES tasks (id),
    status              TEXT NOT NULL DEFAULT 'NEW'
                        CHECK (status IN (
                            'NEW', 'QUEUED', 'RUNNING', 'WAITING_APPROVAL',
                            'COMPLETED', 'FAILED', 'CANCELLED', 'TIMED_OUT'
                        )),
    budget_id           UUID,
    capability_grant_id UUID,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_tasks_tenant ON tasks (tenant_id);
CREATE INDEX idx_tasks_session ON tasks (session_id);
CREATE INDEX idx_tasks_agent ON tasks (agent_id);
CREATE INDEX idx_tasks_parent ON tasks (parent_task_id);
CREATE INDEX idx_tasks_status ON tasks (tenant_id, status);

-- -------------------------------------------------------------------------

CREATE TABLE runs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    task_id       UUID NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
    attempt       INT NOT NULL DEFAULT 1,
    status        TEXT NOT NULL DEFAULT 'RUNNING'
                  CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED')),
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_runs_task ON runs (task_id);
CREATE INDEX idx_runs_tenant ON runs (tenant_id);
CREATE UNIQUE INDEX idx_runs_task_attempt ON runs (tenant_id, task_id, attempt);

-- -------------------------------------------------------------------------

CREATE TABLE steps (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    run_id           UUID NOT NULL REFERENCES runs (id) ON DELETE CASCADE,
    step_type        TEXT NOT NULL
                     CHECK (step_type IN (
                         'model_call', 'tool_call', 'memory_search',
                         'memory_write', 'approval_wait', 'connector_send'
                     )),
    step_seq         INT NOT NULL,
    idempotency_key  TEXT,
    status           TEXT NOT NULL DEFAULT 'PENDING',
    input_ref        TEXT,
    output_ref       TEXT,
    started_at       TIMESTAMPTZ,
    completed_at     TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_steps_run ON steps (run_id);
CREATE INDEX idx_steps_tenant ON steps (tenant_id);
CREATE UNIQUE INDEX idx_steps_idempotency
    ON steps (tenant_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

-- -------------------------------------------------------------------------

CREATE TABLE artifacts (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    task_id          UUID REFERENCES tasks (id) ON DELETE SET NULL,
    run_id           UUID REFERENCES runs (id) ON DELETE SET NULL,
    step_id          UUID REFERENCES steps (id) ON DELETE SET NULL,
    name             TEXT,
    content_type     TEXT,
    size_bytes       BIGINT,
    payload_ref      TEXT NOT NULL,
    sha256           TEXT,
    retention_class  TEXT DEFAULT 'standard',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_artifacts_tenant ON artifacts (tenant_id);
CREATE INDEX idx_artifacts_task ON artifacts (task_id);
CREATE INDEX idx_artifacts_run ON artifacts (run_id);
CREATE INDEX idx_artifacts_step ON artifacts (step_id);

-- -------------------------------------------------------------------------

CREATE TABLE approval_requests (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    task_id       UUID NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
    step_id       UUID REFERENCES steps (id) ON DELETE SET NULL,
    status        TEXT NOT NULL DEFAULT 'PENDING'
                  CHECK (status IN ('PENDING', 'APPROVED', 'DENIED', 'EXPIRED')),
    requested_by  TEXT,
    approved_by   TEXT,
    expires_at    TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_approval_requests_tenant ON approval_requests (tenant_id);
CREATE INDEX idx_approval_requests_task ON approval_requests (task_id);
CREATE INDEX idx_approval_requests_step ON approval_requests (step_id);
CREATE INDEX idx_approval_requests_status ON approval_requests (tenant_id, status);
CREATE INDEX idx_approval_requests_expires
    ON approval_requests (expires_at)
    WHERE status = 'PENDING';

-- =============================================================================
-- BUDGET ENTITIES
-- =============================================================================

CREATE TABLE budgets (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    agent_id        UUID REFERENCES agents (id) ON DELETE SET NULL,
    scope           TEXT NOT NULL DEFAULT 'tenant'
                    CHECK (scope IN ('tenant', 'agent', 'task')),
    daily_limit     NUMERIC(12, 4),
    monthly_limit   NUMERIC(12, 4),
    soft_threshold  NUMERIC(5, 4) DEFAULT 0.8,
    hard_threshold  NUMERIC(5, 4) DEFAULT 1.0,
    spend_today     NUMERIC(12, 4) DEFAULT 0,
    spend_month     NUMERIC(12, 4) DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_budgets_tenant ON budgets (tenant_id);
CREATE INDEX idx_budgets_agent ON budgets (agent_id);
CREATE INDEX idx_budgets_scope ON budgets (tenant_id, scope);

-- -------------------------------------------------------------------------

CREATE TABLE budget_transactions (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    budget_id      UUID NOT NULL REFERENCES budgets (id) ON DELETE CASCADE,
    model_name     TEXT,
    provider       TEXT,
    input_tokens   INT,
    output_tokens  INT,
    cost           NUMERIC(12, 6),
    task_id        UUID,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_budget_tx_tenant ON budget_transactions (tenant_id);
CREATE INDEX idx_budget_tx_budget ON budget_transactions (budget_id);
CREATE INDEX idx_budget_tx_task ON budget_transactions (task_id);
CREATE INDEX idx_budget_tx_created ON budget_transactions (created_at);

-- =============================================================================
-- POLICY ENTITIES (RFC-002)
-- =============================================================================

CREATE TABLE org_policies (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    policy      JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_org_policies_tenant UNIQUE (tenant_id)
);

-- -------------------------------------------------------------------------

CREATE TABLE agent_definitions (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    agent_id             UUID NOT NULL REFERENCES agents (id) ON DELETE CASCADE,
    agent_definition_ref TEXT,
    definition           JSONB NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_agent_definitions_tenant ON agent_definitions (tenant_id);
CREATE INDEX idx_agent_definitions_agent ON agent_definitions (agent_id);

-- -------------------------------------------------------------------------

CREATE TABLE subagent_templates (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               UUID NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    agent_definition_id     UUID NOT NULL REFERENCES agent_definitions (id) ON DELETE CASCADE,
    name                    TEXT,
    max_depth               INT DEFAULT 2,
    max_concurrent_children INT DEFAULT 8,
    max_wall_time_s         INT DEFAULT 3600,
    tool_allowlist          JSONB,
    memory_sharing_rules    JSONB,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_subagent_templates_tenant ON subagent_templates (tenant_id);
CREATE INDEX idx_subagent_templates_def ON subagent_templates (agent_definition_id);

-- -------------------------------------------------------------------------

CREATE TABLE capability_grants (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    task_id         UUID NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
    agent_id        UUID NOT NULL REFERENCES agents (id) ON DELETE CASCADE,
    allowed_tools   JSONB,
    model_classes   JSONB,
    memory_layers   JSONB,
    sandbox_profile TEXT,
    quotas          JSONB,
    expires_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_capability_grants_tenant ON capability_grants (tenant_id);
CREATE INDEX idx_capability_grants_task ON capability_grants (task_id);
CREATE INDEX idx_capability_grants_agent ON capability_grants (agent_id);
CREATE INDEX idx_capability_grants_expires ON capability_grants (expires_at);

-- =============================================================================
-- EXTENSION ENTITIES (RFC-005)
-- =============================================================================

CREATE TABLE extensions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    version     TEXT NOT NULL,
    digest      TEXT,
    trust_tier  INT NOT NULL DEFAULT 0
                CHECK (trust_tier BETWEEN 0 AND 3),
    enabled     BOOLEAN DEFAULT true,
    manifest    JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_extensions_tenant_name_version
        UNIQUE (tenant_id, name, version)
);

CREATE INDEX idx_extensions_tenant ON extensions (tenant_id);
CREATE INDEX idx_extensions_enabled ON extensions (tenant_id, enabled);

-- -------------------------------------------------------------------------

CREATE TABLE tool_descriptors (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    extension_id   UUID NOT NULL REFERENCES extensions (id) ON DELETE CASCADE,
    tool_id        TEXT NOT NULL,
    name           TEXT,
    description    TEXT,
    input_schema   JSONB,
    output_schema  JSONB,
    risk_class     TEXT,
    idempotent     BOOLEAN DEFAULT false,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_tool_descriptors_tenant ON tool_descriptors (tenant_id);
CREATE INDEX idx_tool_descriptors_extension ON tool_descriptors (extension_id);
CREATE INDEX idx_tool_descriptors_tool_id ON tool_descriptors (tenant_id, tool_id);

-- -------------------------------------------------------------------------

CREATE TABLE skill_specs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    extension_id  UUID NOT NULL REFERENCES extensions (id) ON DELETE CASCADE,
    skill_id      TEXT NOT NULL,
    name          TEXT,
    spec          JSONB NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_skill_specs_tenant ON skill_specs (tenant_id);
CREATE INDEX idx_skill_specs_extension ON skill_specs (extension_id);
CREATE INDEX idx_skill_specs_skill_id ON skill_specs (tenant_id, skill_id);

-- -------------------------------------------------------------------------

CREATE TABLE memory_plugin_endpoints (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    extension_id  UUID NOT NULL REFERENCES extensions (id) ON DELETE CASCADE,
    endpoint_url  TEXT,
    protocol      TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_memory_plugin_endpoints_tenant ON memory_plugin_endpoints (tenant_id);
CREATE INDEX idx_memory_plugin_endpoints_extension ON memory_plugin_endpoints (extension_id);

-- -------------------------------------------------------------------------

CREATE TABLE storage_driver_endpoints (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    extension_id  UUID NOT NULL REFERENCES extensions (id) ON DELETE CASCADE,
    driver_type   TEXT,
    config        JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_storage_driver_endpoints_tenant ON storage_driver_endpoints (tenant_id);
CREATE INDEX idx_storage_driver_endpoints_extension ON storage_driver_endpoints (extension_id);

-- -------------------------------------------------------------------------

CREATE TABLE loop_specs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    extension_id  UUID NOT NULL REFERENCES extensions (id) ON DELETE CASCADE,
    loop_id       TEXT NOT NULL,
    name          TEXT,
    spec          JSONB NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_loop_specs_tenant ON loop_specs (tenant_id);
CREATE INDEX idx_loop_specs_extension ON loop_specs (extension_id);
CREATE INDEX idx_loop_specs_loop_id ON loop_specs (tenant_id, loop_id);

-- -------------------------------------------------------------------------

CREATE TABLE schedule_specs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants (id) ON DELETE CASCADE,
    extension_id        UUID NOT NULL REFERENCES extensions (id) ON DELETE CASCADE,
    schedule_id         TEXT NOT NULL,
    cron_expression     TEXT NOT NULL,
    timezone            TEXT DEFAULT 'UTC',
    concurrency_policy  TEXT DEFAULT 'single_flight',
    task_template       JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_schedule_specs_tenant ON schedule_specs (tenant_id);
CREATE INDEX idx_schedule_specs_extension ON schedule_specs (extension_id);
CREATE INDEX idx_schedule_specs_schedule_id ON schedule_specs (tenant_id, schedule_id);

-- =============================================================================
-- IDENTITY MAPPING
-- =============================================================================

CREATE TABLE identity_mappings (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID REFERENCES tenants (id) ON DELETE SET NULL,
    connector_type       TEXT NOT NULL,
    connector_sender_id  TEXT NOT NULL,
    oidc_sub             TEXT,
    ldap_groups          TEXT[],
    display_name         TEXT DEFAULT 'Anonymous',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_identity_connector
        UNIQUE (connector_type, connector_sender_id)
);

CREATE INDEX idx_identity_mappings_tenant ON identity_mappings (tenant_id);
CREATE INDEX idx_identity_mappings_oidc ON identity_mappings (oidc_sub)
    WHERE oidc_sub IS NOT NULL;
