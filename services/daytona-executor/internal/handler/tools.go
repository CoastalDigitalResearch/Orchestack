package handler

import (
	"encoding/json"
	"fmt"
	"log"
	"sync"
	"time"

	"github.com/nats-io/nats.go"

	"github.com/CoastalDigitalResearch/Orchestack/libs/envelope-go/envelope"
	"github.com/CoastalDigitalResearch/Orchestack/services/daytona-executor/internal/sandbox"
)

// ToolHandler subscribes to NATS tool call subjects and executes tools
// inside sandboxes.
type ToolHandler struct {
	manager *sandbox.SandboxManager
	nc      *nats.Conn
	sub     *nats.Subscription

	// idempotency cache: key -> serialized ToolExecResult
	cache   map[string][]byte
	cacheMu sync.RWMutex
}

// NewToolHandler creates a new ToolHandler.
func NewToolHandler(nc *nats.Conn, mgr *sandbox.SandboxManager) *ToolHandler {
	return &ToolHandler{
		manager: mgr,
		nc:      nc,
		cache:   make(map[string][]byte),
	}
}

// Subscribe starts listening on tools.*.call subjects.
// It uses a queue group so multiple executor instances can share the load.
func (h *ToolHandler) Subscribe() error {
	sub, err := h.nc.QueueSubscribe("tools.*.call", "daytona-executors", h.handleMsg)
	if err != nil {
		return fmt.Errorf("subscribe tools.*.call: %w", err)
	}
	h.sub = sub
	log.Printf("[tools] subscribed to tools.*.call")
	return nil
}

// Unsubscribe stops the NATS subscription.
func (h *ToolHandler) Unsubscribe() error {
	if h.sub != nil {
		return h.sub.Unsubscribe()
	}
	return nil
}

// handleMsg processes a single NATS message containing a tool call request
// wrapped in an envelope.
func (h *ToolHandler) handleMsg(msg *nats.Msg) {
	start := time.Now()

	// Parse the envelope
	env, err := envelope.Unmarshal(msg.Data)
	if err != nil {
		log.Printf("[tools] failed to unmarshal envelope: %v", err)
		h.replyError(msg, "invalid envelope: "+err.Error())
		return
	}

	// Parse the tool exec request from the envelope payload
	var req sandbox.ToolExecRequest
	if err := json.Unmarshal(env.Payload, &req); err != nil {
		log.Printf("[tools] failed to unmarshal tool request: %v", err)
		h.replyError(msg, "invalid tool request payload: "+err.Error())
		return
	}

	// Idempotency check
	if req.IdempotencyKey != "" {
		h.cacheMu.RLock()
		if cached, ok := h.cache[req.IdempotencyKey]; ok {
			h.cacheMu.RUnlock()
			log.Printf("[tools] returning cached result for idempotency_key=%s", req.IdempotencyKey)
			if msg.Reply != "" {
				_ = msg.Respond(cached)
			}
			return
		}
		h.cacheMu.RUnlock()
	}

	log.Printf("[tools] executing tool=%s trace=%s", req.ToolID, req.TraceID)

	// Find or create a sandbox for this task.
	// We use the correlation ID from the envelope as the task ID and the
	// actor ID as the agent ID.
	taskID := env.CorrelationID
	if taskID == "" {
		taskID = "unknown"
	}
	agentID := env.Actor.ID
	if agentID == "" {
		agentID = "system"
	}

	sb, err := h.findOrCreateSandbox(taskID, agentID)
	if err != nil {
		log.Printf("[tools] sandbox error: %v", err)
		h.replyError(msg, "sandbox error: "+err.Error())
		return
	}

	// Execute the tool as a command in the sandbox
	execReq := sandbox.ExecRequest{
		SandboxID:      sb.ID,
		Command:        req.ToolID,
		Args:           nil,
		IdempotencyKey: req.IdempotencyKey,
	}

	execResult, err := h.manager.Execute(sb.ID, execReq)
	if err != nil {
		log.Printf("[tools] exec error: %v", err)
		h.replyError(msg, "exec error: "+err.Error())
		return
	}

	// Build tool result
	outputBytes, _ := json.Marshal(map[string]interface{}{
		"stdout":    execResult.Stdout,
		"stderr":    execResult.Stderr,
		"exit_code": execResult.ExitCode,
	})

	result := sandbox.ToolExecResult{
		ToolID:     req.ToolID,
		Output:     json.RawMessage(outputBytes),
		DurationMS: time.Since(start).Milliseconds(),
	}

	respData, err := json.Marshal(result)
	if err != nil {
		log.Printf("[tools] marshal result error: %v", err)
		h.replyError(msg, "marshal error: "+err.Error())
		return
	}

	// Cache the result for idempotency
	if req.IdempotencyKey != "" {
		h.cacheMu.Lock()
		h.cache[req.IdempotencyKey] = respData
		h.cacheMu.Unlock()
	}

	if msg.Reply != "" {
		if err := msg.Respond(respData); err != nil {
			log.Printf("[tools] reply error: %v", err)
		}
	}

	log.Printf("[tools] completed tool=%s duration=%dms", req.ToolID, result.DurationMS)
}

// findOrCreateSandbox looks for a running sandbox for the given task/agent
// pair, or creates one if none exists.
func (h *ToolHandler) findOrCreateSandbox(taskID, agentID string) (*sandbox.Sandbox, error) {
	sandboxes, err := h.manager.ListSandboxes(agentID)
	if err != nil {
		return nil, err
	}

	// Return first running sandbox for this agent
	for _, sb := range sandboxes {
		if sb.TaskID == taskID && sb.Status == sandbox.StatusRunning {
			return sb, nil
		}
	}

	// Create a new one with default profile
	profile := sandbox.ResourceProfile{
		CPUCores:      2,
		MemoryMB:      512,
		DiskGB:        5,
		EgressPolicy:  "restricted",
		MaxConcurrent: 4,
	}

	return h.manager.CreateSandbox(taskID, agentID, "default:latest", profile)
}

// replyError sends an error ToolExecResult on the NATS reply subject.
func (h *ToolHandler) replyError(msg *nats.Msg, errMsg string) {
	if msg.Reply == "" {
		return
	}
	result := sandbox.ToolExecResult{
		Error: errMsg,
	}
	data, _ := json.Marshal(result)
	_ = msg.Respond(data)
}
