// Package v1alpha1 contains API types for the Orchestack platform operator.
package v1alpha1

import (
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

const (
	Group   = "orchestack.io"
	Version = "v1alpha1"

	// Platform lifecycle phases.
	PhasePending   = "Pending"
	PhaseDeploying = "Deploying"
	PhaseRunning   = "Running"
	PhaseDegraded  = "Degraded"
	PhaseFailed    = "Failed"

	// Condition types.
	ConditionReady       = "Ready"
	ConditionProgressing = "Progressing"
	ConditionDegraded    = "Degraded"
)

// OrchestackPlatform is the top-level custom resource that describes a desired
// Orchestack deployment. The operator watches these resources and reconciles
// the cluster state to match the declared specification.
//
// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:printcolumn:name="Phase",type=string,JSONPath=`.status.phase`
// +kubebuilder:printcolumn:name="Version",type=string,JSONPath=`.spec.version`
// +kubebuilder:printcolumn:name="Age",type=date,JSONPath=`.metadata.creationTimestamp`
type OrchestackPlatform struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   OrchestackPlatformSpec   `json:"spec,omitempty"`
	Status OrchestackPlatformStatus `json:"status,omitempty"`
}

// OrchestackPlatformList contains a list of OrchestackPlatform resources.
//
// +kubebuilder:object:root=true
type OrchestackPlatformList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []OrchestackPlatform `json:"items"`
}

// OrchestackPlatformSpec defines the desired state of the platform.
type OrchestackPlatformSpec struct {
	// Version of the Orchestack platform to deploy (e.g. "0.1.0").
	// +kubebuilder:validation:MinLength=1
	Version string `json:"version"`

	// Services describes the core Orchestack micro-services.
	// Keys are service names (task-dispatcher, session-scheduler, etc.).
	// +optional
	Services map[string]ServiceSpec `json:"services,omitempty"`

	// Connectors describes optional external-system connector sidecars.
	// +optional
	Connectors map[string]ConnectorSpec `json:"connectors,omitempty"`

	// NATS configures the NATS message-bus dependency.
	// +optional
	NATS NATSSpec `json:"nats,omitempty"`

	// Postgres configures the PostgreSQL dependency.
	// +optional
	Postgres PostgresSpec `json:"postgres,omitempty"`

	// MinIO configures the S3-compatible object store.
	// +optional
	MinIO MinIOSpec `json:"minio,omitempty"`

	// Vault configures the HashiCorp Vault integration.
	// +optional
	Vault VaultSpec `json:"vault,omitempty"`

	// OpenShift contains settings specific to OpenShift clusters.
	// +optional
	OpenShift OpenShiftSpec `json:"openshift,omitempty"`
}

// ServiceSpec describes a single Orchestack micro-service deployment.
type ServiceSpec struct {
	// Replicas is the desired pod count. Defaults to 1.
	// +kubebuilder:validation:Minimum=0
	// +kubebuilder:default=1
	// +optional
	Replicas *int32 `json:"replicas,omitempty"`

	// Image overrides the default container image for this service.
	// +optional
	Image string `json:"image,omitempty"`

	// Resources sets the CPU/memory requests and limits.
	// +optional
	Resources corev1.ResourceRequirements `json:"resources,omitempty"`
}

// ConnectorSpec describes an optional connector sidecar.
type ConnectorSpec struct {
	// Enabled controls whether the connector is deployed.
	// +kubebuilder:default=false
	// +optional
	Enabled bool `json:"enabled,omitempty"`

	// Replicas is the desired pod count. Defaults to 1.
	// +kubebuilder:validation:Minimum=0
	// +kubebuilder:default=1
	// +optional
	Replicas *int32 `json:"replicas,omitempty"`

	// Image overrides the default container image.
	// +optional
	Image string `json:"image,omitempty"`
}

