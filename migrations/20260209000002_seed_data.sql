-- =============================================================================
-- Orchestack Seed Data
-- Default tenant, org policy, and budget for local development
-- =============================================================================

-- Default tenant
INSERT INTO tenants (id, name, slug)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    'Default',
    'default'
);

-- Default org policy (empty permissive policy)
INSERT INTO org_policies (id, tenant_id, policy)
VALUES (
    '00000000-0000-0000-0000-000000000002',
    '00000000-0000-0000-0000-000000000001',
    '{}'::jsonb
);

-- Default budget for the default tenant
INSERT INTO budgets (id, tenant_id, scope, daily_limit, monthly_limit)
VALUES (
    '00000000-0000-0000-0000-000000000003',
    '00000000-0000-0000-0000-000000000001',
    'tenant',
    100.0000,
    1000.0000
);
