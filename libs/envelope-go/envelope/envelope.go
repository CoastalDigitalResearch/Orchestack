// Package envelope implements the RFC-001 §5.1 event envelope for Go services.
package envelope

import (
	"crypto/rand"
	"encoding/json"
	"fmt"
	"strings"
	"time"
)

// Envelope represents the RFC-001 §5.1 event envelope.
type Envelope struct {
	Version        string          `json:"version"`
	EventID        string          `json:"event_id"`
	EventType      string          `json:"event_type"`
	Timestamp      time.Time       `json:"timestamp"`
	Actor          Actor           `json:"actor"`
	TenantID       string          `json:"tenant_id"`
	CorrelationID  string          `json:"correlation_id,omitempty"`
	IdempotencyKey string          `json:"idempotency_key,omitempty"`
	Priority       int             `json:"priority,omitempty"`
	PayloadRef     string          `json:"payload_ref,omitempty"`
	Schema         string          `json:"schema,omitempty"`
	Trace          *TraceContext   `json:"trace,omitempty"`
	Payload        json.RawMessage `json:"payload,omitempty"`
}

// Actor represents the entity that produced the event.
type Actor struct {
	Type string `json:"type"` // "user", "agent", "system", "connector"
	ID   string `json:"id"`
	Name string `json:"name,omitempty"`
}

// TraceContext holds W3C traceparent/tracestate headers.
type TraceContext struct {
	TraceParent string `json:"traceparent,omitempty"`
	TraceState  string `json:"tracestate,omitempty"`
}

// New creates a new Envelope with a generated ULID event_id and current timestamp.
func New(eventType string, actor Actor, tenantID string) *Envelope {
	return &Envelope{
		Version:   "1.0",
		EventID:   NewULID(),
		EventType: eventType,
		Timestamp: time.Now().UTC(),
		Actor:     actor,
		TenantID:  tenantID,
	}
}

// Marshal serializes the envelope to JSON.
func (e *Envelope) Marshal() ([]byte, error) {
	return json.Marshal(e)
}

// Unmarshal deserializes JSON into an Envelope.
func Unmarshal(data []byte) (*Envelope, error) {
	var e Envelope
	if err := json.Unmarshal(data, &e); err != nil {
		return nil, err
	}
	return &e, nil
}

// Valid actor types.
var validActorTypes = map[string]bool{
	"user":      true,
	"agent":     true,
	"system":    true,
	"connector": true,
}

// Valid versions.
var validVersions = map[string]bool{
	"1.0": true,
}

// Validate checks the envelope for conformance errors.
// Returns nil if valid, or a slice of error strings.
func (e *Envelope) Validate() []string {
	var errs []string

	if !validVersions[e.Version] {
		errs = append(errs, fmt.Sprintf("invalid version: %s", e.Version))
	}
	if e.EventID == "" {
		errs = append(errs, "event_id is required")
	}
	if e.EventType == "" {
		errs = append(errs, "event_type is required")
	}
	if e.TenantID == "" {
		errs = append(errs, "tenant_id is required")
	}
	if !validActorTypes[e.Actor.Type] {
		errs = append(errs, fmt.Sprintf("invalid actor type: %s", e.Actor.Type))
	}
	if e.Actor.ID == "" {
		errs = append(errs, "actor.id is required")
	}
	if e.Priority < 0 || e.Priority > 10 {
		errs = append(errs, fmt.Sprintf("priority must be 0-10, got %d", e.Priority))
	}

	return errs
}

// IdempotencyKey generates a key in the format:
// idem:{tenant}:{task_id}:{run_attempt}:{step_type}:{step_seq}
func IdempotencyKey(tenantID, taskID string, runAttempt int, stepType string, stepSeq int) string {
	return fmt.Sprintf("idem:%s:%s:%d:%s:%d", tenantID, taskID, runAttempt, stepType, stepSeq)
}

// NewTraceParent generates a new W3C traceparent header value.
// Format: {version}-{trace-id}-{parent-id}-{trace-flags}
func NewTraceParent() string {
	traceID := make([]byte, 16)
	parentID := make([]byte, 8)
	_, _ = rand.Read(traceID)
	_, _ = rand.Read(parentID)
	return fmt.Sprintf("00-%032x-%016x-01", traceID, parentID)
}

// ParseTraceParent parses a W3C traceparent header and returns (traceID, parentID, flags, err).
func ParseTraceParent(tp string) (traceID string, parentID string, flags string, err error) {
	parts := strings.Split(tp, "-")
	if len(parts) != 4 {
		return "", "", "", fmt.Errorf("invalid traceparent: expected 4 parts, got %d", len(parts))
	}
	if parts[0] != "00" {
		return "", "", "", fmt.Errorf("unsupported traceparent version: %s", parts[0])
	}
	return parts[1], parts[2], parts[3], nil
}
