package handler

import "time"

// Task represents a task record in the database.
type Task struct {
	ID         string
	SessionID  string
	TenantID   string
	AgentID    string
	Payload    string
	Status     string
	RunAttempt int
	MaxRetries int
	CreatedAt  time.Time
	UpdatedAt  time.Time
}

// AgentConfig holds the configuration for an agent associated with a task.
type AgentConfig struct {
	AgentID     string
	TenantID    string
	Model       string
	MaxTokens   int
	SystemPrompt string
	Tools       string // JSON-encoded tool list
}

// TaskStore defines the interface for task persistence operations.
type TaskStore interface {
	// GetTask retrieves a task by its ID.
	GetTask(id string) (*Task, error)

	// UpdateTaskStatus sets the status of a task (e.g. "dispatched", "rejected", "failed").
	UpdateTaskStatus(id string, status string) error

	// IncrementRunAttempt increments the run attempt counter for a task
	// and returns the new attempt number.
	IncrementRunAttempt(id string) (int, error)

	// GetAgentConfig retrieves the agent configuration for a given agent ID.
	GetAgentConfig(agentID string) (*AgentConfig, error)
}
