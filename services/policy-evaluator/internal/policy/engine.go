package policy

import (
	"context"
	"fmt"
	"log"
	"strings"
	"sync"
	"time"
)

// Store is the interface the engine uses to load policy data.
// It mirrors the store.PolicyStore interface to avoid an import cycle.
type Store interface {
	GetOrgPolicies(ctx context.Context, tenantID string) ([]OrgPolicy, error)
	GetCapabilityGrants(ctx context.Context, tenantID, agentID string) ([]CapabilityGrant, error)
	GetAgentDefinition(ctx context.Context, tenantID, agentID string) (*AgentDefinition, error)
	GetBudgetUsage(ctx context.Context, tenantID, scope, scopeID string) (*BudgetUsage, error)
}

// PolicyEngine caches org policies and evaluates requests against them.
type PolicyEngine struct {
	store Store

	mu       sync.RWMutex
	policies map[string][]OrgPolicy // keyed by tenant_id

	// Simple in-memory rate limiter: tenant:agent:action -> timestamps
	rateMu   sync.Mutex
	rateHits map[string][]time.Time
}

// NewPolicyEngine creates a new engine backed by the given store.
func NewPolicyEngine(s Store) *PolicyEngine {
	return &PolicyEngine{
		store:    s,
		policies: make(map[string][]OrgPolicy),
		rateHits: make(map[string][]time.Time),
	}
}

// LoadPolicies fetches policies for a tenant from the database and caches them.
func (e *PolicyEngine) LoadPolicies(ctx context.Context, tenantID string) error {
	policies, err := e.store.GetOrgPolicies(ctx, tenantID)
	if err != nil {
		return fmt.Errorf("load policies for tenant %s: %w", tenantID, err)
	}

	e.mu.Lock()
	e.policies[tenantID] = policies
	e.mu.Unlock()

	log.Printf("policy-engine: loaded %d policies for tenant %s", len(policies), tenantID)
	return nil
}

// Evaluate checks whether a request is permitted by the org policies,
// capability grants, budget limits, and rate limits.
func (e *PolicyEngine) Evaluate(ctx context.Context, req EvaluateRequest) PolicyDecision {
	// Validate required fields.
	if req.TenantID == "" || req.AgentID == "" || req.Action == "" {
		return PolicyDecision{
			Allowed: false,
			Reason:  "missing required fields: tenant_id, agent_id, and action are required",
		}
	}

	// Validate action value.
	switch req.Action {
	case "execute_task", "use_tool", "select_model":
		// valid
	default:
		return PolicyDecision{
			Allowed: false,
			Reason:  fmt.Sprintf("unknown action %q; expected execute_task, use_tool, or select_model", req.Action),
		}
	}

	// 1. Check capability grants -- the agent must have at least one valid grant.
	grantDecision := e.checkCapabilityGrants(ctx, req)
	if !grantDecision.Allowed {
		return grantDecision
	}

	// 2. Check org policies (allowed actions, models, tools, deny patterns).
	policyDecision := e.checkOrgPolicies(req)
	if !policyDecision.Allowed {
		return policyDecision
	}

	// 3. Check budget limits.
	budgetDecision := e.checkBudget(ctx, req)
	if !budgetDecision.Allowed {
		return budgetDecision
	}

	// 4. Check rate limits.
	rateDecision := e.checkRateLimit(req, policyDecision.MatchedPolicyID)
	if !rateDecision.Allowed {
		return rateDecision
	}

	return PolicyDecision{
		Allowed:         true,
		Reason:          "all policy checks passed",
		MatchedPolicyID: policyDecision.MatchedPolicyID,
	}
}

