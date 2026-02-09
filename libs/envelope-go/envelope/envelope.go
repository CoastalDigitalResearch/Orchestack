package envelope

import (
	"encoding/json"
	"time"
)

// Envelope represents the RFC-001 S5.1 event envelope
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
	Trace          TraceContext    `json:"trace,omitempty"`
	Payload        json.RawMessage `json:"payload,omitempty"`
}

// Actor represents the entity that produced the event
type Actor struct {
	Type string `json:"type"` // "user", "agent", "system", "connector"
	ID   string `json:"id"`
	Name string `json:"name,omitempty"`
}

// TraceContext holds W3C traceparent/tracestate
type TraceContext struct {
	TraceParent string `json:"traceparent,omitempty"`
	TraceState  string `json:"tracestate,omitempty"`
}

// Marshal serializes the envelope to JSON
func (e *Envelope) Marshal() ([]byte, error) {
	return json.Marshal(e)
}

// Unmarshal deserializes JSON into an Envelope
func Unmarshal(data []byte) (*Envelope, error) {
	var e Envelope
	if err := json.Unmarshal(data, &e); err != nil {
		return nil, err
	}
	return &e, nil
}
