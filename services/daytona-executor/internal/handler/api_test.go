package handler

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/CoastalDigitalResearch/Orchestack/services/daytona-executor/internal/sandbox"
)

// newTestHandler creates an APIHandler backed by an in-memory sandbox store.
func newTestHandler() (*APIHandler, *http.ServeMux) {
	store := sandbox.NewInMemoryStore()
	mgr := sandbox.NewSandboxManager(store, sandbox.DefaultManagerConfig())
	h := NewAPIHandler(mgr)
	mux := http.NewServeMux()
	h.RegisterRoutes(mux)
	return h, mux
}

func doJSON(t *testing.T, mux http.Handler, method, path string, body interface{}) *httptest.ResponseRecorder {
	t.Helper()
	var buf bytes.Buffer
	if body != nil {
		json.NewEncoder(&buf).Encode(body)
	}
	req := httptest.NewRequest(method, path, &buf)
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()
	mux.ServeHTTP(rr, req)
	return rr
}

// --- tests ------------------------------------------------------------------

func TestCreateSandbox_HappyPath(t *testing.T) {
	_, mux := newTestHandler()

	body := createSandboxRequest{
		TaskID:  "task-1",
		AgentID: "agent-1",
		Image:   "python:3.12",
		ResourceProfile: sandbox.ResourceProfile{
			CPUCores: 2,
			MemoryMB: 512,
		},
	}
	rr := doJSON(t, mux, http.MethodPost, "/v1/sandboxes", body)

	if rr.Code != http.StatusCreated {
		t.Fatalf("expected 201, got %d: %s", rr.Code, rr.Body.String())
	}

	var sb sandbox.Sandbox
	json.NewDecoder(rr.Body).Decode(&sb)
	if sb.ID == "" {
		t.Error("expected sandbox ID to be set")
	}
	if sb.Status != sandbox.StatusRunning {
		t.Errorf("expected status 'running', got %q", sb.Status)
	}
	if sb.TaskID != "task-1" {
		t.Errorf("expected task_id 'task-1', got %q", sb.TaskID)
	}
}

func TestCreateSandbox_MissingFields(t *testing.T) {
	_, mux := newTestHandler()

	body := createSandboxRequest{TaskID: "task-1"} // missing agent_id, image
	rr := doJSON(t, mux, http.MethodPost, "/v1/sandboxes", body)

	if rr.Code != http.StatusBadRequest {
		t.Errorf("expected 400, got %d", rr.Code)
	}
}

func TestCreateSandbox_InvalidJSON(t *testing.T) {
	_, mux := newTestHandler()

	req := httptest.NewRequest(http.MethodPost, "/v1/sandboxes", bytes.NewBufferString("not json"))
	req.Header.Set("Content-Type", "application/json")
	rr := httptest.NewRecorder()
	mux.ServeHTTP(rr, req)

	if rr.Code != http.StatusBadRequest {
		t.Errorf("expected 400, got %d", rr.Code)
	}
}

func TestListSandboxes_Empty(t *testing.T) {
	_, mux := newTestHandler()

	rr := doJSON(t, mux, http.MethodGet, "/v1/sandboxes", nil)

	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rr.Code)
	}

	var sandboxes []sandbox.Sandbox
	json.NewDecoder(rr.Body).Decode(&sandboxes)
	if len(sandboxes) != 0 {
		t.Errorf("expected 0 sandboxes, got %d", len(sandboxes))
	}
}

func TestGetSandbox_NotFound(t *testing.T) {
	_, mux := newTestHandler()

	rr := doJSON(t, mux, http.MethodGet, "/v1/sandboxes/nonexistent", nil)

	if rr.Code != http.StatusNotFound {
		t.Errorf("expected 404, got %d", rr.Code)
	}
}

func TestCreateAndGetSandbox(t *testing.T) {
	_, mux := newTestHandler()

	// Create
	body := createSandboxRequest{
		TaskID:  "task-1",
		AgentID: "agent-1",
		Image:   "python:3.12",
	}
	createRR := doJSON(t, mux, http.MethodPost, "/v1/sandboxes", body)
	if createRR.Code != http.StatusCreated {
		t.Fatalf("create: expected 201, got %d", createRR.Code)
	}

	var created sandbox.Sandbox
	json.NewDecoder(createRR.Body).Decode(&created)

	// Get
	getRR := doJSON(t, mux, http.MethodGet, "/v1/sandboxes/"+created.ID, nil)
	if getRR.Code != http.StatusOK {
		t.Fatalf("get: expected 200, got %d: %s", getRR.Code, getRR.Body.String())
	}

	var fetched sandbox.Sandbox
	json.NewDecoder(getRR.Body).Decode(&fetched)
	if fetched.ID != created.ID {
		t.Errorf("IDs don't match: %s != %s", fetched.ID, created.ID)
	}
}

