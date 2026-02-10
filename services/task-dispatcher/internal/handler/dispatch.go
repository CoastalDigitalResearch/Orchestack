package handler

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"time"

	"github.com/nats-io/nats.go/jetstream"
)

// Dispatcher handles incoming task.created messages, evaluates policy,
// and publishes dispatch or rejection events.
type Dispatcher struct {
	store              TaskStore
	js                 jetstream.JetStream
	policyEvaluatorURL string
	httpClient         *http.Client
}

// NewDispatcher creates a new Dispatcher with the given dependencies.
func NewDispatcher(store TaskStore, js jetstream.JetStream, policyEvaluatorURL string) *Dispatcher {
	return &Dispatcher{
		store:              store,
		js:                 js,
		policyEvaluatorURL: policyEvaluatorURL,
		httpClient: &http.Client{
			Timeout: 10 * time.Second,
		},
	}
}

// taskCreatedEvent is the payload received from the tasks.created subject.
type taskCreatedEvent struct {
	TaskID    string `json:"task_id"`
	SessionID string `json:"session_id,omitempty"`
	TenantID  string `json:"tenant_id,omitempty"`
	AgentID   string `json:"agent_id,omitempty"`
}

// policyRequest is the request body sent to the policy evaluator.
type policyRequest struct {
	TaskID   string `json:"task_id"`
	TenantID string `json:"tenant_id"`
	AgentID  string `json:"agent_id"`
	Payload  string `json:"payload"`
}

// policyResponse is the response from the policy evaluator.
type policyResponse struct {
	Allowed bool   `json:"allowed"`
	Reason  string `json:"reason,omitempty"`
}

// dispatchEvent is the payload published to tasks.dispatch.
type dispatchEvent struct {
	TaskID     string `json:"task_id"`
	SessionID  string `json:"session_id"`
	TenantID   string `json:"tenant_id"`
	AgentID    string `json:"agent_id"`
	Payload    string `json:"payload"`
	RunAttempt int    `json:"run_attempt"`
}

// rejectedEvent is the payload published to tasks.rejected.
type rejectedEvent struct {
	TaskID   string `json:"task_id"`
	TenantID string `json:"tenant_id"`
	AgentID  string `json:"agent_id"`
	Reason   string `json:"reason"`
}

// HandleMessage processes a single NATS JetStream message from the
// tasks.created subject. It is intended to be used as a jetstream.MessageHandler.
func (d *Dispatcher) HandleMessage(msg jetstream.Msg) {
	ctx := context.Background()

	var event taskCreatedEvent
	if err := json.Unmarshal(msg.Data(), &event); err != nil {
		log.Printf("error: failed to unmarshal task.created event: %v", err)
		// Terminal parse error; do not redeliver.
		if termErr := msg.TermWithReason("invalid message payload"); termErr != nil {
			log.Printf("error: failed to term message: %v", termErr)
		}
		return
	}

	if event.TaskID == "" {
		log.Printf("error: task.created event missing task_id")
		if termErr := msg.TermWithReason("missing task_id"); termErr != nil {
			log.Printf("error: failed to term message: %v", termErr)
		}
		return
	}

	log.Printf("info: processing task %s", event.TaskID)

	// Load the task from the database.
	task, err := d.store.GetTask(event.TaskID)
	if err != nil {
		log.Printf("error: failed to load task %s: %v", event.TaskID, err)
		// Nak so the message is redelivered after backoff.
		if nakErr := msg.Nak(); nakErr != nil {
			log.Printf("error: failed to nak message: %v", nakErr)
		}
		return
	}

	// Check retry budget before doing any work.
	if task.RunAttempt >= task.MaxRetries {
		log.Printf("warn: task %s has exhausted retries (%d/%d), marking failed",
			task.ID, task.RunAttempt, task.MaxRetries)
		if err := d.store.UpdateTaskStatus(task.ID, "failed"); err != nil {
			log.Printf("error: failed to update task status: %v", err)
		}
		d.publishLifecycleEvent(ctx, "tasks.failed", map[string]any{
			"task_id":     task.ID,
			"tenant_id":   task.TenantID,
			"reason":      "max retries exhausted",
			"run_attempt": task.RunAttempt,
		})
		if ackErr := msg.Ack(); ackErr != nil {
			log.Printf("error: failed to ack message: %v", ackErr)
		}
		return
	}

	// Increment the run attempt counter.
	attempt, err := d.store.IncrementRunAttempt(task.ID)
	if err != nil {
		log.Printf("error: failed to increment run attempt for task %s: %v", task.ID, err)
		if nakErr := msg.Nak(); nakErr != nil {
			log.Printf("error: failed to nak message: %v", nakErr)
		}
		return
	}

	// Evaluate policy.
	allowed, reason, err := d.evaluatePolicy(ctx, task)
	if err != nil {
		log.Printf("error: policy evaluation failed for task %s: %v", task.ID, err)
		// Policy evaluator might be temporarily unavailable; nak for retry.
		if nakErr := msg.Nak(); nakErr != nil {
			log.Printf("error: failed to nak message: %v", nakErr)
		}
		return
	}

	if !allowed {
		log.Printf("info: task %s rejected by policy: %s", task.ID, reason)
		if err := d.store.UpdateTaskStatus(task.ID, "rejected"); err != nil {
			log.Printf("error: failed to update task status: %v", err)
		}
		d.publishRejected(ctx, task, reason)
		if ackErr := msg.Ack(); ackErr != nil {
			log.Printf("error: failed to ack message: %v", ackErr)
		}
		return
	}

	// Policy approved -- dispatch the task.
	log.Printf("info: task %s approved, dispatching (attempt %d)", task.ID, attempt)
	if err := d.store.UpdateTaskStatus(task.ID, "dispatched"); err != nil {
		log.Printf("error: failed to update task status: %v", err)
	}

	d.publishDispatch(ctx, task, attempt)

	d.publishLifecycleEvent(ctx, "tasks.dispatched", map[string]any{
		"task_id":     task.ID,
		"session_id":  task.SessionID,
		"tenant_id":   task.TenantID,
		"agent_id":    task.AgentID,
		"run_attempt": attempt,
	})

	if ackErr := msg.Ack(); ackErr != nil {
		log.Printf("error: failed to ack message: %v", ackErr)
	}
}

