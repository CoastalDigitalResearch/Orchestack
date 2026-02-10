// Package v1alpha1 -- hand-written DeepCopy methods for the CRD types.
// In a kubebuilder project these would be generated; we keep things
// lightweight by writing them ourselves.
package v1alpha1

import (
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
)

// ensure the import is used
var _ = metav1.Condition{}

// ---------------------------------------------------------------------------
// OrchestackPlatform
// ---------------------------------------------------------------------------

func (in *OrchestackPlatform) DeepCopyInto(out *OrchestackPlatform) {
	*out = *in
	out.TypeMeta = in.TypeMeta
	in.ObjectMeta.DeepCopyInto(&out.ObjectMeta)
	in.Spec.DeepCopyInto(&out.Spec)
	in.Status.DeepCopyInto(&out.Status)
}

func (in *OrchestackPlatform) DeepCopy() *OrchestackPlatform {
	if in == nil {
		return nil
	}
	out := new(OrchestackPlatform)
	in.DeepCopyInto(out)
	return out
}

func (in *OrchestackPlatform) DeepCopyObject() runtime.Object {
	return in.DeepCopy()
}

// ---------------------------------------------------------------------------
// OrchestackPlatformList
// ---------------------------------------------------------------------------

func (in *OrchestackPlatformList) DeepCopyInto(out *OrchestackPlatformList) {
	*out = *in
	out.TypeMeta = in.TypeMeta
	in.ListMeta.DeepCopyInto(&out.ListMeta)
	if in.Items != nil {
		out.Items = make([]OrchestackPlatform, len(in.Items))
		for i := range in.Items {
			in.Items[i].DeepCopyInto(&out.Items[i])
		}
	}
}

func (in *OrchestackPlatformList) DeepCopy() *OrchestackPlatformList {
	if in == nil {
		return nil
	}
	out := new(OrchestackPlatformList)
	in.DeepCopyInto(out)
	return out
}

func (in *OrchestackPlatformList) DeepCopyObject() runtime.Object {
	return in.DeepCopy()
}

// ---------------------------------------------------------------------------
// Spec types
// ---------------------------------------------------------------------------

func (in *OrchestackPlatformSpec) DeepCopyInto(out *OrchestackPlatformSpec) {
	*out = *in
	if in.Services != nil {
		out.Services = make(map[string]ServiceSpec, len(in.Services))
		for k, v := range in.Services {
			var v2 ServiceSpec
			v.DeepCopyInto(&v2)
			out.Services[k] = v2
		}
	}
	if in.Connectors != nil {
		out.Connectors = make(map[string]ConnectorSpec, len(in.Connectors))
		for k, v := range in.Connectors {
			var v2 ConnectorSpec
			v.DeepCopyInto(&v2)
			out.Connectors[k] = v2
		}
	}
	out.NATS = in.NATS
	out.Postgres = in.Postgres
	out.MinIO = in.MinIO
	out.Vault = in.Vault
	out.OpenShift = in.OpenShift
}

func (in *ServiceSpec) DeepCopyInto(out *ServiceSpec) {
	*out = *in
	if in.Replicas != nil {
		out.Replicas = new(int32)
		*out.Replicas = *in.Replicas
	}
	in.Resources.DeepCopyInto(&out.Resources)
}

func (in *ConnectorSpec) DeepCopyInto(out *ConnectorSpec) {
	*out = *in
	if in.Replicas != nil {
		out.Replicas = new(int32)
		*out.Replicas = *in.Replicas
	}
}

// ---------------------------------------------------------------------------
// Status types
// ---------------------------------------------------------------------------

func (in *OrchestackPlatformStatus) DeepCopyInto(out *OrchestackPlatformStatus) {
	*out = *in
	if in.Conditions != nil {
		out.Conditions = make([]metav1.Condition, len(in.Conditions))
		for i := range in.Conditions {
			in.Conditions[i].DeepCopyInto(&out.Conditions[i])
		}
	}
	if in.Services != nil {
		out.Services = make(map[string]ServiceStatus, len(in.Services))
		for k, v := range in.Services {
			out.Services[k] = v
		}
	}
	in.LastReconciled.DeepCopyInto(&out.LastReconciled)
}
