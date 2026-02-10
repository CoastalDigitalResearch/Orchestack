package handler

import (
	"encoding/json"
	"log"
	"net/http"

	"github.com/CoastalDigitalResearch/Orchestack/services/policy-evaluator/internal/policy"
)

// EvaluateHandler handles POST /v1/evaluate requests.
type EvaluateHandler struct {
	engine *policy.PolicyEngine
}

// NewEvaluateHandler creates a handler backed by the given policy engine.
func NewEvaluateHandler(engine *policy.PolicyEngine) *EvaluateHandler {
	return &EvaluateHandler{engine: engine}
}

// ServeHTTP implements http.Handler for the /v1/evaluate endpoint.
func (h *EvaluateHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, `{"error":"method not allowed"}`, http.StatusMethodNotAllowed)
		return
	}

	var req policy.EvaluateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadRequest)
		_ = json.NewEncoder(w).Encode(map[string]string{
			"error": "invalid request body: " + err.Error(),
		})
		return
	}

	// Ensure policies are loaded for this tenant (lazy load on first request).
	if err := h.engine.LoadPolicies(r.Context(), req.TenantID); err != nil {
		log.Printf("evaluate: failed to load policies for tenant %s: %v", req.TenantID, err)
		// Continue evaluation with whatever is cached; LoadPolicies logs the error.
	}

	decision := h.engine.Evaluate(r.Context(), req)

	resp := policy.EvaluateResponse{
		Allowed:  decision.Allowed,
		Reason:   decision.Reason,
		PolicyID: decision.MatchedPolicyID,
	}

	w.Header().Set("Content-Type", "application/json")
	if !decision.Allowed {
		w.WriteHeader(http.StatusForbidden)
	} else {
		w.WriteHeader(http.StatusOK)
	}
	if err := json.NewEncoder(w).Encode(resp); err != nil {
		log.Printf("evaluate: failed to encode response: %v", err)
	}
}
