package handler

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/CoastalDigitalResearch/Orchestack/services/extension-controller/internal/registry"
)

// --- mock store -------------------------------------------------------------

type mockExtensionStore struct {
	mu   sync.Mutex
	exts map[string]*registry.Extension

	listErr   error
	getErr    error
	createErr error
	updateErr error
	deleteErr error
}

func newMockExtensionStore() *mockExtensionStore {
	return &mockExtensionStore{
		exts: make(map[string]*registry.Extension),
	}
}

func (m *mockExtensionStore) seed(exts ...registry.Extension) {
	m.mu.Lock()
	defer m.mu.Unlock()
	for _, e := range exts {
		ext := e // copy
		m.exts[ext.ID] = &ext
	}
}

func (m *mockExtensionStore) List(_ context.Context, filterType *registry.ExtensionType, filterStatus *registry.ExtensionStatus) ([]registry.Extension, error) {
	if m.listErr != nil {
		return nil, m.listErr
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	var out []registry.Extension
	for _, e := range m.exts {
		if filterType != nil && e.Type != *filterType {
			continue
		}
		if filterStatus != nil && e.Status != *filterStatus {
			continue
		}
		out = append(out, *e)
	}
	return out, nil
}

func (m *mockExtensionStore) ListByType(ctx context.Context, t registry.ExtensionType) ([]registry.Extension, error) {
	return m.List(ctx, &t, nil)
}

func (m *mockExtensionStore) Get(_ context.Context, id string) (*registry.Extension, error) {
	if m.getErr != nil {
		return nil, m.getErr
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	e, ok := m.exts[id]
	if !ok {
		return nil, nil
	}
	return e, nil
}

func (m *mockExtensionStore) Create(_ context.Context, ext *registry.Extension) error {
	if m.createErr != nil {
		return m.createErr
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	m.exts[ext.ID] = ext
	return nil
}

func (m *mockExtensionStore) Update(_ context.Context, ext *registry.Extension) error {
	if m.updateErr != nil {
		return m.updateErr
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	m.exts[ext.ID] = ext
	return nil
}

func (m *mockExtensionStore) Delete(_ context.Context, id string) error {
	if m.deleteErr != nil {
		return m.deleteErr
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	delete(m.exts, id)
	return nil
}

func (m *mockExtensionStore) EnsureSchema(_ context.Context) error { return nil }

var _ registry.ExtensionStore = (*mockExtensionStore)(nil)

// --- helpers ----------------------------------------------------------------

func sampleExtension(id, name string, extType registry.ExtensionType) registry.Extension {
	return registry.Extension{
		ID:        id,
		Name:      name,
		Version:   "1.0.0",
		Type:      extType,
		TrustTier: "official",
		Status:    registry.StatusActive,
		CreatedAt: time.Now(),
		UpdatedAt: time.Now(),
	}
}

// --- tests ------------------------------------------------------------------

func TestListExtensions_Empty(t *testing.T) {
	store := newMockExtensionStore()
	api := NewAPI(store)

	req := httptest.NewRequest(http.MethodGet, "/v1/extensions", nil)
	rr := httptest.NewRecorder()
	api.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rr.Code)
	}

	var exts []registry.Extension
	json.NewDecoder(rr.Body).Decode(&exts)
	if len(exts) != 0 {
		t.Errorf("expected 0 extensions, got %d", len(exts))
	}
}

func TestListExtensions_WithData(t *testing.T) {
	store := newMockExtensionStore()
	store.seed(
		sampleExtension("ext-1", "shell-tool", registry.ExtTypeTool),
		sampleExtension("ext-2", "summarize-skill", registry.ExtTypeSkill),
	)
	api := NewAPI(store)

	req := httptest.NewRequest(http.MethodGet, "/v1/extensions", nil)
	rr := httptest.NewRecorder()
	api.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rr.Code)
	}

	var exts []registry.Extension
	json.NewDecoder(rr.Body).Decode(&exts)
	if len(exts) != 2 {
		t.Errorf("expected 2 extensions, got %d", len(exts))
	}
}

func TestListExtensions_FilterByType(t *testing.T) {
	store := newMockExtensionStore()
	store.seed(
		sampleExtension("ext-1", "shell-tool", registry.ExtTypeTool),
		sampleExtension("ext-2", "summarize-skill", registry.ExtTypeSkill),
	)
	api := NewAPI(store)

	req := httptest.NewRequest(http.MethodGet, "/v1/extensions?type=tool", nil)
	rr := httptest.NewRecorder()
	api.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rr.Code)
	}

	var exts []registry.Extension
	json.NewDecoder(rr.Body).Decode(&exts)
	if len(exts) != 1 {
		t.Errorf("expected 1 tool extension, got %d", len(exts))
	}
}

