package envelope

import (
	"encoding/json"
	"testing"
	"time"
)

func testActor() Actor {
	return Actor{Type: "system", ID: "test-service", Name: "Test"}
}

func TestNew(t *testing.T) {
	env := New("task.created", testActor(), "tenant-1")

	if env.Version != "1.0" {
		t.Errorf("expected version 1.0, got %s", env.Version)
	}
	if env.EventType != "task.created" {
		t.Errorf("expected event_type task.created, got %s", env.EventType)
	}
	if env.TenantID != "tenant-1" {
		t.Errorf("expected tenant_id tenant-1, got %s", env.TenantID)
	}
	if !IsValidULID(env.EventID) {
		t.Errorf("expected valid ULID event_id, got %s", env.EventID)
	}
	if env.Timestamp.IsZero() {
		t.Error("expected non-zero timestamp")
	}
}

func TestJSONRoundtrip(t *testing.T) {
	env := New("ingress.message", testActor(), "tenant-2")
	env.CorrelationID = "corr-123"
	env.Priority = 5
	env.Payload = json.RawMessage(`{"text":"hello"}`)

	data, err := env.Marshal()
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}

	parsed, err := Unmarshal(data)
	if err != nil {
		t.Fatalf("unmarshal: %v", err)
	}

	if parsed.EventID != env.EventID {
		t.Errorf("event_id mismatch: %s != %s", parsed.EventID, env.EventID)
	}
	if parsed.EventType != env.EventType {
		t.Errorf("event_type mismatch: %s != %s", parsed.EventType, env.EventType)
	}
	if parsed.TenantID != env.TenantID {
		t.Errorf("tenant_id mismatch")
	}
	if parsed.CorrelationID != env.CorrelationID {
		t.Errorf("correlation_id mismatch")
	}
	if parsed.Priority != env.Priority {
		t.Errorf("priority mismatch: %d != %d", parsed.Priority, env.Priority)
	}
	if parsed.Actor.Type != env.Actor.Type {
		t.Errorf("actor.type mismatch")
	}
}

func TestValidate_Valid(t *testing.T) {
	env := New("task.created", testActor(), "tenant-1")
	errs := env.Validate()
	if len(errs) > 0 {
		t.Errorf("expected no errors, got: %v", errs)
	}
}

func TestValidate_InvalidActor(t *testing.T) {
	env := New("task.created", Actor{Type: "invalid", ID: "x"}, "tenant-1")
	errs := env.Validate()
	if len(errs) == 0 {
		t.Error("expected validation errors for invalid actor type")
	}
	found := false
	for _, e := range errs {
		if e == "invalid actor type: invalid" {
			found = true
		}
	}
	if !found {
		t.Errorf("expected 'invalid actor type' error, got: %v", errs)
	}
}

func TestValidate_MissingFields(t *testing.T) {
	env := &Envelope{} // all fields empty
	errs := env.Validate()
	if len(errs) < 4 {
		t.Errorf("expected at least 4 errors for empty envelope, got %d: %v", len(errs), errs)
	}
}

func TestValidate_PriorityRange(t *testing.T) {
	env := New("test", testActor(), "t")
	env.Priority = 11
	errs := env.Validate()
	found := false
	for _, e := range errs {
		if e == "priority must be 0-10, got 11" {
			found = true
		}
	}
	if !found {
		t.Errorf("expected priority range error, got: %v", errs)
	}
}

func TestIdempotencyKey(t *testing.T) {
	key := IdempotencyKey("tenant-1", "task-abc", 2, "model_call", 3)
	expected := "idem:tenant-1:task-abc:2:model_call:3"
	if key != expected {
		t.Errorf("expected %q, got %q", expected, key)
	}
}

func TestNewTraceParent(t *testing.T) {
	tp := NewTraceParent()
	traceID, parentID, flags, err := ParseTraceParent(tp)
	if err != nil {
		t.Fatalf("parse error: %v", err)
	}
	if len(traceID) != 32 {
		t.Errorf("expected 32 char trace-id, got %d", len(traceID))
	}
	if len(parentID) != 16 {
		t.Errorf("expected 16 char parent-id, got %d", len(parentID))
	}
	if flags != "01" {
		t.Errorf("expected flags 01, got %s", flags)
	}
}

func TestParseTraceParent_Invalid(t *testing.T) {
	_, _, _, err := ParseTraceParent("invalid")
	if err == nil {
		t.Error("expected error for invalid traceparent")
	}

	_, _, _, err = ParseTraceParent("01-abc-def-00")
	if err == nil {
		t.Error("expected error for unsupported version")
	}
}

func TestULIDUniqueness(t *testing.T) {
	seen := make(map[string]bool, 1000)
	for range 1000 {
		id := NewULID()
		if seen[id] {
			t.Fatalf("duplicate ULID: %s", id)
		}
		seen[id] = true
	}
}

func TestULIDMonotonicity(t *testing.T) {
	// Generate several ULIDs in rapid succession; they should be monotonically increasing.
	prev := ""
	for range 100 {
		id := NewULID()
		if id <= prev {
			t.Errorf("ULID not monotonic: %s <= %s", id, prev)
		}
		prev = id
	}
}

func TestTimestampFormat(t *testing.T) {
	env := New("test", testActor(), "t")
	data, _ := env.Marshal()

	var raw map[string]interface{}
	_ = json.Unmarshal(data, &raw)

	ts, ok := raw["timestamp"].(string)
	if !ok {
		t.Fatal("timestamp not a string in JSON")
	}

	// Should parse as RFC3339.
	_, err := time.Parse(time.RFC3339Nano, ts)
	if err != nil {
		t.Errorf("timestamp not valid RFC3339: %s (%v)", ts, err)
	}
}
