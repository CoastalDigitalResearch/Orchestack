package store

import (
	"context"
	"database/sql"
	"fmt"

	"github.com/CoastalDigitalResearch/Orchestack/services/session-scheduler/internal/handler"
	"github.com/google/uuid"
)

type PostgresStore struct {
	db *sql.DB
}

func NewPostgresStore(db *sql.DB) *PostgresStore {
	return &PostgresStore{db: db}
}

func (s *PostgresStore) ResolveSession(ctx context.Context, tenantID, connectorType, accountID, threadID string) (*handler.Session, error) {
	var session handler.Session

	// Try to find existing session
	err := s.db.QueryRowContext(ctx,
		`SELECT id, tenant_id, agent_id, connector_type, connector_account_id, thread_id, next_ingress_seq, last_processed_ingress_seq
		 FROM sessions
		 WHERE tenant_id = $1 AND connector_type = $2 AND connector_account_id = $3 AND thread_id = $4`,
		tenantID, connectorType, accountID, threadID,
	).Scan(&session.ID, &session.TenantID, &session.AgentID, &session.ConnectorType, &session.ConnectorAccountID, &session.ThreadID, &session.NextIngressSeq, &session.LastProcessedIngressSeq)

	if err == sql.ErrNoRows {
		// Create new session - resolve agent from connector mapping or use default
		agentID := "agent-default" // TODO: resolve from identity mapping
		sessionID := uuid.New().String()

		_, err = s.db.ExecContext(ctx,
			`INSERT INTO sessions (id, tenant_id, agent_id, connector_type, connector_account_id, thread_id)
			 VALUES ($1, $2, $3, $4, $5, $6)`,
			sessionID, tenantID, agentID, connectorType, accountID, threadID,
		)
		if err != nil {
			return nil, fmt.Errorf("create session: %w", err)
		}

		return &handler.Session{
			ID: sessionID, TenantID: tenantID, AgentID: agentID,
			ConnectorType: connectorType, ConnectorAccountID: accountID, ThreadID: threadID,
			NextIngressSeq: 1, LastProcessedIngressSeq: 0,
		}, nil
	}

	return &session, err
}

func (s *PostgresStore) PersistIngress(ctx context.Context, sessionID string, event handler.IngressEvent) (*handler.IngressMessage, error) {
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, fmt.Errorf("begin tx: %w", err)
	}
	defer tx.Rollback()

	// Atomically increment next_ingress_seq using advisory lock
	var seq int64
	err = tx.QueryRowContext(ctx,
		`UPDATE sessions SET next_ingress_seq = next_ingress_seq + 1, updated_at = now()
		 WHERE id = $1
		 RETURNING next_ingress_seq - 1`, sessionID,
	).Scan(&seq)
	if err != nil {
		return nil, fmt.Errorf("increment seq: %w", err)
	}

	msgID := uuid.New().String()
	contentPreview := event.Payload.Content
	if len(contentPreview) > 200 {
		contentPreview = contentPreview[:200]
	}

	_, err = tx.ExecContext(ctx,
		`INSERT INTO ingress_messages (id, tenant_id, session_id, ingress_seq, event_id, payload_ref, sender_id, content_preview)
		 VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
		msgID, event.TenantID, sessionID, seq, event.EventID, event.Payload.PayloadRef, event.Payload.SenderID, contentPreview,
	)
	if err != nil {
		return nil, fmt.Errorf("insert ingress: %w", err)
	}

	if err = tx.Commit(); err != nil {
		return nil, fmt.Errorf("commit: %w", err)
	}

	return &handler.IngressMessage{
		ID: msgID, SessionID: sessionID, IngressSeq: seq,
		EventID: event.EventID, PayloadRef: event.Payload.PayloadRef,
		SenderID: event.Payload.SenderID, Content: event.Payload.Content,
	}, nil
}

func (s *PostgresStore) ShouldCreateTask(ctx context.Context, sessionID string) (bool, error) {
	// Check: no active task in RUNNING or WAITING_APPROVAL state
	var activeCount int
	err := s.db.QueryRowContext(ctx,
		`SELECT COUNT(*) FROM tasks
		 WHERE session_id = $1 AND status IN ('new', 'queued', 'running', 'waiting_approval')`,
		sessionID,
	).Scan(&activeCount)
	if err != nil {
		return false, err
	}
	return activeCount == 0, nil
}

func (s *PostgresStore) CreateTask(ctx context.Context, session *handler.Session, ingress *handler.IngressMessage) (*handler.Task, error) {
	taskID := uuid.New().String()
	_, err := s.db.ExecContext(ctx,
		`INSERT INTO tasks (id, tenant_id, session_id, agent_id, ingress_message_id, status)
		 VALUES ($1, $2, $3, $4, $5, 'new')`,
		taskID, session.TenantID, session.ID, session.AgentID, ingress.ID,
	)
	if err != nil {
		return nil, fmt.Errorf("create task: %w", err)
	}

	return &handler.Task{
		ID: taskID, TenantID: session.TenantID, SessionID: session.ID,
		AgentID: session.AgentID, IngressMessageID: ingress.ID, Status: "new",
	}, nil
}
