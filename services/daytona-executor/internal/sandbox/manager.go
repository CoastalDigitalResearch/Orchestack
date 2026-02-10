package sandbox

import (
	"fmt"
	"log"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"
)

// DefaultSandboxTTL is the default time-to-live for a sandbox before it expires.
const DefaultSandboxTTL = 1 * time.Hour

// ManagerConfig holds configuration for the SandboxManager.
type ManagerConfig struct {
	DefaultTTL      time.Duration
	CleanupInterval time.Duration
}

// DefaultManagerConfig returns a ManagerConfig with sensible defaults.
func DefaultManagerConfig() ManagerConfig {
	return ManagerConfig{
		DefaultTTL:      DefaultSandboxTTL,
		CleanupInterval: 30 * time.Second,
	}
}

// SandboxManager manages the lifecycle of sandboxes.
type SandboxManager struct {
	store  SandboxStore
	config ManagerConfig

	// Idempotency cache for exec requests: key -> *ExecResult
	execCache   map[string]*ExecResult
	execCacheMu sync.RWMutex
}

// NewSandboxManager creates a new SandboxManager.
func NewSandboxManager(store SandboxStore, cfg ManagerConfig) *SandboxManager {
	return &SandboxManager{
		store:     store,
		config:    cfg,
		execCache: make(map[string]*ExecResult),
	}
}

// CreateSandbox provisions a new sandbox and stores it.
func (m *SandboxManager) CreateSandbox(taskID, agentID, image string, profile ResourceProfile) (*Sandbox, error) {
	now := time.Now().UTC()
	sb := &Sandbox{
		ID:              uuid.New().String(),
		TaskID:          taskID,
		AgentID:         agentID,
		Status:          StatusCreating,
		Image:           image,
		ResourceProfile: profile,
		CreatedAt:       now,
		ExpiresAt:       now.Add(m.config.DefaultTTL),
	}

	if err := m.store.Put(sb); err != nil {
		return nil, fmt.Errorf("store sandbox: %w", err)
	}

	// In a real implementation this would call the Daytona API to provision
	// the sandbox. For now we immediately transition to running.
	sb.Status = StatusRunning
	if err := m.store.Put(sb); err != nil {
		return nil, fmt.Errorf("update sandbox status: %w", err)
	}

	log.Printf("[sandbox] created id=%s task=%s agent=%s image=%s", sb.ID, taskID, agentID, image)
	return sb, nil
}

// DestroySandbox tears down a sandbox and removes it from the store.
func (m *SandboxManager) DestroySandbox(sandboxID string) error {
	sb, err := m.store.Get(sandboxID)
	if err != nil {
		return err
	}

	sb.Status = StatusStopping
	_ = m.store.Put(sb)

	// In a real implementation this would call the Daytona API to destroy
	// the sandbox. For now we just remove it from the store.
	sb.Status = StatusStopped
	_ = m.store.Put(sb)

	if err := m.store.Delete(sandboxID); err != nil {
		return fmt.Errorf("delete sandbox: %w", err)
	}

	log.Printf("[sandbox] destroyed id=%s", sandboxID)
	return nil
}

// GetSandbox retrieves a sandbox by ID.
func (m *SandboxManager) GetSandbox(sandboxID string) (*Sandbox, error) {
	return m.store.Get(sandboxID)
}

// ListSandboxes returns all sandboxes for a given agent. If agentID is empty,
// all sandboxes are returned.
func (m *SandboxManager) ListSandboxes(agentID string) ([]*Sandbox, error) {
	if agentID == "" {
		return m.store.ListAll()
	}
	return m.store.ListByAgent(agentID)
}

// Execute runs a command inside a sandbox. If an idempotency key is provided
// and a cached result exists, the cached result is returned.
func (m *SandboxManager) Execute(sandboxID string, req ExecRequest) (*ExecResult, error) {
	// Idempotency check
	if req.IdempotencyKey != "" {
		m.execCacheMu.RLock()
		if cached, ok := m.execCache[req.IdempotencyKey]; ok {
			m.execCacheMu.RUnlock()
			result := *cached
			result.Cached = true
			return &result, nil
		}
		m.execCacheMu.RUnlock()
	}

	sb, err := m.store.Get(sandboxID)
	if err != nil {
		return nil, err
	}
	if sb.Status != StatusRunning {
		return nil, fmt.Errorf("sandbox %q is not running (status=%s)", sandboxID, sb.Status)
	}

	start := time.Now()

	// Simulated execution: in a real implementation this would call into the
	// Daytona workspace API. We simulate a successful echo of the command.
	cmdLine := req.Command
	if len(req.Args) > 0 {
		cmdLine += " " + strings.Join(req.Args, " ")
	}

	result := &ExecResult{
		ExitCode:   0,
		Stdout:     fmt.Sprintf("[simulated] executed: %s", cmdLine),
		Stderr:     "",
		DurationMS: time.Since(start).Milliseconds(),
		Cached:     false,
	}

	// Cache the result
	if req.IdempotencyKey != "" {
		m.execCacheMu.Lock()
		m.execCache[req.IdempotencyKey] = result
		m.execCacheMu.Unlock()
	}

	log.Printf("[sandbox] exec id=%s cmd=%q exit=%d duration=%dms",
		sandboxID, cmdLine, result.ExitCode, result.DurationMS)
	return result, nil
}

// CleanupExpired removes sandboxes that have passed their expiration time.
func (m *SandboxManager) CleanupExpired() {
	all, err := m.store.ListAll()
	if err != nil {
		log.Printf("[sandbox] cleanup error listing: %v", err)
		return
	}

	now := time.Now().UTC()
	for _, sb := range all {
		if now.After(sb.ExpiresAt) {
			log.Printf("[sandbox] cleaning up expired sandbox id=%s (expired %s)", sb.ID, sb.ExpiresAt)
			if err := m.DestroySandbox(sb.ID); err != nil {
				log.Printf("[sandbox] cleanup destroy error id=%s: %v", sb.ID, err)
			}
		}
	}
}
