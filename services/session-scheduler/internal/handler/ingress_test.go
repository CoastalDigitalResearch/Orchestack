package handler

import (
	"context"
	"encoding/json"
	"errors"
	"sync"
	"testing"
	"time"

	"github.com/nats-io/nats.go"
	"github.com/nats-io/nats.go/jetstream"
)

// --- mock store ---------------------------------------------------------

type mockSessionStore struct {
	mu       sync.Mutex
	sessions map[string]*Session
	messages []*IngressMessage
	tasks    []*Task

	resolveErr      error
	persistErr      error
	shouldCreateOk  bool
	shouldCreateErr error
	createTaskErr   error
}

func newMockStore() *mockSessionStore {
	return &mockSessionStore{
		sessions:       make(map[string]*Session),
		shouldCreateOk: true,
	}
}

func (m *mockSessionStore) GetDefaultAgent(_ context.Context, _ string) (string, error) {
	return "00000000-0000-0000-0000-00000000a001", nil
}

func (m *mockSessionStore) ResolveSession(_ context.Context, tenantID, connectorType, accountID, threadID, agentID string) (*Session, error) {
	if m.resolveErr != nil {
		return nil, m.resolveErr
	}
	m.mu.Lock()
	defer m.mu.Unlock()

	key := tenantID + ":" + connectorType + ":" + accountID + ":" + threadID
	if s, ok := m.sessions[key]; ok {
		return s, nil
	}
	if agentID == "" {
		agentID = "00000000-0000-0000-0000-00000000a001"
	}
	s := &Session{
		ID:                 "sess-" + threadID,
		TenantID:           tenantID,
		AgentID:            agentID,
		ConnectorType:      connectorType,
		ConnectorAccountID: accountID,
		ThreadID:           threadID,
		NextIngressSeq:     1,
	}
	m.sessions[key] = s
	return s, nil
}

func (m *mockSessionStore) PersistIngress(_ context.Context, sessionID string, event IngressEvent) (*IngressMessage, error) {
	if m.persistErr != nil {
		return nil, m.persistErr
	}
	m.mu.Lock()
	defer m.mu.Unlock()

	seq := int64(len(m.messages) + 1)
	msg := &IngressMessage{
		ID:         "im-" + event.EventID,
		SessionID:  sessionID,
		IngressSeq: seq,
		EventID:    event.EventID,
		SenderID:   event.Payload.SenderID,
		Content:    event.Payload.Content,
	}
	m.messages = append(m.messages, msg)
	return msg, nil
}

func (m *mockSessionStore) ShouldCreateTask(_ context.Context, _ string) (bool, error) {
	return m.shouldCreateOk, m.shouldCreateErr
}

func (m *mockSessionStore) CreateTask(_ context.Context, session *Session, ingress *IngressMessage) (*Task, error) {
	if m.createTaskErr != nil {
		return nil, m.createTaskErr
	}
	m.mu.Lock()
	defer m.mu.Unlock()

	t := &Task{
		ID:               "task-" + ingress.ID,
		TenantID:         session.TenantID,
		SessionID:        session.ID,
		AgentID:          session.AgentID,
		IngressMessageID: ingress.ID,
		Status:           "NEW",
	}
	m.tasks = append(m.tasks, t)
	return t, nil
}

// --- mock NATS msg ------------------------------------------------------

type mockMsg struct {
	data   []byte
	acked  bool
	naked  bool
	termed bool
}

func (m *mockMsg) Data() []byte                                { return m.data }
func (m *mockMsg) Subject() string                             { return "ingress.test.message" }
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

// Compile-time check that mockMsg satisfies jetstream.Msg.
var _ jetstream.Msg = (*mockMsg)(nil)

// --- tests --------------------------------------------------------------

func makeEvent(eventID, content string) IngressEvent {
	return IngressEvent{
		Version:   "1.0",
		EventID:   eventID,
		EventType: "ingress.discord.message",
		TenantID:  "tenant-1",
		Actor:     Actor{Type: "connector", ID: "discord-bot"},
		Payload: IngressPayload{
			MessageID:          "msg-123",
			ConnectorType:      "discord",
			ConnectorAccountID: "bot-1",
			ThreadID:           "thread-abc",
			SenderID:           "user-42",
			SenderDisplayName:  "Alice",
			Content:            content,
		},
	}
}

func TestHandleMessage_HappyPath(t *testing.T) {
	store := newMockStore()
	handler := &IngressHandler{js: nil, store: store}

	event := makeEvent("evt-1", "Hello world")
	data, _ := json.Marshal(event)
	msg := &mockMsg{data: data}

	// When js is nil the publish will panic; skip that path by disabling task creation.
	store.shouldCreateOk = false
	handler.HandleMessage(msg)

	if !msg.acked {
		t.Error("expected message to be acked")
	}
	if len(store.messages) != 1 {
		t.Fatalf("expected 1 ingress message, got %d", len(store.messages))
	}
	if store.messages[0].Content != "Hello world" {
		t.Errorf("unexpected content: %s", store.messages[0].Content)
	}
}

func TestHandleMessage_InvalidJSON(t *testing.T) {
	store := newMockStore()
	handler := &IngressHandler{js: nil, store: store}

	msg := &mockMsg{data: []byte("not json")}
	handler.HandleMessage(msg)

	if !msg.termed {
		t.Error("expected message to be termed on invalid JSON")
	}
}

func TestHandleMessage_ResolveSessionError(t *testing.T) {
	store := newMockStore()
	store.resolveErr = errors.New("db down")
	handler := &IngressHandler{js: nil, store: store}

	event := makeEvent("evt-2", "test")
	data, _ := json.Marshal(event)
	msg := &mockMsg{data: data}
	handler.HandleMessage(msg)

	if !msg.naked {
		t.Error("expected message to be nak'd on store error")
	}
}

func TestHandleMessage_PersistIngressError(t *testing.T) {
	store := newMockStore()
	store.persistErr = errors.New("write failed")
	handler := &IngressHandler{js: nil, store: store}

	event := makeEvent("evt-3", "test")
	data, _ := json.Marshal(event)
	msg := &mockMsg{data: data}
	handler.HandleMessage(msg)

	if !msg.naked {
		t.Error("expected message to be nak'd on persist error")
	}
}

func TestHandleMessage_ShouldCreateTaskError(t *testing.T) {
	store := newMockStore()
	store.shouldCreateErr = errors.New("check failed")
	handler := &IngressHandler{js: nil, store: store}

	event := makeEvent("evt-4", "test")
	data, _ := json.Marshal(event)
	msg := &mockMsg{data: data}
	handler.HandleMessage(msg)

	if !msg.naked {
		t.Error("expected message to be nak'd on shouldCreateTask error")
	}
}
