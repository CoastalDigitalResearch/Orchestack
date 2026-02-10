package store

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"

	"github.com/CoastalDigitalResearch/Orchestack/services/policy-evaluator/internal/policy"
)

// PolicyStore defines the interface for reading policy-related data.
type PolicyStore interface {
	GetOrgPolicies(ctx context.Context, tenantID string) ([]policy.OrgPolicy, error)
	GetCapabilityGrants(ctx context.Context, tenantID, agentID string) ([]policy.CapabilityGrant, error)
	GetAgentDefinition(ctx context.Context, tenantID, agentID string) (*policy.AgentDefinition, error)
	GetBudgetUsage(ctx context.Context, tenantID, scope, scopeID string) (*policy.BudgetUsage, error)
}

// PostgresPolicyStore implements PolicyStore backed by a *sql.DB.
type PostgresPolicyStore struct {
	db *sql.DB
}

// NewPostgresPolicyStore returns a PostgresPolicyStore using the given connection.
func NewPostgresPolicyStore(db *sql.DB) *PostgresPolicyStore {
	return &PostgresPolicyStore{db: db}
}

// GetOrgPolicies returns all org policies for a tenant.
func (s *PostgresPolicyStore) GetOrgPolicies(ctx context.Context, tenantID string) ([]policy.OrgPolicy, error) {
	const q = `
		SELECT id, tenant_id, name, COALESCE(description, ''), policy_data, is_default, created_at, updated_at
		FROM org_policies
		WHERE tenant_id = $1
		ORDER BY is_default DESC, created_at ASC
	`

	rows, err := s.db.QueryContext(ctx, q, tenantID)
	if err != nil {
		return nil, fmt.Errorf("query org_policies: %w", err)
	}
	defer rows.Close()

	var policies []policy.OrgPolicy
	for rows.Next() {
		var p policy.OrgPolicy
		var policyDataJSON []byte
		if err := rows.Scan(
			&p.ID, &p.TenantID, &p.Name, &p.Description,
			&policyDataJSON, &p.IsDefault, &p.CreatedAt, &p.UpdatedAt,
		); err != nil {
			return nil, fmt.Errorf("scan org_policies row: %w", err)
		}
		if err := json.Unmarshal(policyDataJSON, &p.PolicyData); err != nil {
			return nil, fmt.Errorf("unmarshal policy_data for %s: %w", p.ID, err)
		}
		policies = append(policies, p)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate org_policies rows: %w", err)
	}
	return policies, nil
}

// GetCapabilityGrants returns all non-expired capability grants for a tenant + agent.
func (s *PostgresPolicyStore) GetCapabilityGrants(ctx context.Context, tenantID, agentID string) ([]policy.CapabilityGrant, error) {
	const q = `
		SELECT id, tenant_id, task_id, agent_id,
		       tools_allowed, model_classes, memory_layers,
		       COALESCE(sandbox_profile, ''), quotas, is_break_glass,
		       expires_at, created_at
		FROM capability_grants
		WHERE tenant_id = $1 AND agent_id = $2 AND expires_at > now()
		ORDER BY created_at DESC
	`

	rows, err := s.db.QueryContext(ctx, q, tenantID, agentID)
	if err != nil {
		return nil, fmt.Errorf("query capability_grants: %w", err)
	}
	defer rows.Close()

	var grants []policy.CapabilityGrant
	for rows.Next() {
		var g policy.CapabilityGrant
		var toolsJSON, modelClassesJSON, memoryLayersJSON, quotasJSON []byte
		if err := rows.Scan(
			&g.ID, &g.TenantID, &g.TaskID, &g.AgentID,
			&toolsJSON, &modelClassesJSON, &memoryLayersJSON,
			&g.SandboxProfile, &quotasJSON, &g.IsBreakGlass,
			&g.ExpiresAt, &g.CreatedAt,
		); err != nil {
			return nil, fmt.Errorf("scan capability_grants row: %w", err)
		}
		if err := json.Unmarshal(toolsJSON, &g.ToolsAllowed); err != nil {
			return nil, fmt.Errorf("unmarshal tools_allowed for %s: %w", g.ID, err)
		}
		if err := json.Unmarshal(modelClassesJSON, &g.ModelClasses); err != nil {
			return nil, fmt.Errorf("unmarshal model_classes for %s: %w", g.ID, err)
		}
		if err := json.Unmarshal(memoryLayersJSON, &g.MemoryLayers); err != nil {
			return nil, fmt.Errorf("unmarshal memory_layers for %s: %w", g.ID, err)
		}
		if err := json.Unmarshal(quotasJSON, &g.Quotas); err != nil {
			return nil, fmt.Errorf("unmarshal quotas for %s: %w", g.ID, err)
		}
		grants = append(grants, g)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate capability_grants rows: %w", err)
	}
	return grants, nil
}

