// Package controller implements the Orchestack platform reconciler.
//
// The reconciler watches OrchestackPlatform custom resources and drives the
// cluster toward the declared state by templating and applying the Orchestack
// Helm chart, then updating the CR status based on observed health.
package controller

import (
	"context"
	"fmt"
	"time"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/log"

	orchestackv1 "github.com/CoastalDigitalResearch/Orchestack/deploy/operator/api/v1alpha1"
)

const (
	// finalizerName is attached to OrchestackPlatform resources so the
	// operator can clean up Helm releases on deletion.
	finalizerName = "orchestack.io/platform-finalizer"

	// requeueInterval is the default period between reconciliations when
	// the platform is already running and healthy.
	requeueInterval = 30 * time.Second

	// helmReleaseName is the Helm release name used for the Orchestack chart.
	helmReleaseName = "orchestack"

	// helmChartPath is the default path to the Orchestack Helm chart.
	// This is overridable at startup via the ORCHESTACK_CHART_PATH env var.
	helmChartPath = "/charts/orchestack"
)

// OrchestackReconciler reconciles OrchestackPlatform resources.
type OrchestackReconciler struct {
	client.Client
	Scheme  *runtime.Scheme
	Health  *HealthChecker
}

// SetupWithManager registers the reconciler with the controller-runtime manager.
func (r *OrchestackReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&orchestackv1.OrchestackPlatform{}).
		Owns(&appsv1.Deployment{}).
		Owns(&appsv1.StatefulSet{}).
		Owns(&corev1.Service{}).
		Complete(r)
}

// Reconcile is the main reconciliation loop. It is called by
// controller-runtime whenever an OrchestackPlatform resource or any of its
// owned resources changes.
func (r *OrchestackReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	logger := log.FromContext(ctx)

	// ---------------------------------------------------------------
	// 1. Fetch the OrchestackPlatform CR.
	// ---------------------------------------------------------------
	platform := &orchestackv1.OrchestackPlatform{}
	if err := r.Get(ctx, req.NamespacedName, platform); err != nil {
		if apierrors.IsNotFound(err) {
			logger.Info("OrchestackPlatform resource not found; likely deleted")
			return ctrl.Result{}, nil
		}
		return ctrl.Result{}, fmt.Errorf("fetching OrchestackPlatform: %w", err)
	}

	// ---------------------------------------------------------------
	// 2. Handle deletion via finalizer.
	// ---------------------------------------------------------------
	if !platform.DeletionTimestamp.IsZero() {
		return r.reconcileDelete(ctx, platform)
	}

	// Ensure the finalizer is present.
	if !controllerutil.ContainsFinalizer(platform, finalizerName) {
		controllerutil.AddFinalizer(platform, finalizerName)
		if err := r.Update(ctx, platform); err != nil {
			return ctrl.Result{}, fmt.Errorf("adding finalizer: %w", err)
		}
	}

	// ---------------------------------------------------------------
	// 3. Reconcile the Helm release.
	// ---------------------------------------------------------------
	if err := r.reconcileHelmRelease(ctx, platform); err != nil {
		r.setCondition(platform, orchestackv1.ConditionReady, metav1.ConditionFalse, "HelmFailed", err.Error())
		platform.Status.Phase = orchestackv1.PhaseFailed
		_ = r.statusUpdate(ctx, platform)
		return ctrl.Result{RequeueAfter: requeueInterval}, fmt.Errorf("reconciling Helm release: %w", err)
	}

	// ---------------------------------------------------------------
	// 4. Check health of deployed services and infrastructure.
	// ---------------------------------------------------------------
	health, err := r.Health.AggregateHealth(ctx, platform)
	if err != nil {
		logger.Error(err, "health check failed")
		r.setCondition(platform, orchestackv1.ConditionDegraded, metav1.ConditionTrue, "HealthCheckError", err.Error())
		platform.Status.Phase = orchestackv1.PhaseDegraded
		_ = r.statusUpdate(ctx, platform)
		return ctrl.Result{RequeueAfter: requeueInterval}, nil
	}

	// ---------------------------------------------------------------
	// 5. Update status from health results.
	// ---------------------------------------------------------------
	platform.Status.Services = health.Services
	platform.Status.ObservedGeneration = platform.Generation
	platform.Status.LastReconciled = metav1.Now()

	switch {
	case health.AllReady:
		platform.Status.Phase = orchestackv1.PhaseRunning
		r.setCondition(platform, orchestackv1.ConditionReady, metav1.ConditionTrue, "AllServicesReady", "All services are healthy")
		r.setCondition(platform, orchestackv1.ConditionDegraded, metav1.ConditionFalse, "AllServicesReady", "No degradation detected")
		r.setCondition(platform, orchestackv1.ConditionProgressing, metav1.ConditionFalse, "Reconciled", "Reconciliation complete")
	case health.AnyReady:
		platform.Status.Phase = orchestackv1.PhaseDegraded
		r.setCondition(platform, orchestackv1.ConditionReady, metav1.ConditionFalse, "SomeServicesUnready", health.Summary)
		r.setCondition(platform, orchestackv1.ConditionDegraded, metav1.ConditionTrue, "SomeServicesUnready", health.Summary)
	default:
		platform.Status.Phase = orchestackv1.PhaseDeploying
		r.setCondition(platform, orchestackv1.ConditionReady, metav1.ConditionFalse, "NoServicesReady", health.Summary)
		r.setCondition(platform, orchestackv1.ConditionProgressing, metav1.ConditionTrue, "Deploying", "Waiting for services to become ready")
	}

	if err := r.statusUpdate(ctx, platform); err != nil {
		return ctrl.Result{}, fmt.Errorf("updating status: %w", err)
	}

	logger.Info("reconciliation complete", "phase", platform.Status.Phase)
	return ctrl.Result{RequeueAfter: requeueInterval}, nil
}