func TestListExtensions_InvalidTypeFilter(t *testing.T) {
	store := newMockExtensionStore()
	api := NewAPI(store)

	req := httptest.NewRequest(http.MethodGet, "/v1/extensions?type=bogus", nil)
	rr := httptest.NewRecorder()
	api.ServeHTTP(rr, req)

	if rr.Code != http.StatusBadRequest {
		t.Errorf("expected 400, got %d", rr.Code)
	}
}

func TestGetExtension_Found(t *testing.T) {
	store := newMockExtensionStore()
	store.seed(sampleExtension("ext-1", "shell-tool", registry.ExtTypeTool))
	api := NewAPI(store)

	req := httptest.NewRequest(http.MethodGet, "/v1/extensions/ext-1", nil)
	rr := httptest.NewRecorder()
	api.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", rr.Code, rr.Body.String())
	}

	var ext registry.Extension
	json.NewDecoder(rr.Body).Decode(&ext)
	if ext.ID != "ext-1" {
		t.Errorf("expected ext-1, got %s", ext.ID)
	}
}

func TestGetExtension_NotFound(t *testing.T) {
	store := newMockExtensionStore()
	api := NewAPI(store)

	req := httptest.NewRequest(http.MethodGet, "/v1/extensions/nonexistent", nil)
	rr := httptest.NewRecorder()
	api.ServeHTTP(rr, req)

	if rr.Code != http.StatusNotFound {
		t.Errorf("expected 404, got %d", rr.Code)
	}
}

func TestEnableExtension(t *testing.T) {
	store := newMockExtensionStore()
	ext := sampleExtension("ext-1", "shell-tool", registry.ExtTypeTool)
	ext.Status = registry.StatusDisabled
	store.seed(ext)
	api := NewAPI(store)

	req := httptest.NewRequest(http.MethodPost, "/v1/extensions/ext-1/enable", nil)
	rr := httptest.NewRecorder()
	api.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", rr.Code, rr.Body.String())
	}

	var result registry.Extension
	json.NewDecoder(rr.Body).Decode(&result)
	if result.Status != registry.StatusActive {
		t.Errorf("expected status 'active', got %q", result.Status)
	}
}

func TestDisableExtension(t *testing.T) {
	store := newMockExtensionStore()
	store.seed(sampleExtension("ext-1", "shell-tool", registry.ExtTypeTool))
	api := NewAPI(store)

	req := httptest.NewRequest(http.MethodPost, "/v1/extensions/ext-1/disable", nil)
	rr := httptest.NewRecorder()
	api.ServeHTTP(rr, req)

	if rr.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d: %s", rr.Code, rr.Body.String())
	}

	var result registry.Extension
	json.NewDecoder(rr.Body).Decode(&result)
	if result.Status != registry.StatusDisabled {
		t.Errorf("expected status 'disabled', got %q", result.Status)
	}
}

func TestEnableExtension_NotFound(t *testing.T) {
	store := newMockExtensionStore()
	api := NewAPI(store)

	req := httptest.NewRequest(http.MethodPost, "/v1/extensions/nonexistent/enable", nil)
	rr := httptest.NewRecorder()
	api.ServeHTTP(rr, req)

	if rr.Code != http.StatusNotFound {
		t.Errorf("expected 404, got %d", rr.Code)
	}
}

func TestListExtensions_StoreError(t *testing.T) {
	store := newMockExtensionStore()
	store.listErr = fmt.Errorf("db down")
	api := NewAPI(store)

	req := httptest.NewRequest(http.MethodGet, "/v1/extensions", nil)
	rr := httptest.NewRecorder()
	api.ServeHTTP(rr, req)

	if rr.Code != http.StatusInternalServerError {
		t.Errorf("expected 500, got %d", rr.Code)
	}
}

func TestListExtensions_MethodNotAllowed(t *testing.T) {
	store := newMockExtensionStore()
	api := NewAPI(store)

	req := httptest.NewRequest(http.MethodPost, "/v1/extensions", nil)
	rr := httptest.NewRecorder()
	api.ServeHTTP(rr, req)

	if rr.Code != http.StatusMethodNotAllowed {
		t.Errorf("expected 405, got %d", rr.Code)
	}
}
