// Package handler provides the HTTP API for the Extension Controller.
package handler

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"strings"

	"github.com/CoastalDigitalResearch/Orchestack/services/extension-controller/internal/registry"
)

// ---------------------------------------------------------------------------
// API handler
// ---------------------------------------------------------------------------

// API exposes the Extension Controller REST endpoints.
type API struct {
	store registry.ExtensionStore
	mux   *http.ServeMux
}

// NewAPI creates and wires the API handler.
func NewAPI(store registry.ExtensionStore) *API {
	a := &API{store: store, mux: http.NewServeMux()}
	a.mux.HandleFunc("/v1/extensions", a.handleExtensions)
	a.mux.HandleFunc("/v1/extensions/", a.handleExtensionByID)
	return a
}

// ServeHTTP delegates to the internal mux.
func (a *API) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	a.mux.ServeHTTP(w, r)
}

// ---------------------------------------------------------------------------
// JSON helpers
// ---------------------------------------------------------------------------

type errorResponse struct {
	Error string `json:"error"`
}

func writeJSON(w http.ResponseWriter, status int, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(v); err != nil {
		log.Printf("[api] encode response: %v", err)
	}
}

func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, errorResponse{Error: msg})
}

// ---------------------------------------------------------------------------
// GET /v1/extensions
// ---------------------------------------------------------------------------

func (a *API) handleExtensions(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	var filterType *registry.ExtensionType
	var filterStatus *registry.ExtensionStatus

	if t := r.URL.Query().Get("type"); t != "" {
		et := registry.ExtensionType(t)
		if !et.Valid() {
			writeError(w, http.StatusBadRequest, "invalid type filter")
			return
		}
		filterType = &et
	}
	if s := r.URL.Query().Get("status"); s != "" {
		es := registry.ExtensionStatus(s)
		if !es.Valid() {
			writeError(w, http.StatusBadRequest, "invalid status filter")
			return
		}
		filterStatus = &es
	}

	exts, err := a.store.List(r.Context(), filterType, filterStatus)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "failed to list extensions")
		log.Printf("[api] list: %v", err)
		return
	}

	// Return an empty array rather than null.
	if exts == nil {
		exts = []registry.Extension{}
	}

	writeJSON(w, http.StatusOK, exts)
}

// ---------------------------------------------------------------------------
// /v1/extensions/{id}[/enable|/disable]
// ---------------------------------------------------------------------------

func (a *API) handleExtensionByID(w http.ResponseWriter, r *http.Request) {
	// Strip the prefix to extract the path segments.
	path := strings.TrimPrefix(r.URL.Path, "/v1/extensions/")
	parts := strings.SplitN(path, "/", 2)
	id := parts[0]
	if id == "" {
		writeError(w, http.StatusBadRequest, "extension id required")
		return
	}

	// Determine sub-action.
	action := ""
	if len(parts) == 2 {
		action = parts[1]
	}

	switch {
	case action == "" && r.Method == http.MethodGet:
		a.getExtension(w, r, id)
	case action == "enable" && r.Method == http.MethodPost:
		a.enableExtension(w, r, id)
	case action == "disable" && r.Method == http.MethodPost:
		a.disableExtension(w, r, id)
	default:
		writeError(w, http.StatusNotFound, "not found")
	}
}

func (a *API) getExtension(w http.ResponseWriter, r *http.Request, id string) {
	ext, err := a.store.Get(r.Context(), id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "failed to get extension")
		log.Printf("[api] get %s: %v", id, err)
		return
	}
	if ext == nil {
		writeError(w, http.StatusNotFound, "extension not found")
		return
	}
	writeJSON(w, http.StatusOK, ext)
}

func (a *API) enableExtension(w http.ResponseWriter, r *http.Request, id string) {
	a.setStatus(w, r.Context(), id, registry.StatusActive)
}

func (a *API) disableExtension(w http.ResponseWriter, r *http.Request, id string) {
	a.setStatus(w, r.Context(), id, registry.StatusDisabled)
}

func (a *API) setStatus(w http.ResponseWriter, ctx context.Context, id string, status registry.ExtensionStatus) {
	ext, err := a.store.Get(ctx, id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "failed to get extension")
		log.Printf("[api] get for status change %s: %v", id, err)
		return
	}
	if ext == nil {
		writeError(w, http.StatusNotFound, "extension not found")
		return
	}

	ext.Status = status
	if err := a.store.Update(ctx, ext); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to update extension")
		log.Printf("[api] update status %s: %v", id, err)
		return
	}
	writeJSON(w, http.StatusOK, ext)
}
