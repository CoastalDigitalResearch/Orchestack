package sandbox

import (
	"fmt"
	"sync"
)

// SandboxStore defines the persistence interface for sandbox records.
type SandboxStore interface {
	Put(s *Sandbox) error
	Get(id string) (*Sandbox, error)
	Delete(id string) error
	ListByAgent(agentID string) ([]*Sandbox, error)
	ListAll() ([]*Sandbox, error)
}

// InMemorySandboxStore is a concurrency-safe in-memory implementation of SandboxStore.
type InMemorySandboxStore struct {
	mu   sync.RWMutex
	data map[string]*Sandbox
}

// NewInMemoryStore creates a new InMemorySandboxStore.
func NewInMemoryStore() *InMemorySandboxStore {
	return &InMemorySandboxStore{
		data: make(map[string]*Sandbox),
	}
}

func (s *InMemorySandboxStore) Put(sb *Sandbox) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.data[sb.ID] = sb
	return nil
}

func (s *InMemorySandboxStore) Get(id string) (*Sandbox, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	sb, ok := s.data[id]
	if !ok {
		return nil, fmt.Errorf("sandbox %q not found", id)
	}
	return sb, nil
}

func (s *InMemorySandboxStore) Delete(id string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.data[id]; !ok {
		return fmt.Errorf("sandbox %q not found", id)
	}
	delete(s.data, id)
	return nil
}

func (s *InMemorySandboxStore) ListByAgent(agentID string) ([]*Sandbox, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	var result []*Sandbox
	for _, sb := range s.data {
		if sb.AgentID == agentID {
			result = append(result, sb)
		}
	}
	return result, nil
}

func (s *InMemorySandboxStore) ListAll() ([]*Sandbox, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	result := make([]*Sandbox, 0, len(s.data))
	for _, sb := range s.data {
		result = append(result, sb)
	}
	return result, nil
}
