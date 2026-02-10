package sandbox

import (
	"encoding/json"
	"time"
)

// SandboxStatus represents the lifecycle state of a sandbox.
type SandboxStatus string

const (
	StatusCreating SandboxStatus = "creating"
	StatusRunning  SandboxStatus = "running"
	StatusStopping SandboxStatus = "stopping"
	StatusStopped  SandboxStatus = "stopped"
	StatusFailed   SandboxStatus = "failed"
)

// ResourceProfile defines the resource constraints for a sandbox.
type ResourceProfile struct {
	CPUCores      int    `json:"cpu_cores"`
	MemoryMB      int    `json:"memory_mb"`
	DiskGB        int    `json:"disk_gb"`
	EgressPolicy  string `json:"egress_policy"` // "allow", "deny", "restricted"
	MaxConcurrent int    `json:"max_concurrent"`
}

// Sandbox represents a managed sandbox instance.
type Sandbox struct {
	ID              string          `json:"id"`
	TaskID          string          `json:"task_id"`
	AgentID         string          `json:"agent_id"`
	Status          SandboxStatus   `json:"status"`
	Image           string          `json:"image"`
	ResourceProfile ResourceProfile `json:"resource_profile"`
	CreatedAt       time.Time       `json:"created_at"`
	ExpiresAt       time.Time       `json:"expires_at"`
}

// ExecRequest describes a command to run inside a sandbox.
type ExecRequest struct {
	SandboxID      string            `json:"sandbox_id"`
	Command        string            `json:"command"`
	Args           []string          `json:"args,omitempty"`
	Env            map[string]string `json:"env,omitempty"`
	Timeout        time.Duration     `json:"timeout,omitempty"`
	IdempotencyKey string            `json:"idempotency_key,omitempty"`
}

// ExecResult holds the outcome of a command execution.
type ExecResult struct {
	ExitCode   int    `json:"exit_code"`
	Stdout     string `json:"stdout"`
	Stderr     string `json:"stderr"`
	DurationMS int64  `json:"duration_ms"`
	Cached     bool   `json:"cached"`
}

// ToolExecRequest describes a tool invocation routed through NATS.
type ToolExecRequest struct {
	ToolID            string          `json:"tool_id"`
	Input             json.RawMessage `json:"input"`
	IdempotencyKey    string          `json:"idempotency_key,omitempty"`
	CapabilityGrantID string          `json:"capability_grant_id,omitempty"`
	TraceID           string          `json:"trace_id,omitempty"`
}

// ToolExecResult holds the outcome of a tool invocation.
type ToolExecResult struct {
	ToolID     string          `json:"tool_id"`
	Output     json.RawMessage `json:"output,omitempty"`
	Error      string          `json:"error,omitempty"`
	DurationMS int64           `json:"duration_ms"`
}
