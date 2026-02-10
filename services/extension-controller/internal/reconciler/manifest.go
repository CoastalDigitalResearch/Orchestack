// Package reconciler implements the GitOps reconciliation loop for extensions.
package reconciler

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/CoastalDigitalResearch/Orchestack/services/extension-controller/internal/registry"
	"gopkg.in/yaml.v3"
)

// ---------------------------------------------------------------------------
// ExtensionManifest — on-disk representation (extension.yaml)
// ---------------------------------------------------------------------------

// ExtensionManifest is the parsed form of an extension.yaml file that lives
// inside the GitOps config repo under extensions/<name>/extension.yaml.
type ExtensionManifest struct {
	APIVersion string `yaml:"apiVersion" json:"apiVersion"`
	Kind       string `yaml:"kind" json:"kind"`

	Metadata ManifestMetadata `yaml:"metadata" json:"metadata"`
	Spec     ManifestSpec     `yaml:"spec" json:"spec"`
}

// ManifestMetadata holds the identity fields.
type ManifestMetadata struct {
	Name    string            `yaml:"name" json:"name"`
	Version string            `yaml:"version" json:"version"`
	Labels  map[string]string `yaml:"labels,omitempty" json:"labels,omitempty"`
}

// ManifestSpec holds the extension configuration.
type ManifestSpec struct {
	Type      registry.ExtensionType `yaml:"type" json:"type"`
	TrustTier string                 `yaml:"trustTier" json:"trustTier"`
	Digest    string                 `yaml:"digest,omitempty" json:"digest,omitempty"`
	Image     string                 `yaml:"image,omitempty" json:"image,omitempty"`
	Enabled   *bool                  `yaml:"enabled,omitempty" json:"enabled,omitempty"`

	// Tool-type extensions declare their tools here.
	Tools []ManifestTool `yaml:"tools,omitempty" json:"tools,omitempty"`

	// Skill-type extensions declare their pipeline here.
	Skill *registry.SkillSpec `yaml:"skill,omitempty" json:"skill,omitempty"`

	// Arbitrary extension-specific config blob.
	Config map[string]interface{} `yaml:"config,omitempty" json:"config,omitempty"`
}

// ManifestTool is the on-disk representation of a tool descriptor.
type ManifestTool struct {
	ToolID       string          `yaml:"toolId" json:"toolId"`
	Name         string          `yaml:"name" json:"name"`
	Description  string          `yaml:"description" json:"description"`
	InputSchema  json.RawMessage `yaml:"inputSchema,omitempty" json:"inputSchema,omitempty"`
	OutputSchema json.RawMessage `yaml:"outputSchema,omitempty" json:"outputSchema,omitempty"`
	RiskClass    string          `yaml:"riskClass" json:"riskClass"`
}

// ---------------------------------------------------------------------------
// Parsing
// ---------------------------------------------------------------------------

// ParseManifest reads and parses an extension.yaml file.
func ParseManifest(path string) (*ExtensionManifest, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read manifest %s: %w", path, err)
	}

	var m ExtensionManifest
	if err := yaml.Unmarshal(data, &m); err != nil {
		return nil, fmt.Errorf("parse manifest %s: %w", path, err)
	}
	return &m, nil
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

// ValidateManifest checks the manifest for structural correctness and returns
// a slice of all problems found (empty slice = valid).
func ValidateManifest(m *ExtensionManifest) []error {
	var errs []error

	if m.APIVersion == "" {
		errs = append(errs, fmt.Errorf("apiVersion is required"))
	}
	if m.Kind == "" {
		errs = append(errs, fmt.Errorf("kind is required"))
	} else if m.Kind != "Extension" {
		errs = append(errs, fmt.Errorf("kind must be 'Extension', got %q", m.Kind))
	}
	if m.Metadata.Name == "" {
		errs = append(errs, fmt.Errorf("metadata.name is required"))
	}
	if m.Metadata.Version == "" {
		errs = append(errs, fmt.Errorf("metadata.version is required"))
	}
	if !m.Spec.Type.Valid() {
		errs = append(errs, fmt.Errorf("spec.type %q is not a valid extension type", m.Spec.Type))
	}
	if m.Spec.TrustTier == "" {
		errs = append(errs, fmt.Errorf("spec.trustTier is required"))
	}

	// Tool-specific: each tool must have at minimum a toolId and name.
	if m.Spec.Type == registry.ExtTypeTool {
		if len(m.Spec.Tools) == 0 {
			errs = append(errs, fmt.Errorf("tool-type extension must declare at least one tool"))
		}
		for i, t := range m.Spec.Tools {
			if t.ToolID == "" {
				errs = append(errs, fmt.Errorf("tools[%d].toolId is required", i))
			}
			if t.Name == "" {
				errs = append(errs, fmt.Errorf("tools[%d].name is required", i))
			}
		}
	}

	// Skill-specific: must have at least one step.
	if m.Spec.Type == registry.ExtTypeSkill {
		if m.Spec.Skill == nil || len(m.Spec.Skill.Steps) == 0 {
			errs = append(errs, fmt.Errorf("skill-type extension must declare at least one step"))
		}
	}

	return errs
}

// IsEnabled returns whether the manifest declares the extension as enabled.
// Defaults to true when the field is omitted.
func (m *ExtensionManifest) IsEnabled() bool {
	if m.Spec.Enabled == nil {
		return true
	}
	return *m.Spec.Enabled
}
