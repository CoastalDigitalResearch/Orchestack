package handler

import (
	"context"
	"encoding/json"
	"log"

	"github.com/nats-io/nats.go/jetstream"
)

// IngressEvent represents a normalized ingress message from a connector
type IngressEvent struct {
	Version   string         `json:"version"`
	EventID   string         `json:"event_id"`
	EventType string         `json:"event_type"`
	TenantID  string         `json:"tenant_id"`
	Actor     Actor          `json:"actor"`
	Payload   IngressPayload `json:"payload"`
}

type Actor struct {
	Type string `json:"type"`
	ID   string `json:"id"`
	Name string `json:"name,omitempty"`
}

type IngressPayload struct {
	MessageID          string `json:"message_id"`
	ConnectorType      string `json:"connector_type"`
	ConnectorAccountID string `json:"connector_account_id"`
	ThreadID           string `json:"thread_id"`
	SenderID           string `json:"sender_id"`
	SenderDisplayName  string `json:"sender_display_name"`
	Content            string `json:"content"`
	PayloadRef         string `json:"payload_ref,omitempty"`
}

// IngressHandler processes incoming ingress events
type IngressHandler struct {
	js    jetstream.JetStream
	store SessionStore
}

func NewIngressHandler(js jetstream.JetStream, store SessionStore) *IngressHandler {
	return &IngressHandler{js: js, store: store}
}

// HandleMessage processes a single NATS message from the ingress stream
func (h *IngressHandler) HandleMessage(msg jetstream.Msg) {
	var event IngressEvent
	if err := json.Unmarshal(msg.Data(), &event); err != nil {
		log.Printf("ERROR: failed to unmarshal ingress event: %v", err)
		msg.Term()
		return
	}

	ctx := context.Background()

	// 1. Resolve or create session
	session, err := h.store.ResolveSession(ctx, event.TenantID, event.Payload.ConnectorType, event.Payload.ConnectorAccountID, event.Payload.ThreadID)
	if err != nil {
		log.Printf("ERROR: failed to resolve session: %v", err)
		msg.Nak()
		return
	}

	// 2. Persist ingress message with sequence number
	ingressMsg, err := h.store.PersistIngress(ctx, session.ID, event)
	if err != nil {
		log.Printf("ERROR: failed to persist ingress: %v", err)
		msg.Nak()
		return
	}

	// 3. Check if we should create a task
	shouldCreate, err := h.store.ShouldCreateTask(ctx, session.ID)
	if err != nil {
		log.Printf("ERROR: failed to check task creation: %v", err)
		msg.Nak()
		return
	}

	if shouldCreate {
		// 4. Create task and publish tasks.create
		task, err := h.store.CreateTask(ctx, session, ingressMsg)
		if err != nil {
			log.Printf("ERROR: failed to create task: %v", err)
			msg.Nak()
			return
		}

		taskEvent, _ := json.Marshal(map[string]interface{}{
			"version":    "1.0",
			"event_type": "tasks.create",
			"tenant_id":  event.TenantID,
			"payload": map[string]interface{}{
				"task_id":            task.ID,
				"session_id":         session.ID,
				"agent_id":           session.AgentID,
				"ingress_message_id": ingressMsg.ID,
			},
		})

		if _, err := h.js.Publish(ctx, "tasks.create", taskEvent); err != nil {
			log.Printf("ERROR: failed to publish tasks.create: %v", err)
			msg.Nak()
			return
		}

		log.Printf("Created task %s for session %s", task.ID, session.ID)
	}

	msg.Ack()
	log.Printf("Processed ingress %s for session %s (seq=%d)", event.EventID, session.ID, ingressMsg.IngressSeq)
}