// GetAgentDefinition returns the latest agent definition for a tenant + agent.
func (s *PostgresPolicyStore) GetAgentDefinition(ctx context.Context, tenantID, agentID string) (*policy.AgentDefinition, error) {
	const q = `
		SELECT id, tenant_id, agent_id, COALESCE(agent_definition_ref, ''),
		       policy_data, COALESCE(system_prompt, ''), tools_allowed,
		       model_preferences, memory_config, COALESCE(sandbox_profile, ''),
		       version, created_at, updated_at
		FROM agent_definitions
		WHERE tenant_id = $1 AND agent_id = $2
		ORDER BY version DESC
		LIMIT 1
	`

	var ad policy.AgentDefinition
	var policyDataJSON, toolsJSON, modelPrefJSON, memCfgJSON []byte
	err := s.db.QueryRowContext(ctx, q, tenantID, agentID).Scan(
		&ad.ID, &ad.TenantID, &ad.AgentID, &ad.AgentDefinitionRef,
		&policyDataJSON, &ad.SystemPrompt, &toolsJSON,
		&modelPrefJSON, &memCfgJSON, &ad.SandboxProfile,
		&ad.Version, &ad.CreatedAt, &ad.UpdatedAt,
	)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("query agent_definitions: %w", err)
	}
	if err := json.Unmarshal(policyDataJSON, &ad.PolicyData); err != nil {
		return nil, fmt.Errorf("unmarshal policy_data for agent_def %s: %w", ad.ID, err)
	}
	if err := json.Unmarshal(toolsJSON, &ad.ToolsAllowed); err != nil {
		return nil, fmt.Errorf("unmarshal tools_allowed for agent_def %s: %w", ad.ID, err)
	}
	if err := json.Unmarshal(modelPrefJSON, &ad.ModelPreferences); err != nil {
		return nil, fmt.Errorf("unmarshal model_preferences for agent_def %s: %w", ad.ID, err)
	}
	if err := json.Unmarshal(memCfgJSON, &ad.MemoryConfig); err != nil {
		return nil, fmt.Errorf("unmarshal memory_config for agent_def %s: %w", ad.ID, err)
	}
	return &ad, nil
}

// GetBudgetUsage returns the current budget usage for a given scope.
func (s *PostgresPolicyStore) GetBudgetUsage(ctx context.Context, tenantID, scope, scopeID string) (*policy.BudgetUsage, error) {
	const q = `
		SELECT id, scope, scope_id,
		       COALESCE(daily_limit_usd, 0), COALESCE(monthly_limit_usd, 0),
		       spend_today_usd, spend_month_usd
		FROM budgets
		WHERE tenant_id = $1 AND scope = $2 AND scope_id = $3
	`

	var bu policy.BudgetUsage
	err := s.db.QueryRowContext(ctx, q, tenantID, scope, scopeID).Scan(
		&bu.BudgetID, &bu.Scope, &bu.ScopeID,
		&bu.DailyLimitUSD, &bu.MonthlyLimitUSD,
		&bu.SpendTodayUSD, &bu.SpendMonthUSD,
	)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("query budgets: %w", err)
	}
	return &bu, nil
}
