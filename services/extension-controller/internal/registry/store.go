package registry

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"time"

	// Postgres driver registered via blank import.
	_ "github.com/lib/pq"
)

// ---------------------------------------------------------------------------
// ExtensionStore — interface
// ---------------------------------------------------------------------------

// ExtensionStore defines the persistence API for extensions.
type ExtensionStore interface {
	// List returns extensions, optionally filtered by type and/or status.
	List(ctx context.Context, filterType *ExtensionType, filterStatus *ExtensionStatus) ([]Extension, error)
	// ListByType is a convenience wrapper around List.
	ListByType(ctx context.Context, t ExtensionType) ([]Extension, error)
	// Get returns a single extension by ID.
	Get(ctx context.Context, id string) (*Extension, error)
	// Create inserts a new extension record.
	Create(ctx context.Context, ext *Extension) error
	// Update persists changes to an existing extension.
	Update(ctx context.Context, ext *Extension) error
	// Delete removes an extension by ID.
	Delete(ctx context.Context, id string) error
	// EnsureSchema creates the required tables if they do not exist.
	EnsureSchema(ctx context.Context) error
}

// ---------------------------------------------------------------------------
// PostgresExtensionStore — implementation
// ---------------------------------------------------------------------------

// PostgresExtensionStore implements ExtensionStore backed by PostgreSQL.
type PostgresExtensionStore struct {
	db *sql.DB
}

// NewPostgresExtensionStore opens a connection pool and returns a ready store.
func NewPostgresExtensionStore(dsn string) (*PostgresExtensionStore, error) {
	db, err := sql.Open("postgres", dsn)
	if err != nil {
		return nil, fmt.Errorf("open postgres: %w", err)
	}
	db.SetMaxOpenConns(10)
	db.SetMaxIdleConns(5)
	db.SetConnMaxLifetime(5 * time.Minute)
	if err := db.Ping(); err != nil {
		return nil, fmt.Errorf("ping postgres: %w", err)
	}
	return &PostgresExtensionStore{db: db}, nil
}

// NewPostgresExtensionStoreFromDB wraps an existing *sql.DB.
func NewPostgresExtensionStoreFromDB(db *sql.DB) *PostgresExtensionStore {
	return &PostgresExtensionStore{db: db}
}

// Close closes the underlying database connection pool.
func (s *PostgresExtensionStore) Close() error {
	return s.db.Close()
}

// ---------------------------------------------------------------------------
// Schema bootstrap
// ---------------------------------------------------------------------------

const schemaSQL = `
CREATE TABLE IF NOT EXISTS extensions (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    version       TEXT NOT NULL,
    type          TEXT NOT NULL,
    trust_tier    TEXT NOT NULL DEFAULT 'community',
    digest        TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'pending',
    manifest_path TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tool_descriptors (
    tool_id       TEXT PRIMARY KEY,
    extension_id  TEXT NOT NULL REFERENCES extensions(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    input_schema  JSONB,
    output_schema JSONB,
    risk_class    TEXT NOT NULL DEFAULT 'low',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_extensions_type   ON extensions(type);
CREATE INDEX IF NOT EXISTS idx_extensions_status ON extensions(status);
CREATE INDEX IF NOT EXISTS idx_tool_descriptors_extension ON tool_descriptors(extension_id);
`

// EnsureSchema creates tables and indexes if they do not already exist.
func (s *PostgresExtensionStore) EnsureSchema(ctx context.Context) error {
	_, err := s.db.ExecContext(ctx, schemaSQL)
	return err
}

// ---------------------------------------------------------------------------
// CRUD
// ---------------------------------------------------------------------------

// List returns extensions with optional type/status filters.
func (s *PostgresExtensionStore) List(ctx context.Context, filterType *ExtensionType, filterStatus *ExtensionStatus) ([]Extension, error) {
	query := `SELECT id, name, version, type, trust_tier, digest, status, manifest_path, created_at, updated_at FROM extensions WHERE 1=1`
	args := []interface{}{}
	argIdx := 1

	if filterType != nil {
		query += fmt.Sprintf(" AND type = $%d", argIdx)
		args = append(args, string(*filterType))
		argIdx++
	}
	if filterStatus != nil {
		query += fmt.Sprintf(" AND status = $%d", argIdx)
		args = append(args, string(*filterStatus))
		argIdx++
	}
	query += " ORDER BY name ASC"

	rows, err := s.db.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, fmt.Errorf("list extensions: %w", err)
	}
	defer rows.Close()

	var exts []Extension
	for rows.Next() {
		var e Extension
		if err := rows.Scan(&e.ID, &e.Name, &e.Version, &e.Type, &e.TrustTier, &e.Digest, &e.Status, &e.ManifestPath, &e.CreatedAt, &e.UpdatedAt); err != nil {
			return nil, fmt.Errorf("scan extension: %w", err)
		}
		exts = append(exts, e)
	}
	return exts, rows.Err()
}

