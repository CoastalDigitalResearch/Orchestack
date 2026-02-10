package store

import (
	"database/sql"
	"fmt"
	"time"

	_ "github.com/lib/pq"

	"github.com/CoastalDigitalResearch/Orchestack/services/task-dispatcher/internal/handler"
)

// PostgresStore implements handler.TaskStore backed by a PostgreSQL database.
type PostgresStore struct {
	db *sql.DB
}

// NewPostgresStore opens a connection to Postgres using the given DSN and
// returns an initialized PostgresStore. The caller should defer store.Close().
func NewPostgresStore(dsn string) (*PostgresStore, error) {
	db, err := sql.Open("postgres", dsn)
	if err != nil {
		return nil, fmt.Errorf("open postgres: %w", err)
	}

	db.SetMaxOpenConns(25)
	db.SetMaxIdleConns(5)
	db.SetConnMaxLifetime(5 * time.Minute)

	if err := db.Ping(); err != nil {
		db.Close()
		return nil, fmt.Errorf("ping postgres: %w", err)
	}

	return &PostgresStore{db: db}, nil
}

// Close closes the underlying database connection pool.
func (s *PostgresStore) Close() error {
	return s.db.Close()
}

// GetTask retrieves a task by its ID from the tasks table.
func (s *PostgresStore) GetTask(id string) (*handler.Task, error) {
	query := `
		SELECT id, session_id, tenant_id, agent_id, payload, status,
		       run_attempt, max_retries, created_at, updated_at
		FROM tasks
		WHERE id = $1
	`

	var t handler.Task
	err := s.db.QueryRow(query, id).Scan(
		&t.ID,
		&t.SessionID,
		&t.TenantID,
		&t.AgentID,
		&t.Payload,
		&t.Status,
		&t.RunAttempt,
		&t.MaxRetries,
		&t.CreatedAt,
		&t.UpdatedAt,
	)
	if err != nil {
		if err == sql.ErrNoRows {
			return nil, fmt.Errorf("task %s not found", id)
		}
		return nil, fmt.Errorf("query task %s: %w", id, err)
	}

	return &t, nil
}

// UpdateTaskStatus sets the status of a task and updates the updated_at timestamp.
func (s *PostgresStore) UpdateTaskStatus(id string, status string) error {
	query := `
		UPDATE tasks
		SET status = $2, updated_at = NOW()
		WHERE id = $1
	`

	result, err := s.db.Exec(query, id, status)
	if err != nil {
		return fmt.Errorf("update task %s status: %w", id, err)
	}

	rows, err := result.RowsAffected()
	if err != nil {
		return fmt.Errorf("check rows affected: %w", err)
	}
	if rows == 0 {
		return fmt.Errorf("task %s not found", id)
	}

	return nil
}

// IncrementRunAttempt atomically increments the run_attempt counter for the
// given task and returns the new value.
func (s *PostgresStore) IncrementRunAttempt(id string) (int, error) {
	query := `
		UPDATE tasks
		SET run_attempt = run_attempt + 1, updated_at = NOW()
		WHERE id = $1
		RETURNING run_attempt
	`

	var attempt int
	err := s.db.QueryRow(query, id).Scan(&attempt)
	if err != nil {
		if err == sql.ErrNoRows {
			return 0, fmt.Errorf("task %s not found", id)
		}
		return 0, fmt.Errorf("increment run attempt for task %s: %w", id, err)
	}

	return attempt, nil
}

// GetAgentConfig retrieves agent configuration by agent ID.
func (s *PostgresStore) GetAgentConfig(agentID string) (*handler.AgentConfig, error) {
	query := `
		SELECT agent_id, tenant_id, model, max_tokens, system_prompt, tools
		FROM agent_configs
		WHERE agent_id = $1
	`

	var cfg handler.AgentConfig
	err := s.db.QueryRow(query, agentID).Scan(
		&cfg.AgentID,
		&cfg.TenantID,
		&cfg.Model,
		&cfg.MaxTokens,
		&cfg.SystemPrompt,
		&cfg.Tools,
	)
	if err != nil {
		if err == sql.ErrNoRows {
			return nil, fmt.Errorf("agent config for %s not found", agentID)
		}
		return nil, fmt.Errorf("query agent config %s: %w", agentID, err)
	}

	return &cfg, nil
}
