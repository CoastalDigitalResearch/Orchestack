package handler

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/CoastalDigitalResearch/Orchestack/services/policy-evaluator/internal/policy"
)

// --- mock store -------------------------------------------------------------

type mockPolicyStore struct {
	policies []policy.OrgPolicy
	grants   []policy.CapabilityGrant
	budget   *policy.BudgetUsage
	agentDef *policy.AgentDefinition

	policiesErr error
	grantsErr   error
	budgetErr   error
	agentDefErr error
}

func (m *mockPolicyStore) GetOrgPolicies(_ context.Context, _ string) ([]policy.OrgPolicy, error) {
	return m.policies, m.policiesErr
}

func (m *mockPolicyStore) GetCapabilityGrants(_ context.Context, _, _ string) ([]policy.CapabilityGrant, error) {
	return m.grants, m.grantsErr
}

func (m *mockPolicyStore) GetAgentDefinition(_ context.Context, _, _ string) (*policy.AgentDefinition, error) {
	return m.agentDef, m.agentDefErr
}

func (m *mockPolicyStore) GetBudgetUsage(_ context.Context, _, _, _ string) (*policy.BudgetUsage, error) {
	return m.budget, m.budgetErr
}

var _ policy.Store = (*mockPolicyStore)(nil)

// --- helpers ----------------------------------------------------------------

func defaultMockStore() *mockPolicyStore {
	return &mockPolicyStore{
		policies: []policy.OrgPolicy{
			{
				ID:        "pol-1",
				TenantID:  "tenant-1",
				Name:      "default",
				IsDefault: true,
				PolicyData: policy.PolicyData{
					AllowedActions:      []string{"*"},
					AllowedModelClasses: []string{"*"},
					AllowedTools:        []string{"*"},
				},
			},
		},
		grants: []policy.CapabilityGrant{
			{
				ID:           "grant-1",
				TenantID:     "tenant-1",
				AgentID:      "agent-1",
				ToolsAllowed: []string{"*"},
				ModelClasses: []string{"*"},
				ExpiresAt:    time.Now().Add(24 * time.Hour),
			},
		},
	}
}

func makeEvalRequest(action string) policy.EvaluateRequest {
	return policy.EvaluateRequest{
		TenantID: "tenant-1",
		AgentID:  "agent-1",
		Action:   action,
		Resource: map[string]string{"tool": "shell_exec"},
	}
}

func doEvalRequest(t *testing.T, handler http.Handler, method string, body interface{}) *httptest.ResponseRecorder {
	t.Helper()
	var buf bytes.Buffer
	if body != nil {
		json.NewEncoder(&buf).Encode(body)
	}
	req := httptest.NewRequest(method, "/v1/evaluate", &buf)
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)
	return rr
}

// --- tests ------------------------------------------------------------------

func TestEvaluate_Allowed(t *testing.T) {
	store := defaultMockStore()
	engine := policy.NewPolicyEngine(store)
	engine.LoadPolicies(context.Background(), "tenant-1")
	handler := NewEvaluateHandler(engine)

	rr := doEvalRequest(t, handler, http.MethodPost, makeEvalRequest("execute_task"))

	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", rr.Code, rr.Body.String())
	}

	var resp policy.EvaluateResponse
	json.NewDecoder(rr.Body).Decode(&resp)
	if !resp.Allowed {
		t.Errorf("expected allowed=true, got false: %s", resp.Reason)
	}
}

func TestEvaluate_Denied_NoGrants(t *testing.T) {
	store := defaultMockStore()
	store.grants = nil // no grants
	engine := policy.NewPolicyEngine(store)
	engine.LoadPolicies(context.Background(), "tenant-1")
	handler := NewEvaluateHandler(engine)

	rr := doEvalRequest(t, handler, http.MethodPost, makeEvalRequest("execute_task"))

	if rr.Code != http.StatusForbidden {
		t.Fatalf("expected 403, got %d: %s", rr.Code, rr.Body.String())
	}

	var resp policy.EvaluateResponse
	json.NewDecoder(rr.Body).Decode(&resp)
	if resp.Allowed {
		t.Error("expected allowed=false")
	}
}

func TestEvaluate_Denied_BudgetExceeded(t *testing.T) {
	store := defaultMockStore()
	store.budget = &policy.BudgetUsage{
		DailyLimitUSD: 10.0,
		SpendTodayUSD: 15.0, // over limit
	}
	engine := policy.NewPolicyEngine(store)
	engine.LoadPolicies(context.Background(), "tenant-1")
	handler := NewEvaluateHandler(engine)

	rr := doEvalRequest(t, handler, http.MethodPost, makeEvalRequest("execute_task"))

	if rr.Code != http.StatusForbidden {
		t.Fatalf("expected 403, got %d: %s", rr.Code, rr.Body.String())
	}

	var resp policy.EvaluateResponse
	json.NewDecoder(rr.Body).Decode(&resp)
	if resp.Allowed {
		t.Error("expected allowed=false for budget exceeded")
	}
}

func TestEvaluate_MethodNotAllowed(t *testing.T) {
	engine := policy.NewPolicyEngine(defaultMockStore())
	handler := NewEvaluateHandler(engine)

	rr := doEvalRequest(t, handler, http.MethodGet, nil)

	if rr.Code != http.StatusMethodNotAllowed {
		t.Errorf("expected 405, got %d", rr.Code)
	}
}

func TestEvaluate_BadRequest(t *testing.T) {
	engine := policy.NewPolicyEngine(defaultMockStore())
	handler := NewEvaluateHandler(engine)

	req := httptest.NewRequest(http.MethodPost, "/v1/evaluate", bytes.NewBufferString("not json"))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()
	handler.ServeHTTP(rr, req)

	if rr.Code != http.StatusBadRequest {
		t.Errorf("expected 400, got %d", rr.Code)
	}
}

func TestEvaluate_MissingFields(t *testing.T) {
	store := defaultMockStore()
	engine := policy.NewPolicyEngine(store)
	handler := NewEvaluateHandler(engine)

	// Missing action
	badReq := policy.EvaluateRequest{
		TenantID: "tenant-1",
		AgentID:  "agent-1",
	}
	rr := doEvalRequest(t, handler, http.MethodPost, badReq)

	if rr.Code != http.StatusForbidden {
		t.Fatalf("expected 403, got %d: %s", rr.Code, rr.Body.String())
	}

	var resp policy.EvaluateResponse
	json.NewDecoder(rr.Body).Decode(&resp)
	if resp.Allowed {
		t.Error("expected allowed=false for missing fields")
	}
}
