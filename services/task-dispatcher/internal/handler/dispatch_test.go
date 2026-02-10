package handler

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/nats-io/nats.go"
	"github.com/nats-io/nats.go/jetstream"
)

// --- mock store -------------------------------------------------------------

type mockTaskStore struct {
	mu     sync.Mutex
	tasks  map[string]*Task
	status map[string]string

	getTaskErr       error
	updateStatusErr  error
	incrementErr     error
	getAgentCfgErr   error
}

func newMockTaskStore() *mockTaskStore {
	return &mockTaskStore{
		tasks:  make(map[string]*Task),
		status: make(map[string]string),
	}
}

func (m *mockTaskStore) addTask(t *Task) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.tasks[t.ID] = t
}

func (m *mockTaskStore) GetTask(id string) (*Task, error) {
	if m.getTaskErr != nil {
		return nil, m.getTaskErr
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	t, ok := m.tasks[id]
	if !ok {
		return nil, fmt.Errorf("task %s not found", id)
	}
	return t, nil
}

func (m *mockTaskStore) UpdateTaskStatus(id string, status string) error {
	if m.updateStatusErr != nil {
		return m.updateStatusErr
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	m.status[id] = status
	return nil
}

func (m *mockTaskStore) IncrementRunAttempt(id string) (int, error) {
	if m.incrementErr != nil {
		return 0, m.incrementErr
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	t := m.tasks[id]
	t.RunAttempt++
	return t.RunAttempt, nil
}

func (m *mockTaskStore) GetAgentConfig(_ string) (*AgentConfig, error) {
	if m.getAgentCfgErr != nil {
		return nil, m.getAgentCfgErr
	}
	return &AgentConfig{}, nil
}

// --- mock JetStream ---------------------------------------------------------

type publishedMsg struct {
	subject string
	data    []byte
}

type mockJetStream struct {
	jetstream.JetStream // embed to satisfy interface; unused methods will panic

	mu        sync.Mutex
	published []publishedMsg
	publishErr error
}

func (m *mockJetStream) Publish(_ context.Context, subject string, data []byte, _ ...jetstream.PublishOpt) (*jetstream.PubAck, error) {
	if m.publishErr != nil {
		return nil, m.publishErr
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	m.published = append(m.published, publishedMsg{subject: subject, data: data})
	return &jetstream.PubAck{Stream: "test"}, nil
}

func (m *mockJetStream) publishedOn(subject string) []publishedMsg {
	m.mu.Lock()
	defer m.mu.Unlock()
	var out []publishedMsg
	for _, p := range m.published {
		if p.subject == subject {
			out = append(out, p)
		}
	}
	return out
}

// --- mock NATS msg ----------------------------------------------------------

type mockMsg struct {
	data   []byte
	acked  bool
	naked  bool
	termed bool
}

func (m *mockMsg) Data() []byte                                { return m.data }
func (m *mockMsg) Subject() string                             { return "tasks.created" }
func (m *mockMsg) Reply() string                               { return "" }
func (m *mockMsg) Ack() error                                  { m.acked = true; return nil }
func (m *mockMsg) Nak() error                                  { m.naked = true; return nil }
func (m *mockMsg) NakWithDelay(_ time.Duration) error          { m.naked = true; return nil }
func (m *mockMsg) Term() error                                 { m.termed = true; return nil }
func (m *mockMsg) TermWithReason(_ string) error               { m.termed = true; return nil }
func (m *mockMsg) InProgress() error                           { return nil }
func (m *mockMsg) Metadata() (*jetstream.MsgMetadata, error)   { return nil, nil }
func (m *mockMsg) Headers() nats.Header                        { return nil }
func (m *mockMsg) DoubleAck(_ context.Context) error           { return nil }

var _ jetstream.Msg = (*mockMsg)(nil)

// --- helpers ----------------------------------------------------------------

func makePolicyServer(allowed bool, reason string) *httptest.Server {
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		resp := policyResponse{Allowed: allowed, Reason: reason}
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(resp)
	}))
}

func makeTaskEvent(taskID string) []byte {
	event := taskCreatedEvent{
		TaskID:    taskID,
		SessionID: "sess-1",
		TenantID:  "tenant-1",
		AgentID:   "agent-1",
	}
	data, _ := json.Marshal(event)
	return data
}

func defaultTask() *Task {
	return &Task{
		ID:         "task-1",
		SessionID:  "sess-1",
		TenantID:   "tenant-1",
		AgentID:    "agent-1",
		Payload:    `{"prompt":"hello"}`,
		Status:     "new",
		RunAttempt: 0,
		MaxRetries: 3,
		CreatedAt:  time.Now(),
		UpdatedAt:  time.Now(),
	}
}

// --- tests ------------------------------------------------------------------

func TestDispatcher_HappyPath(t *testing.T) {
	store := newMockTaskStore()
	store.addTask(defaultTask())

	policySrv := makePolicyServer(true, "")
	defer policySrv.Close()

	js := &mockJetStream{}
	d := &Dispatcher{
		store:              store,
		js:                 js,
		policyEvaluatorURL: policySrv.URL,
		httpClient:         policySrv.Client(),
	}

	msg := &mockMsg{data: makeTaskEvent("task-1")}
	d.HandleMessage(msg)

	if !msg.acked {
		t.Error("expected message to be acked")
	}
	if store.status["task-1"] != "dispatched" {
		t.Errorf("expected task status 'dispatched', got %q", store.status["task-1"])
	}

	dispatched := js.publishedOn("tasks.dispatch")
	if len(dispatched) != 1 {
		t.Fatalf("expected 1 dispatch publish, got %d", len(dispatched))
	}

	var de dispatchEvent
	json.Unmarshal(dispatched[0].data, &de)
	if de.TaskID != "task-1" {
		t.Errorf("dispatch event task_id = %q, want %q", de.TaskID, "task-1")
	}
	if de.RunAttempt != 1 {
		t.Errorf("dispatch event run_attempt = %d, want 1", de.RunAttempt)
	}

	lifecycle := js.publishedOn("tasks.dispatched")
	if len(lifecycle) != 1 {
		t.Errorf("expected 1 tasks.dispatched lifecycle event, got %d", len(lifecycle))
	}
}

func TestDispatcher_InvalidJSON(t *testing.T) {
	store := newMockTaskStore()
	d := &Dispatcher{store: store}

	msg := &mockMsg{data: []byte("not json")}
	d.HandleMessage(msg)

	if !msg.termed {
		t.Error("expected message to be termed on invalid JSON")
	}
}

func TestDispatcher_MissingTaskID(t *testing.T) {
	store := newMockTaskStore()
	d := &Dispatcher{store: store}

	event := taskCreatedEvent{TaskID: ""}
	data, _ := json.Marshal(event)
	msg := &mockMsg{data: data}
	d.HandleMessage(msg)

	if !msg.termed {
		t.Error("expected message to be termed on missing task_id")
	}
}

func TestDispatcher_GetTaskError(t *testing.T) {
	store := newMockTaskStore()
	store.getTaskErr = fmt.Errorf("db down")
	d := &Dispatcher{store: store}

	msg := &mockMsg{data: makeTaskEvent("task-1")}
	d.HandleMessage(msg)

	if !msg.naked {
		t.Error("expected message to be nak'd on store error")
	}
}

func TestDispatcher_MaxRetriesExhausted(t *testing.T) {
	store := newMockTaskStore()
	task := defaultTask()
	task.RunAttempt = 3
	task.MaxRetries = 3
	store.addTask(task)

	js := &mockJetStream{}
	d := &Dispatcher{
		store: store,
		js:    js,
	}

	msg := &mockMsg{data: makeTaskEvent("task-1")}
	d.HandleMessage(msg)

	if !msg.acked {
		t.Error("expected message to be acked when retries exhausted")
	}
	if store.status["task-1"] != "failed" {
		t.Errorf("expected task status 'failed', got %q", store.status["task-1"])
	}

	failed := js.publishedOn("tasks.failed")
	if len(failed) != 1 {
		t.Errorf("expected 1 tasks.failed lifecycle event, got %d", len(failed))
	}
}

func TestDispatcher_IncrementRunAttemptError(t *testing.T) {
	store := newMockTaskStore()
	store.addTask(defaultTask())
	store.incrementErr = fmt.Errorf("db error")
	d := &Dispatcher{store: store}

	msg := &mockMsg{data: makeTaskEvent("task-1")}
	d.HandleMessage(msg)

	if !msg.naked {
		t.Error("expected message to be nak'd on increment error")
	}
}

func TestDispatcher_PolicyEvaluatorError(t *testing.T) {
	store := newMockTaskStore()
	store.addTask(defaultTask())

	// Server that returns 500
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		w.Write([]byte("internal error"))
	}))
	defer srv.Close()

	js := &mockJetStream{}
	d := &Dispatcher{
		store:              store,
		js:                 js,
		policyEvaluatorURL: srv.URL,
		httpClient:         srv.Client(),
	}

	msg := &mockMsg{data: makeTaskEvent("task-1")}
	d.HandleMessage(msg)

	if !msg.naked {
		t.Error("expected message to be nak'd on policy evaluator error")
	}
}

func TestDispatcher_PolicyRejectsTask(t *testing.T) {
	store := newMockTaskStore()
	store.addTask(defaultTask())

	policySrv := makePolicyServer(false, "budget exceeded")
	defer policySrv.Close()

	js := &mockJetStream{}
	d := &Dispatcher{
		store:              store,
		js:                 js,
		policyEvaluatorURL: policySrv.URL,
		httpClient:         policySrv.Client(),
	}

	msg := &mockMsg{data: makeTaskEvent("task-1")}
	d.HandleMessage(msg)

	if !msg.acked {
		t.Error("expected message to be acked after policy rejection")
	}
	if store.status["task-1"] != "rejected" {
		t.Errorf("expected task status 'rejected', got %q", store.status["task-1"])
	}

	rejected := js.publishedOn("tasks.rejected")
	if len(rejected) != 1 {
		t.Fatalf("expected 1 tasks.rejected publish, got %d", len(rejected))
	}

	var re rejectedEvent
	json.Unmarshal(rejected[0].data, &re)
	if re.Reason != "budget exceeded" {
		t.Errorf("rejected reason = %q, want %q", re.Reason, "budget exceeded")
	}
}