// checkCapabilityGrants verifies the agent has at least one non-expired grant
// that covers the requested action.
func (e *PolicyEngine) checkCapabilityGrants(ctx context.Context, req EvaluateRequest) PolicyDecision {
	grants, err := e.store.GetCapabilityGrants(ctx, req.TenantID, req.AgentID)
	if err != nil {
		log.Printf("policy-engine: error loading capability grants: %v", err)
		return PolicyDecision{Allowed: false, Reason: "internal error loading capability grants"}
	}

	if len(grants) == 0 {
		return PolicyDecision{
			Allowed: false,
			Reason:  fmt.Sprintf("agent %s has no active capability grants", req.AgentID),
		}
	}

	// For use_tool, verify the tool is in at least one grant's tools_allowed.
	if req.Action == "use_tool" {
		toolName := req.Resource["tool"]
		if toolName != "" {
			found := false
			for _, g := range grants {
				if containsWildcardOrMatch(g.ToolsAllowed, toolName) {
					found = true
					break
				}
			}
			if !found {
				return PolicyDecision{
					Allowed: false,
					Reason:  fmt.Sprintf("tool %q not in any capability grant for agent %s", toolName, req.AgentID),
				}
			}
		}
	}

	// For select_model, verify the model class is in at least one grant's model_classes.
	if req.Action == "select_model" {
		modelClass := req.Resource["model_class"]
		if modelClass != "" {
			found := false
			for _, g := range grants {
				if containsWildcardOrMatch(g.ModelClasses, modelClass) {
					found = true
					break
				}
			}
			if !found {
				return PolicyDecision{
					Allowed: false,
					Reason:  fmt.Sprintf("model class %q not in any capability grant for agent %s", modelClass, req.AgentID),
				}
			}
		}
	}

	return PolicyDecision{Allowed: true, Reason: "capability grant check passed"}
}

// checkOrgPolicies evaluates the request against cached org policies.
func (e *PolicyEngine) checkOrgPolicies(req EvaluateRequest) PolicyDecision {
	e.mu.RLock()
	policies := e.policies[req.TenantID]
	e.mu.RUnlock()

	// If no policies are cached, attempt a permissive default.
	if len(policies) == 0 {
		return PolicyDecision{
			Allowed: true,
			Reason:  "no org policies configured; allowing by default",
		}
	}

	// Evaluate against each policy (default first, then tenant-specific).
	for _, p := range policies {
		// Check allowed actions.
		if len(p.PolicyData.AllowedActions) > 0 {
			if !containsWildcardOrMatch(p.PolicyData.AllowedActions, req.Action) {
				return PolicyDecision{
					Allowed:         false,
					Reason:          fmt.Sprintf("action %q not in allowed_actions of policy %s", req.Action, p.Name),
					MatchedPolicyID: p.ID,
				}
			}
		}

		// For use_tool: check allowed tools.
		if req.Action == "use_tool" && len(p.PolicyData.AllowedTools) > 0 {
			toolName := req.Resource["tool"]
			if toolName != "" && !containsWildcardOrMatch(p.PolicyData.AllowedTools, toolName) {
				return PolicyDecision{
					Allowed:         false,
					Reason:          fmt.Sprintf("tool %q not in allowed_tools of policy %s", toolName, p.Name),
					MatchedPolicyID: p.ID,
				}
			}
		}

		// For select_model: check allowed model classes.
		if req.Action == "select_model" {
			modelClass := req.Resource["model_class"]
			if modelClass != "" && len(p.PolicyData.AllowedModelClasses) > 0 {
				if !containsWildcardOrMatch(p.PolicyData.AllowedModelClasses, modelClass) {
					return PolicyDecision{
						Allowed:         false,
						Reason:          fmt.Sprintf("model class %q not in allowed_model_classes of policy %s", modelClass, p.Name),
						MatchedPolicyID: p.ID,
					}
				}
			}
			modelName := req.Resource["model"]
			if modelName != "" && len(p.PolicyData.AllowedModels) > 0 {
				if !containsWildcardOrMatch(p.PolicyData.AllowedModels, modelName) {
					return PolicyDecision{
						Allowed:         false,
						Reason:          fmt.Sprintf("model %q not in allowed_models of policy %s", modelName, p.Name),
						MatchedPolicyID: p.ID,
					}
				}
			}
		}

		// Check deny patterns against the resource description.
		if len(p.PolicyData.DenyPatterns) > 0 {
			desc := req.Resource["description"]
			if desc != "" {
				for _, pattern := range p.PolicyData.DenyPatterns {
					if strings.Contains(strings.ToLower(desc), strings.ToLower(pattern)) {
						return PolicyDecision{
							Allowed:         false,
							Reason:          fmt.Sprintf("resource description matches deny pattern %q in policy %s", pattern, p.Name),
							MatchedPolicyID: p.ID,
						}
					}
				}
			}
		}

		// If we matched this policy and it passed, record it.
		return PolicyDecision{
			Allowed:         true,
			Reason:          "org policy check passed",
			MatchedPolicyID: p.ID,
		}
	}

	return PolicyDecision{Allowed: true, Reason: "org policy check passed"}
}

