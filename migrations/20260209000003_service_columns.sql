-- =============================================================================
-- Orchestack Service Columns Migration
-- Adds columns required by Go/Python services but missing from initial schema
-- =============================================================================

-- -------------------------------------------------------------------------
-- tasks: add payload, run_attempt, max_retries, ingress_message_id
-- -------------------------------------------------------------------------
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS payload TEXT DEFAULT '';
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS run_attempt INT DEFAULT 0;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS max_retries INT DEFAULT 5;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS ingress_message_id UUID;

-- -------------------------------------------------------------------------
-- ingress_messages: add event_id, rename content -> content_preview
-- -------------------------------------------------------------------------
ALTER TABLE ingress_messages ADD COLUMN IF NOT EXISTS event_id TEXT;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'ingress_messages' AND column_name = 'content'
    ) THEN
        ALTER TABLE ingress_messages RENAME COLUMN content TO content_preview;
    END IF;
END $$;

-- -------------------------------------------------------------------------
-- org_policies: add name, description, is_default, rename policy -> policy_data
-- -------------------------------------------------------------------------
ALTER TABLE org_policies ADD COLUMN IF NOT EXISTS name TEXT DEFAULT 'default';
ALTER TABLE org_policies ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE org_policies ADD COLUMN IF NOT EXISTS is_default BOOLEAN DEFAULT false;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'org_policies' AND column_name = 'policy'
    ) THEN
        ALTER TABLE org_policies RENAME COLUMN policy TO policy_data;
    END IF;
END $$;

-- -------------------------------------------------------------------------
-- budgets: rename to _usd suffix, add scope_id
-- -------------------------------------------------------------------------
ALTER TABLE budgets ADD COLUMN IF NOT EXISTS scope_id TEXT;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'budgets' AND column_name = 'daily_limit'
    ) THEN
        ALTER TABLE budgets RENAME COLUMN daily_limit TO daily_limit_usd;
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'budgets' AND column_name = 'monthly_limit'
    ) THEN
        ALTER TABLE budgets RENAME COLUMN monthly_limit TO monthly_limit_usd;
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'budgets' AND column_name = 'spend_today'
    ) THEN
        ALTER TABLE budgets RENAME COLUMN spend_today TO spend_today_usd;
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'budgets' AND column_name = 'spend_month'
    ) THEN
        ALTER TABLE budgets RENAME COLUMN spend_month TO spend_month_usd;
    END IF;
END $$;

-- -------------------------------------------------------------------------
-- capability_grants: make task_id nullable (for dev seed grants)
-- -------------------------------------------------------------------------
ALTER TABLE capability_grants ALTER COLUMN task_id DROP NOT NULL;

-- -------------------------------------------------------------------------
-- tasks status: Go services use lowercase but schema CHECK uses uppercase
-- Allow both cases plus extra states used by dispatcher
-- -------------------------------------------------------------------------
ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_status_check;
ALTER TABLE tasks ADD CONSTRAINT tasks_status_check CHECK (status IN (
    'NEW','QUEUED','RUNNING','WAITING_APPROVAL','COMPLETED','FAILED','CANCELLED','TIMED_OUT',
    'new','queued','running','waiting_approval','completed','failed','cancelled','timed_out',
    'dispatched','rejected'
));
