// Package registry provides extension type definitions and persistent storage
// for the Orchestack Extension Controller.
package registry

import (
	"encoding/json"
	"fmt"
	"time"
)

// ---------------------------------------------------------------------------
// Extension types (enum)
// ---------------------------------------------------------------------------

// ExtensionType enumerates the kinds of extensions supported by Orchestack.
type ExtensionType string

const (
	ExtTypeTool      ExtensionType = "tool"
	ExtTypeSkill     ExtensionType = "skill"
	ExtTypeMemory    ExtensionType = "memory"
	ExtTypeStorage   ExtensionType = "storage"
	ExtTypeLoop      ExtensionType = "loop"
	ExtTypeSchedule  ExtensionType = "schedule"
	ExtTypeConnector ExtensionType = "connector"
)

// validExtensionTypes is the authoritative set of recognised types.
var validExtensionTypes = map[ExtensionType]struct{}{
	ExtTypeTool:      {},
	ExtTypeSkill:     {},
	ExtTypeMemory:    {},
	ExtTypeStorage:   {},
	ExtTypeLoop:      {},
	ExtTypeSchedule:  {},
	ExtTypeConnector: {},
}

// Valid returns true when t is one of the recognised extension types.
func (t ExtensionType) Valid() bool {
	_, ok := validExtensionTypes[t]
	return ok
}

// ---------------------------------------------------------------------------
// Extension status (enum)
// ---------------------------------------------------------------------------

// ExtensionStatus tracks the lifecycle state of an extension.
type ExtensionStatus string

const (
	StatusPending    ExtensionStatus = "pending"
	StatusInstalling ExtensionStatus = "installing"
	StatusActive     ExtensionStatus = "active"
	StatusFailed     ExtensionStatus = "failed"
	StatusDisabled   ExtensionStatus = "disabled"
	StatusRemoving   ExtensionStatus = "removing"
)

// validStatuses is the authoritative set of recognised statuses.
var validStatuses = map[ExtensionStatus]struct{}{
	StatusPending:    {},
	StatusInstalling: {},
	StatusActive:     {},
	StatusFailed:     {},
	StatusDisabled:   {},
	StatusRemoving:   {},
}

// Valid returns true when s is one of the recognised statuses.
func (s ExtensionStatus) Valid() bool {
	_, ok := validStatuses[s]
	return ok
}

// ---------------------------------------------------------------------------
// Extension — the core domain object
// ---------------------------------------------------------------------------

// Extension represents a registered Orchestack extension.
type Extension struct {
	ID           string          `json:"id"`
	Name         string          `json:"name"`
	Version      string          `json:"version"`
	Type         ExtensionType   `json:"type"`
	TrustTier    string          `json:"trust_tier"`
	Digest       string          `json:"digest"`
	Status       ExtensionStatus `json:"status"`
	ManifestPath string          `json:"manifest_path"`
	CreatedAt    time.Time       `json:"created_at"`
	UpdatedAt    time.Time       `json:"updated_at"`
}

// Validate performs basic integrity checks on the extension fields.
func (e *Extension) Validate() error {
	if e.ID == "" {
		return fmt.Errorf("extension id must not be empty")
	}
	if e.Name == "" {
		return fmt.Errorf("extension name must not be empty")
	}
	if e.Version == "" {
		return fmt.Errorf("extension version must not be empty")
	}
	if !e.Type.Valid() {
		return fmt.Errorf("invalid extension type: %s", e.Type)
	}
	if !e.Status.Valid() {
		return fmt.Errorf("invalid extension status: %s", e.Status)
	}
	return nil
}

// ---------------------------------------------------------------------------
// ToolDescriptor — schema for tool-type extensions
// ---------------------------------------------------------------------------

// ToolDescriptor describes a single tool exposed by a tool-type extension.
type ToolDescriptor struct {
	ToolID       string          `json:"tool_id"`
	Name         string          `json:"name"`
	Description  string          `json:"description"`
	InputSchema  json.RawMessage `json:"input_schema,omitempty"`
	OutputSchema json.RawMessage `json:"output_schema,omitempty"`
	RiskClass    string          `json:"risk_class"` // e.g. "low", "medium", "high", "critical"
}

// ---------------------------------------------------------------------------
// SkillSpec — declarative skill pipeline definition
// ---------------------------------------------------------------------------

// SkillStep is a single step in a skill pipeline.
type SkillStep struct {
	Name    string            `json:"name" yaml:"name"`
	ToolRef string            `json:"tool_ref" yaml:"tool_ref"`
	Params  map[string]string `json:"params,omitempty" yaml:"params,omitempty"`
}

// SkillGuardrail is a constraint applied to a skill execution.
type SkillGuardrail struct {
	Type  string `json:"type" yaml:"type"`
	Value string `json:"value" yaml:"value"`
}

// SkillSpec defines the declarative specification for a skill-type extension.
type SkillSpec struct {
	Steps      []SkillStep       `json:"steps" yaml:"steps"`
	Parameters map[string]string `json:"parameters,omitempty" yaml:"parameters,omitempty"`
	Guardrails []SkillGuardrail  `json:"guardrails,omitempty" yaml:"guardrails,omitempty"`
}