// checkBudget verifies that the tenant or agent budget has not been exceeded.
func (e *PolicyEngine) checkBudget(ctx context.Context, req EvaluateRequest) PolicyDecision {
	// Check tenant-level budget.
	usage, err := e.store.GetBudgetUsage(ctx, req.TenantID, "tenant", req.TenantID)
	if err != nil {
		log.Printf("policy-engine: error loading tenant budget: %v", err)
		return PolicyDecision{Allowed: false, Reason: "internal error loading budget"}
	}
	if usage != nil {
		if usage.DailyLimitUSD > 0 && usage.SpendTodayUSD >= usage.DailyLimitUSD {
			return PolicyDecision{
				Allowed: false,
				Reason: fmt.Sprintf(
					"tenant daily budget exceeded (%.2f / %.2f USD)",
					usage.SpendTodayUSD, usage.DailyLimitUSD,
				),
			}
		}
		if usage.MonthlyLimitUSD > 0 && usage.SpendMonthUSD >= usage.MonthlyLimitUSD {
			return PolicyDecision{
				Allowed: false,
				Reason: fmt.Sprintf(
					"tenant monthly budget exceeded (%.2f / %.2f USD)",
					usage.SpendMonthUSD, usage.MonthlyLimitUSD,
				),
			}
		}
	}

	// Check agent-level budget.
	agentUsage, err := e.store.GetBudgetUsage(ctx, req.TenantID, "agent", req.AgentID)
	if err != nil {
		log.Printf("policy-engine: error loading agent budget: %v", err)
		return PolicyDecision{Allowed: false, Reason: "internal error loading agent budget"}
	}
	if agentUsage != nil {
		if agentUsage.DailyLimitUSD > 0 && agentUsage.SpendTodayUSD >= agentUsage.DailyLimitUSD {
			return PolicyDecision{
				Allowed: false,
				Reason: fmt.Sprintf(
					"agent daily budget exceeded (%.2f / %.2f USD)",
					agentUsage.SpendTodayUSD, agentUsage.DailyLimitUSD,
				),
			}
		}
		if agentUsage.MonthlyLimitUSD > 0 && agentUsage.SpendMonthUSD >= agentUsage.MonthlyLimitUSD {
			return PolicyDecision{
				Allowed: false,
				Reason: fmt.Sprintf(
					"agent monthly budget exceeded (%.2f / %.2f USD)",
					agentUsage.SpendMonthUSD, agentUsage.MonthlyLimitUSD,
				),
			}
		}
	}

	return PolicyDecision{Allowed: true, Reason: "budget check passed"}
}

// checkRateLimit enforces a simple in-memory per-minute rate limit.
func (e *PolicyEngine) checkRateLimit(req EvaluateRequest, policyID string) PolicyDecision {
	// Determine the rate limit from the cached policy.
	e.mu.RLock()
	policies := e.policies[req.TenantID]
	e.mu.RUnlock()

	limit := 0
	for _, p := range policies {
		if p.PolicyData.RateLimitPerMinute > 0 {
			limit = p.PolicyData.RateLimitPerMinute
			break
		}
	}
	if limit == 0 {
		return PolicyDecision{Allowed: true, Reason: "no rate limit configured"}
	}

	key := fmt.Sprintf("%s:%s:%s", req.TenantID, req.AgentID, req.Action)
	now := time.Now()
	windowStart := now.Add(-1 * time.Minute)

	e.rateMu.Lock()
	defer e.rateMu.Unlock()

	// Prune old entries.
	hits := e.rateHits[key]
	pruned := hits[:0]
	for _, t := range hits {
		if t.After(windowStart) {
			pruned = append(pruned, t)
		}
	}

	if len(pruned) >= limit {
		e.rateHits[key] = pruned
		return PolicyDecision{
			Allowed:         false,
			Reason:          fmt.Sprintf("rate limit exceeded: %d requests in the last minute (limit: %d)", len(pruned), limit),
			MatchedPolicyID: policyID,
		}
	}

	// Record this hit.
	e.rateHits[key] = append(pruned, now)
	return PolicyDecision{Allowed: true, Reason: "rate limit check passed"}
}

// containsWildcardOrMatch returns true if the list contains "*" or a
// case-insensitive match for target.
func containsWildcardOrMatch(list []string, target string) bool {
	for _, item := range list {
		if item == "*" || strings.EqualFold(item, target) {
			return true
		}
	}
	return false
}