// reconcileHelmRelease ensures the Orchestack Helm chart is installed or
// upgraded with values derived from the OrchestackPlatform spec.
//
// NOTE: In the initial implementation this is a stub that logs the intended
// action. A full implementation would use the Helm SDK
// (helm.sh/helm/v3/pkg/action) to install/upgrade the release.
func (r *OrchestackReconciler) reconcileHelmRelease(ctx context.Context, platform *orchestackv1.OrchestackPlatform) error {
	logger := log.FromContext(ctx)

	values := buildHelmValues(platform)

	logger.Info("reconciling Helm release",
		"release", helmReleaseName,
		"namespace", platform.Namespace,
		"chart", helmChartPath,
		"version", platform.Spec.Version,
		"values", fmt.Sprintf("%v", values),
	)

	// Mark the platform as progressing while we apply the chart.
	r.setCondition(platform, orchestackv1.ConditionProgressing, metav1.ConditionTrue, "ApplyingHelmChart", "Installing/upgrading Helm release")

	// TODO(v1): Wire up helm.sh/helm/v3/pkg/action to actually template and
	// apply the chart. For now the operator relies on the Helm chart being
	// applied externally (e.g. via CI/CD) and focuses on health-monitoring.
	return nil
}

// reconcileDelete handles the deletion of an OrchestackPlatform resource.
func (r *OrchestackReconciler) reconcileDelete(ctx context.Context, platform *orchestackv1.OrchestackPlatform) (ctrl.Result, error) {
	logger := log.FromContext(ctx)
	logger.Info("handling OrchestackPlatform deletion", "name", platform.Name)

	// TODO(v1): Uninstall the Helm release here.

	controllerutil.RemoveFinalizer(platform, finalizerName)
	if err := r.Update(ctx, platform); err != nil {
		return ctrl.Result{}, fmt.Errorf("removing finalizer: %w", err)
	}
	return ctrl.Result{}, nil
}

// statusUpdate persists the status sub-resource.
func (r *OrchestackReconciler) statusUpdate(ctx context.Context, platform *orchestackv1.OrchestackPlatform) error {
	return r.Status().Update(ctx, platform)
}

// setCondition is a helper that upserts a condition on the platform status
// using the apimachinery meta helpers.
func (r *OrchestackReconciler) setCondition(platform *orchestackv1.OrchestackPlatform, condType string, status metav1.ConditionStatus, reason, message string) {
	meta.SetStatusCondition(&platform.Status.Conditions, metav1.Condition{
		Type:               condType,
		Status:             status,
		ObservedGeneration: platform.Generation,
		LastTransitionTime: metav1.Now(),
		Reason:             reason,
		Message:            message,
	})
}

// buildHelmValues converts the OrchestackPlatformSpec into a map suitable for
// passing to the Helm SDK as chart values.
func buildHelmValues(platform *orchestackv1.OrchestackPlatform) map[string]interface{} {
	vals := map[string]interface{}{
		"version": platform.Spec.Version,
	}

	// Services
	svcVals := map[string]interface{}{}
	for name, svc := range platform.Spec.Services {
		entry := map[string]interface{}{
			"image": svc.Image,
		}
		if svc.Replicas != nil {
			entry["replicas"] = *svc.Replicas
		}
		svcVals[name] = entry
	}
	if len(svcVals) > 0 {
		vals["services"] = svcVals
	}

	// Connectors
	connVals := map[string]interface{}{}
	for name, conn := range platform.Spec.Connectors {
		entry := map[string]interface{}{
			"enabled": conn.Enabled,
			"image":   conn.Image,
		}
		if conn.Replicas != nil {
			entry["replicas"] = *conn.Replicas
		}
		connVals[name] = entry
	}
	if len(connVals) > 0 {
		vals["connectors"] = connVals
	}

	// Infrastructure
	vals["nats"] = map[string]interface{}{
		"enabled":   platform.Spec.NATS.Enabled,
		"jetstream": platform.Spec.NATS.JetStream,
	}
	vals["postgres"] = map[string]interface{}{
		"enabled":        platform.Spec.Postgres.Enabled,
		"existingSecret": platform.Spec.Postgres.ExistingSecret,
	}
	vals["minio"] = map[string]interface{}{
		"enabled": platform.Spec.MinIO.Enabled,
		"persistence": map[string]interface{}{
			"enabled":          platform.Spec.MinIO.Persistence.Enabled,
			"storageClassName": platform.Spec.MinIO.Persistence.StorageClassName,
			"size":             platform.Spec.MinIO.Persistence.Size,
		},
	}
	vals["vault"] = map[string]interface{}{
		"enabled":      platform.Spec.Vault.Enabled,
		"externalAddr": platform.Spec.Vault.ExternalAddr,
	}
	vals["openshift"] = map[string]interface{}{
		"enabled": platform.Spec.OpenShift.Enabled,
		"route":   platform.Spec.OpenShift.Route,
	}

	return vals
}