// ListByType is a convenience wrapper that lists extensions of a given type.
func (s *PostgresExtensionStore) ListByType(ctx context.Context, t ExtensionType) ([]Extension, error) {
	return s.List(ctx, &t, nil)
}

// Get retrieves a single extension by ID.
func (s *PostgresExtensionStore) Get(ctx context.Context, id string) (*Extension, error) {
	row := s.db.QueryRowContext(ctx,
		`SELECT id, name, version, type, trust_tier, digest, status, manifest_path, created_at, updated_at
		 FROM extensions WHERE id = $1`, id)

	var e Extension
	err := row.Scan(&e.ID, &e.Name, &e.Version, &e.Type, &e.TrustTier, &e.Digest, &e.Status, &e.ManifestPath, &e.CreatedAt, &e.UpdatedAt)
	if err == sql.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("get extension %s: %w", id, err)
	}
	return &e, nil
}

// Create inserts a new extension. Timestamps are set server-side.
func (s *PostgresExtensionStore) Create(ctx context.Context, ext *Extension) error {
	if err := ext.Validate(); err != nil {
		return fmt.Errorf("validate: %w", err)
	}
	now := time.Now().UTC()
	ext.CreatedAt = now
	ext.UpdatedAt = now

	_, err := s.db.ExecContext(ctx,
		`INSERT INTO extensions (id, name, version, type, trust_tier, digest, status, manifest_path, created_at, updated_at)
		 VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)`,
		ext.ID, ext.Name, ext.Version, string(ext.Type), ext.TrustTier, ext.Digest,
		string(ext.Status), ext.ManifestPath, ext.CreatedAt, ext.UpdatedAt)
	if err != nil {
		return fmt.Errorf("create extension %s: %w", ext.ID, err)
	}
	return nil
}

// Update persists changes to an existing extension record.
func (s *PostgresExtensionStore) Update(ctx context.Context, ext *Extension) error {
	if err := ext.Validate(); err != nil {
		return fmt.Errorf("validate: %w", err)
	}
	ext.UpdatedAt = time.Now().UTC()

	res, err := s.db.ExecContext(ctx,
		`UPDATE extensions SET name=$2, version=$3, type=$4, trust_tier=$5, digest=$6,
		 status=$7, manifest_path=$8, updated_at=$9 WHERE id=$1`,
		ext.ID, ext.Name, ext.Version, string(ext.Type), ext.TrustTier, ext.Digest,
		string(ext.Status), ext.ManifestPath, ext.UpdatedAt)
	if err != nil {
		return fmt.Errorf("update extension %s: %w", ext.ID, err)
	}
	n, _ := res.RowsAffected()
	if n == 0 {
		return fmt.Errorf("extension %s not found", ext.ID)
	}
	return nil
}

// Delete removes an extension by ID. Tool descriptors are cascade-deleted.
func (s *PostgresExtensionStore) Delete(ctx context.Context, id string) error {
	res, err := s.db.ExecContext(ctx, `DELETE FROM extensions WHERE id = $1`, id)
	if err != nil {
		return fmt.Errorf("delete extension %s: %w", id, err)
	}
	n, _ := res.RowsAffected()
	if n == 0 {
		return fmt.Errorf("extension %s not found", id)
	}
	return nil
}

// ---------------------------------------------------------------------------
// Tool descriptor helpers
// ---------------------------------------------------------------------------

// CreateToolDescriptor inserts a tool descriptor linked to an extension.
func (s *PostgresExtensionStore) CreateToolDescriptor(ctx context.Context, extID string, td *ToolDescriptor) error {
	inSchema, _ := json.Marshal(td.InputSchema)
	outSchema, _ := json.Marshal(td.OutputSchema)

	_, err := s.db.ExecContext(ctx,
		`INSERT INTO tool_descriptors (tool_id, extension_id, name, description, input_schema, output_schema, risk_class)
		 VALUES ($1, $2, $3, $4, $5, $6, $7)`,
		td.ToolID, extID, td.Name, td.Description, inSchema, outSchema, td.RiskClass)
	if err != nil {
		return fmt.Errorf("create tool descriptor %s: %w", td.ToolID, err)
	}
	return nil
}

// DeleteToolDescriptors removes all tool descriptors for an extension.
func (s *PostgresExtensionStore) DeleteToolDescriptors(ctx context.Context, extID string) error {
	_, err := s.db.ExecContext(ctx, `DELETE FROM tool_descriptors WHERE extension_id = $1`, extID)
	return err
}
