package handler

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"

	"github.com/CoastalDigitalResearch/Orchestack/services/daytona-executor/internal/sandbox"
)

// APIHandler provides HTTP endpoints for sandbox management.
type APIHandler struct {
	manager *sandbox.SandboxManager
}

// NewAPIHandler creates a new APIHandler.
func NewAPIHandler(mgr *sandbox.SandboxManager) *APIHandler {
	return &APIHandler{manager: mgr}
}

// RegisterRoutes registers all API routes on the given ServeMux.
func (h *APIHandler) RegisterRoutes(mux *http.ServeMux) {
	mux.HandleFunc("/v1/sandboxes", h.handleSandboxes)
	mux.HandleFunc("/v1/sandboxes/", h.handleSandboxByPath)
}

// createSandboxRequest is the JSON body for POST /v1/sandboxes.
type createSandboxRequest struct {
	TaskID          string                  `json:"task_id"`
	AgentID         string                  `json:"agent_id"`
	Image           string                  `json:"image"`
	ResourceProfile sandbox.ResourceProfile `json:"resource_profile"`
}

// execCommandRequest is the JSON body for POST /v1/sandboxes/{id}/exec.
type execCommandRequest struct {
	Command        string            `json:"command"`
	Args           []string          `json:"args,omitempty"`
	Env            map[string]string `json:"env,omitempty"`
	TimeoutMS      int64             `json:"timeout_ms,omitempty"`
	IdempotencyKey string            `json:"idempotency_key,omitempty"`
}

// handleSandboxes handles POST /v1/sandboxes and GET /v1/sandboxes.
func (h *APIHandler) handleSandboxes(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodPost:
		h.createSandbox(w, r)
	case http.MethodGet:
		h.listSandboxes(w, r)
	default:
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
	}
}

// handleSandboxByPath routes /v1/sandboxes/{id} and /v1/sandboxes/{id}/exec.
func (h *APIHandler) handleSandboxByPath(w http.ResponseWriter, r *http.Request) {
	// Strip the prefix "/v1/sandboxes/" to get "{id}" or "{id}/exec"
	path := strings.TrimPrefix(r.URL.Path, "/v1/sandboxes/")
	if path == "" {
		http.Error(w, "sandbox id required", http.StatusBadRequest)
		return
	}

	parts := strings.SplitN(path, "/", 2)
	sandboxID := parts[0]

	if len(parts) == 2 && parts[1] == "exec" {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		h.execCommand(w, r, sandboxID)
		return
	}

	// /v1/sandboxes/{id}
	switch r.Method {
	case http.MethodGet:
		h.getSandbox(w, r, sandboxID)
	case http.MethodDelete:
		h.destroySandbox(w, r, sandboxID)
	default:
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
	}
}

func (h *APIHandler) createSandbox(w http.ResponseWriter, r *http.Request) {
	var req createSandboxRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid request body: " + err.Error()})
		return
	}

	if req.TaskID == "" || req.AgentID == "" || req.Image == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "task_id, agent_id, and image are required"})
		return
	}

	sb, err := h.manager.CreateSandbox(req.TaskID, req.AgentID, req.Image, req.ResourceProfile)
	if err != nil {
		log.Printf("[api] create sandbox error: %v", err)
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
		return
	}

	writeJSON(w, http.StatusCreated, sb)
}

func (h *APIHandler) listSandboxes(w http.ResponseWriter, r *http.Request) {
	agentID := r.URL.Query().Get("agent_id")
	sandboxes, err := h.manager.ListSandboxes(agentID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": err.Error()})
		return
	}
	if sandboxes == nil {
		sandboxes = []*sandbox.Sandbox{}
	}
	writeJSON(w, http.StatusOK, sandboxes)
}

func (h *APIHandler) getSandbox(w http.ResponseWriter, _ *http.Request, id string) {
	sb, err := h.manager.GetSandbox(id)
	if err != nil {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, sb)
}

func (h *APIHandler) destroySandbox(w http.ResponseWriter, _ *http.Request, id string) {
	if err := h.manager.DestroySandbox(id); err != nil {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": err.Error()})
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "destroyed"})
}

func (h *APIHandler) execCommand(w http.ResponseWriter, r *http.Request, sandboxID string) {
	var req execCommandRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid request body: " + err.Error()})
		return
	}

	if req.Command == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "command is required"})
		return
	}

	execReq := sandbox.ExecRequest{
		SandboxID:      sandboxID,
		Command:        req.Command,
		Args:           req.Args,
		Env:            req.Env,
		IdempotencyKey: req.IdempotencyKey,
	}

	result, err := h.manager.Execute(sandboxID, execReq)
	if err != nil {
		status := http.StatusInternalServerError
		if strings.Contains(err.Error(), "not found") {
			status = http.StatusNotFound
		} else if strings.Contains(err.Error(), "not running") {
			status = http.StatusConflict
		}
		writeJSON(w, status, map[string]string{"error": err.Error()})
		return
	}

	writeJSON(w, http.StatusOK, result)
}

func writeJSON(w http.ResponseWriter, status int, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(v); err != nil {
		log.Printf("[api] json encode error: %v", err)
	}
}