// NATSSpec configures the NATS message-bus dependency.
type NATSSpec struct {
	// Enabled controls whether the operator manages NATS.
	// +kubebuilder:default=true
	// +optional
	Enabled bool `json:"enabled,omitempty"`

	// JetStream enables JetStream persistence in NATS.
	// +kubebuilder:default=true
	// +optional
	JetStream bool `json:"jetstream,omitempty"`
}

// PostgresSpec configures the PostgreSQL dependency.
type PostgresSpec struct {
	// Enabled controls whether the operator manages PostgreSQL.
	// +kubebuilder:default=true
	// +optional
	Enabled bool `json:"enabled,omitempty"`

	// ExistingSecret references a pre-existing Secret with connection credentials.
	// When set the operator will not create a new PostgreSQL StatefulSet.
	// +optional
	ExistingSecret string `json:"existingSecret,omitempty"`
}

// MinIOSpec configures the S3-compatible object store.
type MinIOSpec struct {
	// Enabled controls whether the operator manages MinIO.
	// +kubebuilder:default=true
	// +optional
	Enabled bool `json:"enabled,omitempty"`

	// Persistence configures the PVC for MinIO data.
	// +optional
	Persistence PersistenceSpec `json:"persistence,omitempty"`
}

// PersistenceSpec describes a volume claim for stateful workloads.
type PersistenceSpec struct {
	// Enabled controls whether a PVC is created.
	// +kubebuilder:default=true
	// +optional
	Enabled bool `json:"enabled,omitempty"`

	// StorageClassName overrides the default storage class.
	// +optional
	StorageClassName string `json:"storageClassName,omitempty"`

	// Size is the requested storage size (e.g. "10Gi").
	// +kubebuilder:default="10Gi"
	// +optional
	Size string `json:"size,omitempty"`
}

// VaultSpec configures the HashiCorp Vault integration.
type VaultSpec struct {
	// Enabled controls whether the operator manages Vault.
	// +kubebuilder:default=false
	// +optional
	Enabled bool `json:"enabled,omitempty"`

	// ExternalAddr points to an existing Vault instance (e.g. "https://vault.example.com").
	// When set the operator will not deploy its own Vault.
	// +optional
	ExternalAddr string `json:"externalAddr,omitempty"`
}

// OpenShiftSpec contains settings specific to OpenShift clusters.
type OpenShiftSpec struct {
	// Enabled signals that the target cluster is OpenShift.
	// +optional
	Enabled bool `json:"enabled,omitempty"`

	// Route controls whether OpenShift Routes are created instead of Ingress.
	// +optional
	Route bool `json:"route,omitempty"`
}

// ---------------------------------------------------------------------------
// Status types
// ---------------------------------------------------------------------------

// OrchestackPlatformStatus describes the observed state of the platform.
type OrchestackPlatformStatus struct {
	// Phase is the high-level lifecycle state.
	// +kubebuilder:validation:Enum=Pending;Deploying;Running;Degraded;Failed
	// +optional
	Phase string `json:"phase,omitempty"`

	// Conditions provide detailed, machine-readable status signals.
	// +optional
	Conditions []metav1.Condition `json:"conditions,omitempty"`

	// Services maps service names to their observed status.
	// +optional
	Services map[string]ServiceStatus `json:"services,omitempty"`

	// ObservedGeneration is the most recent .metadata.generation observed.
	// +optional
	ObservedGeneration int64 `json:"observedGeneration,omitempty"`

	// LastReconciled is the timestamp of the last successful reconciliation.
	// +optional
	LastReconciled metav1.Time `json:"lastReconciled,omitempty"`
}

// ServiceStatus describes the observed state of a single service.
type ServiceStatus struct {
	// Ready indicates whether the service is healthy.
	Ready bool `json:"ready"`

	// Replicas is the total number of pods.
	Replicas int32 `json:"replicas"`

	// ReadyReplicas is the number of pods that are passing readiness checks.
	ReadyReplicas int32 `json:"readyReplicas"`

	// Message is a human-readable description of the current state.
	// +optional
	Message string `json:"message,omitempty"`
}
