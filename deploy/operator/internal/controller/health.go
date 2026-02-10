package controller

import (
	"context"
	"fmt"
	"strings"

	appsv1 "k8s.io/api/apps/v1"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/log"

	orchestackv1 "github.com/CoastalDigitalResearch/Orchestack/deploy/operator/api/v1alpha1"
)

// HealthResult is the aggregated health state returned by AggregateHealth.
type HealthResult struct {
	// AllReady is true when every tracked service is healthy.
	AllReady bool
	// AnyReady is true when at least one service is healthy.
	AnyReady bool
	// Summary is a human-readable description of the overall health.
	Summary string
	// Services maps service names to their observed status.
	Services map[string]orchestackv1.ServiceStatus
}

// HealthChecker inspects the health of all Orchestack components by querying
// Kubernetes API objects (Deployments, StatefulSets) in the platform namespace.
type HealthChecker struct {
	Client client.Client
}

// NewHealthChecker creates a new HealthChecker.
func NewHealthChecker(c client.Client) *HealthChecker {
	return &HealthChecker{Client: c}
}

// AggregateHealth collects health information for every service defined in the
// platform spec plus known infrastructure components (NATS, Postgres, MinIO).
func (h *HealthChecker) AggregateHealth(ctx context.Context, platform *orchestackv1.OrchestackPlatform) (*HealthResult, error) {
	logger := log.FromContext(ctx)
	ns := platform.Namespace

	result := &HealthResult{
		Services: make(map[string]orchestackv1.ServiceStatus),
	}

	// -- Core services (Deployments) ------------------------------------
	for name := range platform.Spec.Services {
		status, err := h.CheckServiceHealth(ctx, ns, name)
		if err != nil {
			logger.Error(err, "checking service health", "service", name)
			result.Services[name] = orchestackv1.ServiceStatus{
				Ready:   false,
				Message: err.Error(),
			}
			continue
		}
		result.Services[name] = status
	}

	// -- NATS -----------------------------------------------------------
	if platform.Spec.NATS.Enabled {
		status, err := h.CheckNATSHealth(ctx, ns)
		if err != nil {
			logger.Error(err, "checking NATS health")
			result.Services["nats"] = orchestackv1.ServiceStatus{
				Ready:   false,
				Message: err.Error(),
			}
		} else {
			result.Services["nats"] = status
		}
	}

	// -- Postgres -------------------------------------------------------
	if platform.Spec.Postgres.Enabled && platform.Spec.Postgres.ExistingSecret == "" {
		status, err := h.CheckPostgresHealth(ctx, ns)
		if err != nil {
			logger.Error(err, "checking Postgres health")
			result.Services["postgres"] = orchestackv1.ServiceStatus{
				Ready:   false,
				Message: err.Error(),
			}
		} else {
			result.Services["postgres"] = status
		}
	}

	// -- MinIO ----------------------------------------------------------
	if platform.Spec.MinIO.Enabled {
		status, err := h.checkStatefulSetHealth(ctx, ns, "orchestack-minio", "minio")
		if err != nil {
			logger.Error(err, "checking MinIO health")
			result.Services["minio"] = orchestackv1.ServiceStatus{
				Ready:   false,
				Message: err.Error(),
			}
		} else {
			result.Services["minio"] = status
		}
	}

	// -- Aggregate ------------------------------------------------------
	totalCount := len(result.Services)
	readyCount := 0
	var unhealthy []string
	for name, svc := range result.Services {
		if svc.Ready {
			readyCount++
		} else {
			unhealthy = append(unhealthy, name)
		}
	}

	result.AllReady = readyCount == totalCount && totalCount > 0
	result.AnyReady = readyCount > 0
	if result.AllReady {
		result.Summary = fmt.Sprintf("All %d services healthy", totalCount)
	} else {
		result.Summary = fmt.Sprintf("%d/%d services ready; unhealthy: %s",
			readyCount, totalCount, strings.Join(unhealthy, ", "))
	}

	return result, nil
}

// CheckServiceHealth checks the health of a core Orchestack service by
// inspecting its Deployment replicas.
func (h *HealthChecker) CheckServiceHealth(ctx context.Context, namespace, name string) (orchestackv1.ServiceStatus, error) {
	deployName := fmt.Sprintf("orchestack-%s", name)
	return h.checkDeploymentHealth(ctx, namespace, deployName, name)
}

// CheckNATSHealth checks the NATS StatefulSet readiness. In the future this
// could also hit the NATS /healthz HTTP endpoint if monitoring is enabled.
func (h *HealthChecker) CheckNATSHealth(ctx context.Context, namespace string) (orchestackv1.ServiceStatus, error) {
	return h.checkStatefulSetHealth(ctx, namespace, "orchestack-nats", "nats")
}

// CheckPostgresHealth checks the PostgreSQL StatefulSet readiness.
func (h *HealthChecker) CheckPostgresHealth(ctx context.Context, namespace string) (orchestackv1.ServiceStatus, error) {
	return h.checkStatefulSetHealth(ctx, namespace, "orchestack-postgres", "postgres")
}

// checkDeploymentHealth is a helper that reads a Deployment and returns a
// ServiceStatus reflecting its replica readiness.
func (h *HealthChecker) checkDeploymentHealth(ctx context.Context, namespace, deployName, label string) (orchestackv1.ServiceStatus, error) {
	deploy := &appsv1.Deployment{}
	key := client.ObjectKey{Namespace: namespace, Name: deployName}
	if err := h.Client.Get(ctx, key, deploy); err != nil {
		return orchestackv1.ServiceStatus{}, fmt.Errorf("getting Deployment %s: %w", deployName, err)
	}

	desired := int32(1)
	if deploy.Spec.Replicas != nil {
		desired = *deploy.Spec.Replicas
	}

	status := orchestackv1.ServiceStatus{
		Replicas:      deploy.Status.Replicas,
		ReadyReplicas: deploy.Status.ReadyReplicas,
		Ready:         deploy.Status.ReadyReplicas >= desired && desired > 0,
	}

	if status.Ready {
		status.Message = fmt.Sprintf("%s: %d/%d replicas ready", label, status.ReadyReplicas, desired)
	} else {
		status.Message = fmt.Sprintf("%s: %d/%d replicas ready (want %d)", label, status.ReadyReplicas, status.Replicas, desired)
	}
	return status, nil
}

// checkStatefulSetHealth is a helper that reads a StatefulSet and returns a
// ServiceStatus reflecting its replica readiness.
func (h *HealthChecker) checkStatefulSetHealth(ctx context.Context, namespace, stsName, label string) (orchestackv1.ServiceStatus, error) {
	sts := &appsv1.StatefulSet{}
	key := client.ObjectKey{Namespace: namespace, Name: stsName}
	if err := h.Client.Get(ctx, key, sts); err != nil {
		return orchestackv1.ServiceStatus{}, fmt.Errorf("getting StatefulSet %s: %w", stsName, err)
	}

	desired := int32(1)
	if sts.Spec.Replicas != nil {
		desired = *sts.Spec.Replicas
	}

	status := orchestackv1.ServiceStatus{
		Replicas:      sts.Status.Replicas,
		ReadyReplicas: sts.Status.ReadyReplicas,
		Ready:         sts.Status.ReadyReplicas >= desired && desired > 0,
	}

	if status.Ready {
		status.Message = fmt.Sprintf("%s: %d/%d replicas ready", label, status.ReadyReplicas, desired)
	} else {
		status.Message = fmt.Sprintf("%s: %d/%d replicas ready (want %d)", label, status.ReadyReplicas, status.Replicas, desired)
	}
	return status, nil
}
