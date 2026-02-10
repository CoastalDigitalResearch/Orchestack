package reconciler

import (
	"context"
	"encoding/json"
	"log"
	"os"
	"path/filepath"
	"time"

	"github.com/CoastalDigitalResearch/Orchestack/services/extension-controller/internal/registry"
	"github.com/nats-io/nats.go"
)

// ---------------------------------------------------------------------------
// Reconciler
// ---------------------------------------------------------------------------

// Reconciler watches a local Git-synced directory for extension manifests and
// keeps the extension store in sync.
type Reconciler struct {
	store    registry.ExtensionStore
	nc       *nats.Conn
	repoPath string // root of the git config repo checkout
	interval time.Duration
}

// New creates a new Reconciler. repoPath should point to the local checkout
// of the GitOps config repo that contains an extensions/ directory.
func New(store registry.ExtensionStore, nc *nats.Conn, repoPath string) *Reconciler {
	return &Reconciler{
		store:    store,
		nc:       nc,
		repoPath: repoPath,
		interval: 30 * time.Second,
	}
}

// ReconcileLoop runs the reconciliation loop until the context is cancelled.
func (r *Reconciler) ReconcileLoop(ctx context.Context) {
	log.Printf("[reconciler] starting loop (interval=%s, repo=%s)", r.interval, r.repoPath)

	// Run once immediately on start.
	r.reconcile(ctx)

	ticker := time.NewTicker(r.interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			log.Println("[reconciler] stopping")
			return
		case <-ticker.C:
			r.reconcile(ctx)
		}
	}
}

// ---------------------------------------------------------------------------
// Core reconciliation
// ---------------------------------------------------------------------------

func (r *Reconciler) reconcile(ctx context.Context) {
	desired, err := r.scanExtensions()
	if err != nil {
		log.Printf("[reconciler] scan error: %v", err)
		return
	}

	// Build lookup of desired manifests keyed by name.
	desiredMap := make(map[string]*ExtensionManifest, len(desired))
	for i := range desired {
		desiredMap[desired[i].Metadata.Name] = &desired[i]
	}

	// Fetch current state from store.
	existing, err := r.store.List(ctx, nil, nil)
	if err != nil {
		log.Printf("[reconciler] list error: %v", err)
		return
	}
	existingMap := make(map[string]*registry.Extension, len(existing))
	for i := range existing {
		existingMap[existing[i].ID] = &existing[i]
	}

	// Install or update desired extensions.
	for name, manifest := range desiredMap {
		ext, exists := existingMap[name]
		if !exists {
			r.installExtension(ctx, manifest)
		} else {
			r.reconcileExtension(ctx, ext, manifest)
			delete(existingMap, name) // mark as reconciled
		}
	}

	// Remove extensions that are no longer declared.
	for id, ext := range existingMap {
		r.removeExtension(ctx, id, ext)
	}
}

// ---------------------------------------------------------------------------
// Scan git repo
// ---------------------------------------------------------------------------

// scanExtensions walks extensions/ in the repo and parses every extension.yaml.
func (r *Reconciler) scanExtensions() ([]ExtensionManifest, error) {
	extDir := filepath.Join(r.repoPath, "extensions")
	entries, err := os.ReadDir(extDir)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil // no extensions directory yet
		}
		return nil, err
	}

	var manifests []ExtensionManifest
	for _, entry := range entries {
		if !entry.IsDir() {
			continue
		}
		manifestPath := filepath.Join(extDir, entry.Name(), "extension.yaml")
		m, err := ParseManifest(manifestPath)
		if err != nil {
			log.Printf("[reconciler] skip %s: %v", entry.Name(), err)
			continue
		}
		if errs := ValidateManifest(m); len(errs) > 0 {
			for _, e := range errs {
				log.Printf("[reconciler] manifest %s invalid: %v", entry.Name(), e)
			}
			continue
		}
		manifests = append(manifests, *m)
	}
	return manifests, nil
}

// ---------------------------------------------------------------------------
// Install / Update / Remove
// ---------------------------------------------------------------------------

func (r *Reconciler) installExtension(ctx context.Context, m *ExtensionManifest) {
	status := registry.StatusActive
	if !m.IsEnabled() {
		status = registry.StatusDisabled
	}

	ext := &registry.Extension{
		ID:           m.Metadata.Name,
		Name:         m.Metadata.Name,
		Version:      m.Metadata.Version,
		Type:         m.Spec.Type,
		TrustTier:    m.Spec.TrustTier,
		Digest:       m.Spec.Digest,
		Status:       status,
		ManifestPath: filepath.Join(r.repoPath, "extensions", m.Metadata.Name, "extension.yaml"),
	}
	if err := r.store.Create(ctx, ext); err != nil {
		log.Printf("[reconciler] install %s failed: %v", m.Metadata.Name, err)
		return
	}
	log.Printf("[reconciler] installed %s v%s", m.Metadata.Name, m.Metadata.Version)
	r.publish("ext.installed", ext)
}

func (r *Reconciler) reconcileExtension(ctx context.Context, ext *registry.Extension, m *ExtensionManifest) {
	changed := false

	if ext.Version != m.Metadata.Version || ext.Digest != m.Spec.Digest {
		changed = true
	}

	desiredStatus := registry.StatusActive
	if !m.IsEnabled() {
		desiredStatus = registry.StatusDisabled
	}
	if ext.Status != desiredStatus {
		changed = true
	}

	if !changed {
		return
	}

	r.updateExtension(ctx, ext, m, desiredStatus)
}

func (r *Reconciler) updateExtension(ctx context.Context, ext *registry.Extension, m *ExtensionManifest, status registry.ExtensionStatus) {
	ext.Version = m.Metadata.Version
	ext.Digest = m.Spec.Digest
	ext.TrustTier = m.Spec.TrustTier
	ext.Status = status

	if err := r.store.Update(ctx, ext); err != nil {
		log.Printf("[reconciler] update %s failed: %v", ext.ID, err)
		return
	}
	log.Printf("[reconciler] updated %s to v%s (status=%s)", ext.ID, ext.Version, ext.Status)

	if status == registry.StatusDisabled {
		r.publish("ext.disabled", ext)
	} else {
		r.publish("ext.updated", ext)
	}
}

func (r *Reconciler) removeExtension(ctx context.Context, id string, ext *registry.Extension) {
	ext.Status = registry.StatusRemoving
	_ = r.store.Update(ctx, ext)

	if err := r.store.Delete(ctx, id); err != nil {
		log.Printf("[reconciler] remove %s failed: %v", id, err)
		return
	}
	log.Printf("[reconciler] removed %s", id)
	r.publish("ext.disabled", ext)
}

// ---------------------------------------------------------------------------
// NATS event publishing
// ---------------------------------------------------------------------------

func (r *Reconciler) publish(subject string, ext *registry.Extension) {
	if r.nc == nil {
		return
	}
	data, err := json.Marshal(ext)
	if err != nil {
		log.Printf("[reconciler] marshal event: %v", err)
		return
	}
	if err := r.nc.Publish(subject, data); err != nil {
		log.Printf("[reconciler] publish %s: %v", subject, err)
	}
}