// evaluatePolicy calls the policy evaluator HTTP service and returns
// whether the task is allowed, an optional reason, and any error.
func (d *Dispatcher) evaluatePolicy(ctx context.Context, task *Task) (bool, string, error) {
	reqBody := policyRequest{
		TaskID:   task.ID,
		TenantID: task.TenantID,
		AgentID:  task.AgentID,
		Payload:  task.Payload,
	}

	body, err := json.Marshal(reqBody)
	if err != nil {
		return false, "", fmt.Errorf("marshal policy request: %w", err)
	}

	url := d.policyEvaluatorURL + "/v1/evaluate"
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return false, "", fmt.Errorf("create policy request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := d.httpClient.Do(req)
	if err != nil {
		return false, "", fmt.Errorf("policy evaluator request: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return false, "", fmt.Errorf("read policy response: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return false, "", fmt.Errorf("policy evaluator returned status %d: %s",
			resp.StatusCode, string(respBody))
	}

	var policyResp policyResponse
	if err := json.Unmarshal(respBody, &policyResp); err != nil {
		return false, "", fmt.Errorf("unmarshal policy response: %w", err)
	}

	return policyResp.Allowed, policyResp.Reason, nil
}

// publishDispatch publishes a dispatch event to tasks.dispatch.
func (d *Dispatcher) publishDispatch(ctx context.Context, task *Task, attempt int) {
	event := dispatchEvent{
		TaskID:     task.ID,
		SessionID:  task.SessionID,
		TenantID:   task.TenantID,
		AgentID:    task.AgentID,
		Payload:    task.Payload,
		RunAttempt: attempt,
	}

	data, err := json.Marshal(event)
	if err != nil {
		log.Printf("error: failed to marshal dispatch event for task %s: %v", task.ID, err)
		return
	}

	if _, err := d.js.Publish(ctx, "tasks.dispatch", data); err != nil {
		log.Printf("error: failed to publish tasks.dispatch for task %s: %v", task.ID, err)
	}
}

// publishRejected publishes a rejected event to tasks.rejected.
func (d *Dispatcher) publishRejected(ctx context.Context, task *Task, reason string) {
	event := rejectedEvent{
		TaskID:   task.ID,
		TenantID: task.TenantID,
		AgentID:  task.AgentID,
		Reason:   reason,
	}

	data, err := json.Marshal(event)
	if err != nil {
		log.Printf("error: failed to marshal rejected event for task %s: %v", task.ID, err)
		return
	}

	if _, err := d.js.Publish(ctx, "tasks.rejected", data); err != nil {
		log.Printf("error: failed to publish tasks.rejected for task %s: %v", task.ID, err)
	}
}

// publishLifecycleEvent publishes a generic lifecycle event on the given subject.
func (d *Dispatcher) publishLifecycleEvent(ctx context.Context, subject string, payload map[string]any) {
	data, err := json.Marshal(payload)
	if err != nil {
		log.Printf("error: failed to marshal lifecycle event on %s: %v", subject, err)
		return
	}

	if _, err := d.js.Publish(ctx, subject, data); err != nil {
		log.Printf("error: failed to publish %s: %v", subject, err)
	}
}
