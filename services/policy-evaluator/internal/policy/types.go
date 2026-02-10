package policy

import (
	"time"
)

// OrgPolicy represents a row in the org_policies table.
// The policy_data JSONB column is unpacked into PolicyData.
type OrgPolicy struct {
	ID          string     `json:"id"`
	TenantID    string     `json:"tenant_id"`
	Name        string     `json:"name"`
	Description string     `json:"description"`
	PolicyData  PolicyData `json:"policy_data"`
	IsDefault   bool       `json:"is_default"`
	CreatedAt   time.Time  `json:"created_at"`
	UpdatedAt   time.Time  `json:"updated_at"`
}

// PolicyData represents the JSONB policy_data column on org_policies.
type PolicyData struct {
	MaxSubagentDepth         int      `json:"max_subagent_depth"`
	MaxConcurrentChildren    int      `json:"max_concurrent_children"`
	MaxWallTimeS             int      `json:"max_wall_time_s"`
	AllowedModelClasses      []string `json:"allowed_model_classes"`
	AllowedMemoryLayers      []string `json:"allowed_memory_layers"`
	DefaultSandboxProfile    string   `json:"default_sandbox_profile"`
	NetworkEgress            string   `json:"network_egress"`
	DLPMode                  string   `json:"dlp_mode"`
	BreakGlassEnabled        bool     `json:"break_glass_enabled"`
	BreakGlassDurationS      int      `json:"break_glass_duration_s"`
	BreakGlassApprovalsReq   int      `json:"break_glass_approvals_required"`
	AllowedActions           []string `json:"allowed_actions,omitempty"`
	AllowedTools             []string `json:"allowed_tools,omitempty"`
	AllowedModels            []string `json:"allowed_models,omitempty"`
	MaxBudgetUSD             float64  `json:"max_budget_usd,omitempty"`
	MaxTokensPerRequest      int      `json:"max_tokens_per_request,omitempty"`
	RequireApprovalAboveUSD  float64  `json:"require_approval_above_usd,omitempty"`
	DenyPatterns             []string `json:"deny_patterns,omitempty"`
	DefaultAction            string   `json:"default_action,omitempty"`
	RateLimitPerMinute       int      `json:"rate_limit_per_minute,omitempty"`
}

// CapabilityGrant represents a row in the capability_grants table.
type CapabilityGrant struct {
	ID             string    `json:"id"`
	TenantID       string    `json:"tenant_id"`
	TaskID         string    `json:"task_id"`
	AgentID        string    `json:"agent_id"`
	ToolsAllowed   []string  `json:"tools_allowed"`
	ModelClasses   []string  `json:"model_classes"`
	MemoryLayers   []string  `json:"memory_layers"`
	SandboxProfile string    `json:"sandbox_profile"`
	Quotas         Quotas    `json:"quotas"`
	IsBreakGlass   bool      `json:"is_break_glass"`
	ExpiresAt      time.Time `json:"expires_at"`
	CreatedAt      time.Time `json:"created_at"`
}

// Quotas represents the JSONB quotas column on capability_grants.
type Quotas struct {
	MaxTokens   int     `json:"max_tokens,omitempty"`
	MaxCostUSD  float64 `json:"max_cost_usd,omitempty"`
	MaxRequests int     `json:"max_requests,omitempty"`
}

// AgentDefinition represents a row in the agent_definitions table.
type AgentDefinition struct {
	ID                 string            `json:"id"`
	TenantID           string            `json:"tenant_id"`
	AgentID            string            `json:"agent_id"`
	AgentDefinitionRef string            `json:"agent_definition_ref"`
	PolicyData         PolicyData        `json:"policy_data"`
	SystemPrompt       string            `json:"system_prompt"`
	ToolsAllowed       []string          `json:"tools_allowed"`
	ModelPreferences   map[string]string `json:"model_preferences"`
	MemoryConfig       map[string]string `json:"memory_config"`
	SandboxProfile     string            `json:"sandbox_profile"`
	Version            int               `json:"version"`
	CreatedAt          time.Time         `json:"created_at"`
	UpdatedAt          time.Time         `json:"updated_at"`
}

// BudgetUsage holds aggregated spend information for a budget scope.
type BudgetUsage struct {
	BudgetID       string  `json:"budget_id"`
	Scope          string  `json:"scope"`
	ScopeID        string  `json:"scope_id"`
	DailyLimitUSD  float64 `json:"daily_limit_usd"`
	MonthlyLimitUSD float64 `json:"monthly_limit_usd"`
	SpendTodayUSD  float64 `json:"spend_today_usd"`
	SpendMonthUSD  float64 `json:"spend_month_usd"`
}

// EvaluateRequest is the inbound request to the policy evaluation endpoint.
type EvaluateRequest struct {
	TenantID string            `json:"tenant_id"`
	AgentID  string            `json:"agent_id"`
	Action   string            `json:"action"`
	Resource map[string]string `json:"resource"`
	Context  map[string]string `json:"context"`
}

// EvaluateResponse is returned by the policy evaluation endpoint.
type EvaluateResponse struct {
	Allowed  bool   `json:"allowed"`
	Reason   string `json:"reason"`
	PolicyID string `json:"policy_id,omitempty"`
}

// PolicyDecision is the internal result of the policy engine evaluation.
type PolicyDecision struct {
	Allowed         bool
	Reason          string
	MatchedPolicyID string
}
