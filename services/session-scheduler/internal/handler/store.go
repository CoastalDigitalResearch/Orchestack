package handler

import "context"

type Session struct {
	ID                      string
	TenantID                string
	AgentID                 string
	ConnectorType           string
	ConnectorAccountID      string
	ThreadID                string
	NextIngressSeq          int64
	LastProcessedIngressSeq int64
}

type IngressMessage struct {
	ID         string
	SessionID  string
	IngressSeq int64
	EventID    string
	PayloadRef string
	SenderID   string
	Content    string
}

type Task struct {
	ID               string
	TenantID         string
	SessionID        string
	AgentID          string
	IngressMessageID string
	Status           string
}

// SessionStore defines the persistence interface
type SessionStore interface {
	ResolveSession(ctx context.Context, tenantID, connectorType, accountID, threadID, agentID string) (*Session, error)
	PersistIngress(ctx context.Context, sessionID string, event IngressEvent) (*IngressMessage, error)
	ShouldCreateTask(ctx context.Context, sessionID string) (bool, error)
	CreateTask(ctx context.Context, session *Session, ingress *IngressMessage) (*Task, error)
	GetDefaultAgent(ctx context.Context, tenantID string) (string, error)
}