func TestCreateAndDestroySandbox(t *testing.T) {
	_, mux := newTestHandler()

	// Create
	body := createSandboxRequest{
		TaskID:  "task-1",
		AgentID: "agent-1",
		Image:   "python:3.12",
	}
	createRR := doJSON(t, mux, http.MethodPost, "/v1/sandboxes", body)
	var created sandbox.Sandbox
	json.NewDecoder(createRR.Body).Decode(&created)

	// Destroy
	deleteRR := doJSON(t, mux, http.MethodDelete, "/v1/sandboxes/"+created.ID, nil)
	if deleteRR.Code != http.StatusOK {
		t.Fatalf("delete: expected 200, got %d: %s", deleteRR.Code, deleteRR.Body.String())
	}

	// Verify gone
	getRR := doJSON(t, mux, http.MethodGet, "/v1/sandboxes/"+created.ID, nil)
	if getRR.Code != http.StatusNotFound {
		t.Errorf("get after delete: expected 404, got %d", getRR.Code)
	}
}

func TestExecCommand_HappyPath(t *testing.T) {
	_, mux := newTestHandler()

	// Create sandbox first
	body := createSandboxRequest{
		TaskID:  "task-1",
		AgentID: "agent-1",
		Image:   "python:3.12",
	}
	createRR := doJSON(t, mux, http.MethodPost, "/v1/sandboxes", body)
	var created sandbox.Sandbox
	json.NewDecoder(createRR.Body).Decode(&created)

	// Execute command
	execBody := execCommandRequest{
		Command: "echo",
		Args:    []string{"hello"},
	}
	execRR := doJSON(t, mux, http.MethodPost, "/v1/sandboxes/"+created.ID+"/exec", execBody)

	if execRR.Code != http.StatusOK {
		t.Fatalf("exec: expected 200, got %d: %s", execRR.Code, execRR.Body.String())
	}

	var result sandbox.ExecResult
	json.NewDecoder(execRR.Body).Decode(&result)
	if result.ExitCode != 0 {
		t.Errorf("expected exit code 0, got %d", result.ExitCode)
	}
	if result.Stdout == "" {
		t.Error("expected non-empty stdout")
	}
}

func TestExecCommand_MissingCommand(t *testing.T) {
	_, mux := newTestHandler()

	// Create sandbox first
	body := createSandboxRequest{
		TaskID:  "task-1",
		AgentID: "agent-1",
		Image:   "python:3.12",
	}
	createRR := doJSON(t, mux, http.MethodPost, "/v1/sandboxes", body)
	var created sandbox.Sandbox
	json.NewDecoder(createRR.Body).Decode(&created)

	// Execute with empty command
	execBody := execCommandRequest{Command: ""}
	execRR := doJSON(t, mux, http.MethodPost, "/v1/sandboxes/"+created.ID+"/exec", execBody)

	if execRR.Code != http.StatusBadRequest {
		t.Errorf("expected 400, got %d", execRR.Code)
	}
}

func TestExecCommand_SandboxNotFound(t *testing.T) {
	_, mux := newTestHandler()

	execBody := execCommandRequest{Command: "echo"}
	execRR := doJSON(t, mux, http.MethodPost, "/v1/sandboxes/nonexistent/exec", execBody)

	if execRR.Code != http.StatusNotFound {
		t.Errorf("expected 404, got %d", execRR.Code)
	}
}

func TestExecCommand_Idempotency(t *testing.T) {
	_, mux := newTestHandler()

	// Create sandbox
	body := createSandboxRequest{
		TaskID:  "task-1",
		AgentID: "agent-1",
		Image:   "python:3.12",
	}
	createRR := doJSON(t, mux, http.MethodPost, "/v1/sandboxes", body)
	var created sandbox.Sandbox
	json.NewDecoder(createRR.Body).Decode(&created)

	execBody := execCommandRequest{
		Command:        "echo",
		Args:           []string{"hello"},
		IdempotencyKey: "idem-key-1",
	}

	// First execution
	rr1 := doJSON(t, mux, http.MethodPost, "/v1/sandboxes/"+created.ID+"/exec", execBody)
	if rr1.Code != http.StatusOK {
		t.Fatalf("first exec: expected 200, got %d", rr1.Code)
	}
	var result1 sandbox.ExecResult
	json.NewDecoder(rr1.Body).Decode(&result1)

	// Second execution with same key - should be cached
	rr2 := doJSON(t, mux, http.MethodPost, "/v1/sandboxes/"+created.ID+"/exec", execBody)
	if rr2.Code != http.StatusOK {
		t.Fatalf("second exec: expected 200, got %d", rr2.Code)
	}
	var result2 sandbox.ExecResult
	json.NewDecoder(rr2.Body).Decode(&result2)

	if !result2.Cached {
		t.Error("expected second execution to be cached")
	}
}

func TestSandboxes_MethodNotAllowed(t *testing.T) {
	_, mux := newTestHandler()

	rr := doJSON(t, mux, http.MethodPut, "/v1/sandboxes", nil)
	if rr.Code != http.StatusMethodNotAllowed {
		t.Errorf("expected 405, got %d", rr.Code)
	}
}
