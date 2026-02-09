# Orchestack v1 — Developer Task List

**Prepared by:** System Architect
**Date:** 2026-02-09
**Scope:** Full v1 (Phase 1 core + Phase 2 enterprise/onchain)
**Strategy:** Phase 1 ships and stabilizes first; Phase 2 builds on proven core

---

## Key Architectural Decisions (reference)

- **Monorepo, polyglot:** Go for high-concurrency control-plane services, Python for extensibility/connectors/ML, TypeScript for any web UI. Python preferred where ambiguous.
- **Greenfield build** informed by OpenClaw design, not porting code.
- **Decomposed orchestrator:** Session Scheduler, Task Dispatcher, Policy Evaluator, Loop Runner as separate services.
- **Model Router:** separate service, dynamic registration, fallback by size+locality.
- **Budget Accounting:** separate service with by-model and by-provider breakdowns.
- **Connectors:** separate long-running services, common message format, AAP-style identity mapping, reply to same channel by default.
- **Infrastructure:** assume virgin cluster. Vault exists but build as if from scratch.
- **Daytona:** latest open-source, self-hosted.
- **DLP:** mydlp/mydlp.
- **Deployment:** K8s Operator + Podman/Docker Compose for local dev.
- **CI/CD:** Tekton primary, support GitLab CI and GitHub Actions.
- **Schema migrations:** Atlas.
- **All 5 connectors** in v1: Discord, Slack, Email, Telegram, Webchat.
- **RFC-004 (Onchain):** Phase 2 of v1, after Phase 1 core is validated.
- **Extensibility:** non-negotiable for v1.

---

## Dependency Legend

Tasks are ordered by dependency. Each task lists its `Blocked-by` prerequisites.
Sizes: **S** (1-3 days), **M** (3-7 days), **L** (1-2 weeks), **XL** (2-4 weeks)

---

# PHASE 1 — Core Platform

## Track A: Foundation (everything depends on this)

### A-001: Monorepo scaffold and build system
**Size:** M
**Blocked-by:** none
**Language:** polyglot
**Deliverables:**
- Monorepo directory structure:
  ```
  /
  ├── rfcs/                    # current docs move here
  ├── proto/                   # shared schemas (protobuf, JSON Schema, OpenAPI)
  ├── libs/
  │   ├── envelope-py/         # Python envelope library
  │   ├── envelope-go/         # Go envelope library
  │   └── envelope-ts/         # TypeScript envelope library
  ├── services/
  │   ├── session-scheduler/
  │   ├── task-dispatcher/
  │   ├── policy-evaluator/
  │   ├── loop-runner/
  │   ├── model-router/
  │   ├── budget-accounting/
  │   ├── memory-plane/
  │   ├── dlp-scanner/
  │   ├── daytona-executor/
  │   ├── extension-controller/
  │   └── ...
  ├── connectors/
  │   ├── common/              # shared connector framework
  │   ├── discord/
  │   ├── slack/
  │   ├── email/
  │   ├── telegram/
  │   └── webchat/
  ├── extensions/              # built-in extension packages
  ├── deploy/
  │   ├── helm/                # Helm charts
  │   ├── operator/            # K8s Operator
  │   ├── compose/             # Podman/Docker Compose
  │   └── ci/                  # Tekton, GitLab, GitHub Actions
  ├── migrations/              # Atlas schema migrations
  ├── tools/                   # CLI tools (orchestack-ext, etc.)
  └── docs/
  ```
- Root Makefile / Taskfile with targets: `lint`, `test`, `build`, `dev-up`, `dev-down`
- Pre-commit hooks (formatting, linting)
- Containerfile templates per language (Go, Python)
- `.editorconfig`, `.gitignore`, root `pyproject.toml`, root `go.work`

**Acceptance:** `make lint` and `make test` pass on empty scaffold. `make dev-up` starts a minimal Compose stack (NATS + Postgres + MinIO).

---

### A-002: Event envelope schema and libraries
**Size:** M
**Blocked-by:** A-001
**Language:** Python (primary), Go, TypeScript
**Deliverables:**
- JSON Schema for the RFC-001 §5.1 envelope (version, event_id, event_type, actor, trace, correlation, idempotency_key, priority, payload_ref, schema)
- Python library (`orchestack-envelope`):
  - Envelope dataclass/model (Pydantic v2)
  - ULID generation for event_id
  - Validation on publish and consume
  - Serialization/deserialization (JSON, optionally msgpack)
  - W3C traceparent header generation/parsing
  - Idempotency key generation helper (`idem:{tenant}:{task_id}:{run_attempt}:{step_type}:{step_seq}`)
- Go library (`envelope`):
  - Struct + marshal/unmarshal
  - Same validation rules
- TypeScript library (`@orchestack/envelope`):
  - Types + Zod schema
  - Same validation rules
- Unit tests for all three (schema validation, roundtrip, edge cases)

**Acceptance:** All three libraries pass schema conformance tests against the same test vectors. Published as internal packages.

---

### A-003: NATS JetStream deployment and stream configuration
**Size:** M
**Blocked-by:** A-001
**Deliverables:**
- Helm chart for NATS Server with JetStream enabled
- Docker Compose service definition for local dev
- Stream definitions (RFC-001 §8):
  - `STREAM_TASKS` — subjects: `tasks.>`, retention: work-queue, max-age: 7d
  - `STREAM_EVENTS` — subjects: `ingress.>`, `memory.>`, `router.>`, `heartbeat.>`, retention: limits, max-age: 24h
  - `STREAM_AUDIT` — subjects: `audit.>`, retention: limits, max-age: 90d
- Consumer templates (pull-based, explicit ack, exponential backoff with jitter)
- mTLS configuration (cert generation scripts for dev, Vault PKI for prod)
- NKey generation and JWT-scoped subject permissions per service
- Stream initialization script/job that runs on first deploy

**Acceptance:** Streams are created on startup. A test publisher/consumer can roundtrip an envelope message through each stream. mTLS enforced in prod config.

---

### A-004: Postgres schema and Atlas migrations
**Size:** L
**Blocked-by:** A-001
**Deliverables:**
- Helm chart for Postgres (or CrunchyData Postgres Operator on OpenShift)
- Docker Compose service definition for local dev
- Atlas project configuration (`atlas.hcl`)
- Initial migration covering all RFC-001 §9 entities:
  - `tenants`
  - `workspaces`
  - `agents`
  - `sessions` (with `next_ingress_seq`, `last_processed_ingress_seq`)
  - `ingress_messages` (unique on `tenant_id, session_id, ingress_seq`)
  - `tasks` (with `parent_task_id`, `status` enum, `budget_id`, `capability_grant_id`)
  - `runs` (with `attempt`, `status`)
  - `steps` (with `step_type` enum, `idempotency_key` unique per tenant)
  - `artifacts` (with `retention_class`)
  - `approval_requests` (with `status` enum, `expires_at`)
  - `budgets` (with `daily_limit`, `monthly_limit`, `soft_threshold`, `hard_threshold`, `spend_today`, `spend_month`)
- RFC-002 policy entities:
  - `org_policies`
  - `agent_definitions` (with `agent_definition_ref` for git digest)
  - `subagent_templates`
  - `capability_grants`
- RFC-005 extension entities:
  - `extensions` (id, version, digest, trust_tier, enabled)
  - `tool_descriptors`
  - `skill_specs`
  - `memory_plugin_endpoints`
  - `storage_driver_endpoints`
  - `loop_specs`
  - `schedule_specs`
- Indexes for all foreign keys and common query patterns
- Row-level `tenant_id` on every table (v2-ready)
- `created_at` / `updated_at` timestamps on all mutable tables
- Seed data: default tenant, default org policy, default budget

**Acceptance:** `atlas migrate apply` runs cleanly on fresh Postgres. `atlas migrate lint` passes. Seed data is present. Rollback of latest migration works.

---

### A-005: MinIO / S3-compatible object storage deployment
**Size:** S
**Blocked-by:** A-001
**Deliverables:**
- Helm chart for MinIO
- Docker Compose service definition for local dev
- Bucket creation job:
  - `homarus-memory` (RFC-003 §6.2)
  - `homarus-artifacts`
  - `homarus-audit-export`
- Bucket policies (service-account scoped access)
- Shared Python client library (`orchestack-storage`) wrapping boto3 with:
  - `put_object`, `get_object`, `list_objects`, `delete_object`
  - SHA-256 checksum on put
  - Content-type handling
  - `payload_ref` generation (RFC-001 §6.2 URI format: `s3://<bucket>/<key>`)
- Encryption-at-rest configuration (MinIO server-side encryption with Vault KMS)

**Acceptance:** Objects can be stored and retrieved via the client library. Checksums are verified on get. Encryption at rest is enabled.

---

### A-006: Vault integration layer
**Size:** M
**Blocked-by:** A-001
**Deliverables:**
- Vault deployment Helm chart (HA mode) or configuration for existing Vault
- Kubernetes auth method configuration
- AppRole auth for non-K8s (Podman) mode
- PKI secrets engine for mTLS certificates (NATS, inter-service)
- KV v2 secrets engine paths:
  - `orchestack/connectors/<connector_type>/<account_id>`
  - `orchestack/models/<provider>`
  - `orchestack/agents/<agent_id>`
- Transit engine for MinIO server-side encryption keys
- External Secrets Operator (ESO) deployment + `SecretStore` / `ExternalSecret` CRDs
- Python helper library for Vault interactions (hvac wrapper with auth method abstraction)
- Secret rotation policy templates (90d API keys, 24h tokens)

**Acceptance:** ESO syncs a test secret from Vault into a K8s Secret. Python helper can read/write KV paths. PKI issues short-lived certs.

---

### A-007: SPIFFE/SPIRE deployment and service identity
**Size:** M
**Blocked-by:** A-006
**Deliverables:**
- SPIRE Server Helm chart (OpenShift-compatible)
- SPIRE Agent DaemonSet
- Registration entries for each Orchestack service (one SPIFFE ID per service)
- SVID TTL configuration (<= 24h per RFC-002 §4.2)
- Workload attestor configuration (K8s node attestor + pod attestor)
- Go and Python SPIFFE helper libraries (workload API client)
- Integration with NATS mTLS (SVID certificates as NATS client certs)

**Acceptance:** Each service can obtain an SVID. NATS connections authenticated via SPIFFE-issued certs. SVIDs rotate automatically.

---

### A-008: Podman/Docker Compose full dev stack
**Size:** M
**Blocked-by:** A-003, A-004, A-005, A-006
**Deliverables:**
- Single `docker-compose.yml` (or `podman-compose.yml`) that brings up:
  - NATS with JetStream
  - Postgres (with migrations auto-applied)
  - MinIO (with buckets auto-created)
  - Vault (dev mode for local, with auto-unsealing and seed policies)
  - All Orchestack services (with hot-reload where possible)
- `.env.example` with all configurable values
- `make dev-up` / `make dev-down` / `make dev-logs` targets
- Health check endpoints for all services
- Service discovery via Docker DNS

**Acceptance:** `make dev-up` from a clean clone brings up the full stack. All health checks pass within 60 seconds.

---

## Track B: Core Orchestrator Services

### B-001: Session Scheduler service
**Size:** L
**Blocked-by:** A-002, A-003, A-004
**Language:** Go
**Deliverables:**
- NATS consumer subscribing to `ingress.>` subjects
- Ingress persistence:
  - On receiving an ingress event, write `IngressMessage` row with transactionally incrementing `ingress_seq` per session (`Session.next_ingress_seq`)
  - Store normalized message body in object storage, reference via `payload_ref`
- Session scheduling logic (RFC-001 §10.2):
  - Select next unprocessed ingress message (smallest `ingress_seq > last_processed_ingress_seq`)
  - Create Task only when:
    - no active interactive Task in RUNNING/WAITING state for this session
    - previous ingress message has been processed
  - Postgres advisory lock on `(tenant_id, session_id)` during scheduling
- Session creation/lookup:
  - Create session from connector identity mapping (`connector_type`, `connector_account_id`, `thread_id`)
  - Upsert on first message
- Publish `tasks.create` event when a new Task is created
- OpenTelemetry spans: ingress_received, session_resolved, task_created
- Health check and readiness endpoints

**Acceptance:** Messages arriving on ingress subjects create properly ordered Tasks. Concurrent messages for the same session are serialized. Messages for different sessions are processed in parallel.

---

### B-002: Task Dispatcher service
**Size:** XL
**Blocked-by:** A-002, A-003, A-004, B-001
**Language:** Go
**Deliverables:**
- NATS consumer subscribing to `tasks.create`, `tasks.cancel`
- Task state machine (RFC-001 §11):
  - All states: NEW, QUEUED, RUNNING, WAITING_APPROVAL, COMPLETED, FAILED, CANCELLED, TIMED_OUT
  - All allowed transitions with optimistic concurrency (row version)
  - Immutable transition event log emitted on `tasks.run.*` subjects
- Task dispatch:
  - On `tasks.create`: validate, transition NEW→QUEUED, request CapabilityGrant from Policy Evaluator, publish `tasks.dispatch`
  - On `tasks.dispatch`: assign to Loop Runner, transition QUEUED→RUNNING
- Subagent task spawning:
  - Parent Task RUNNING creates child Task with `parent_task_id`
  - Enforce max depth (2), max concurrent children (8), max wall time (3600s)
  - Child inherits restricted CapabilityGrant
  - Isolated memory scope by default
- Timeout enforcement:
  - Background goroutine checks for tasks exceeding wall time
  - Transition to TIMED_OUT
- Cancellation handling:
  - `tasks.cancel` → transition to CANCELLED (from QUEUED or WAITING_APPROVAL)
  - Propagate cancellation to running children
- Dead-letter handling:
  - After N failures (configurable, default 10), publish to `tasks.deadletter`
  - Store failure metadata in Postgres for operator review
- Run management:
  - Create Run record per attempt
  - Step recording (step_id, step_type, status, idempotency_key, input_ref, output_ref)
- OpenTelemetry spans for all state transitions

**Acceptance:** Full task lifecycle works end-to-end. Subagent spawning respects limits. Timeout and cancellation propagate correctly. Dead-letter queue receives poison messages after N retries.

---

### B-003: Policy Evaluator service
**Size:** XL
**Blocked-by:** A-002, A-004, A-006, A-007
**Language:** Go
**Deliverables:**
- OIDC authentication integration:
  - Token validation (configurable issuer)
  - Claims extraction (sub, groups, email)
- LDAP group resolution:
  - Direct LDAP query service OR IdP group claims passthrough
  - Cache with configurable TTL
  - Role mapping: `operator`, `agent-owner`, `auditor`, `infra-admin`
- SPIFFE authentication for service-to-service calls:
  - SVID validation
  - SPIFFE ID → service identity mapping
- Two-layer policy evaluation (RFC-002 §6):
  - OrgPolicy: admin-controlled hard guardrails
  - AgentPolicy: must be strict subset of OrgPolicy
  - Intersection logic: result = OrgPolicy ∩ AgentPolicy
- CapabilityGrant creation:
  - Evaluate agent + task context → produce signed CapabilityGrant
  - Contents: allowed tools, model classes, memory layers, sandbox profile, quotas, expiry
  - Store in Postgres, return grant_id
- AgentDefinition loading:
  - Read from Git-backed store (or Postgres cache synced from Git)
  - Validate against OrgPolicy
- SubagentTemplate enforcement:
  - max_depth, max_concurrent_children, max_wall_time, max_cost
  - Tool allowlist subsetting
  - Memory sharing rules
- gRPC/NATS API for other services to request:
  - `EvaluateCapability(agent_id, task_context) -> CapabilityGrant`
  - `ValidateAction(grant_id, action) -> allow/deny`
- Break-glass workflow support:
  - Time-bounded (4h) elevated grants
  - Dual approval required
  - Full audit logging

**Acceptance:** CapabilityGrants are correctly computed from the intersection of org and agent policy. Invalid escalations are denied. Break-glass produces audited elevated grants. OIDC and SPIFFE auth both work.

---

### B-004: Loop Runner service
**Size:** XL
**Blocked-by:** A-002, A-003, B-002, B-003, D-001, E-001
**Language:** Python
**Deliverables:**
- NATS consumer subscribing to `tasks.dispatch`
- Default agent loop implementation:
  1. Receive dispatched Task with CapabilityGrant
  2. Load agent context (AgentDefinition, session history from memory)
  3. Search memory (L0→L1→L2 by default, filtered by grant)
  4. Call Model Router (`router.request`) with context + memory hits
  5. Parse model response for tool calls
  6. Execute tool calls via Tool Protocol (`tools.{tool_id}.call`)
  7. Loop if model requests more tool calls (with budget enforcement)
  8. Produce final response
  9. Write to memory (L0 scratch, optionally L1)
  10. Send response via connector egress
- LoopSpec execution engine (RFC-005 §7.5):
  - Parse declarative LoopSpec YAML
  - State machine execution with model/tool/memory nodes
  - Validate against JSON Schema
- Budget enforcement per-run:
  - Max tokens (counted across all model calls)
  - Max tool calls
  - Max wall time
  - Halt loop and fail gracefully on budget exceeded
- Step recording:
  - Emit `tasks.run.step.started` / `tasks.run.step.completed` events
  - Record each Step in Postgres with idempotency_key
- Approval wait handling:
  - When a tool/action requires approval, transition task to WAITING_APPROVAL
  - Resume on approval event
- Connector egress:
  - Publish response to `egress.<connector_type>.message` (or reply to originating connector)
  - Default: reply to same channel; configurable override to common channel
- OpenTelemetry spans: loop_iteration, model_call, tool_call, memory_search, connector_send

**Acceptance:** A message entering via a connector produces a model-generated response sent back to the same channel. Multi-step tool use works. Budget limits halt execution gracefully. LoopSpec-defined custom loops execute correctly.

---

## Track C: Model Router and Budget

### C-001: Model Router service
**Size:** XL
**Blocked-by:** A-002, A-003, A-006
**Language:** Python
**Deliverables:**
- NATS consumer on `router.request`, publisher on `router.completed` / `router.failed`
- Dynamic model registration:
  - REST API: `POST /v1/models/register`, `GET /v1/models`, `DELETE /v1/models/{id}`
  - Model record: id, provider, model_name, endpoint, context_length, cost_per_token (input/output), locality (local/cloud), size_class (small/medium/large), capabilities, privacy_class, status
  - Stored in Postgres
  - Auto-discovery for local models (probe vLLM/llama.cpp health endpoints)
- Routing engine (RFC Architecture Response §10):
  - Input: request context (privacy tags, budget remaining, task complexity hint, latency requirement, context length needed)
  - Routing priority: privacy → cost → quality → latency → context length
  - Output: selected model + provider + endpoint
- Fallback chain (default by size and locality):
  1. Smallest local model that meets context/capability requirements
  2. Larger local model
  3. Smallest cloud model (if privacy allows)
  4. Larger cloud model
  - Configurable override per agent via policy tags
- Provider abstraction layer:
  - OpenAI-compatible API client (covers OpenAI, vLLM, most local servers)
  - Anthropic API client
  - llama.cpp client (if different from OpenAI-compat)
  - Streaming support (SSE) for interactive chat
- Request/response proxying:
  - Accept router.request, select model, call provider, emit router.completed
  - Include token usage in response metadata
  - Emit `router.metrics` with latency, tokens, cost, model used
- Error handling:
  - On provider error, attempt next model in fallback chain
  - Emit `router.failed` after all fallbacks exhausted
  - Circuit breaker per provider (configurable threshold)
- Policy gating enforcement:
  - Respect CapabilityGrant model restrictions
  - Block sensitive data from cloud providers
- Budget check before dispatch:
  - Query Budget Accounting service for remaining budget
  - Reject with `router.budget.alert` if hard limit reached
  - Warn (but proceed) if soft limit reached

**Acceptance:** Requests are routed to the correct model based on policy. Fallback works when a provider is down. Privacy-tagged requests never route to cloud. Budget limits are respected. New models can be registered dynamically and are immediately available for routing.

---

### C-002: Budget Accounting service
**Size:** L
**Blocked-by:** A-002, A-003, A-004
**Language:** Python
**Deliverables:**
- REST API:
  - `GET /v1/budgets` — list all budgets (filterable by scope: tenant/agent)
  - `GET /v1/budgets/{id}` — single budget with current spend
  - `GET /v1/budgets/{id}/breakdown` — by-model and by-provider cost breakdowns
  - `POST /v1/budgets` — create budget
  - `PATCH /v1/budgets/{id}` — update limits
  - `POST /v1/budgets/{id}/record` — record a spend event
  - `GET /v1/budgets/{id}/check` — check remaining budget (for router pre-check)
- NATS consumer on `router.metrics`:
  - Extract token usage + model + provider + cost
  - Atomically increment `spend_today` and `spend_month` in Postgres
  - Emit `router.budget.alert` if soft threshold (80%) or hard threshold (100%) crossed
- Budget scopes:
  - Per-tenant (aggregate)
  - Per-agent (granular)
  - Optional per-task (for subagent cost control)
- Cost breakdowns (stored in a `budget_transactions` table):
  - By model: each model's total tokens + cost
  - By provider: each provider's total tokens + cost
  - Time series: hourly/daily aggregates for charting
- Daily/monthly rollover:
  - Scheduled job resets `spend_today` at midnight (tenant timezone)
  - Scheduled job resets `spend_month` on 1st of month
- API designed for UI consumption (dropdown-friendly: labels, summaries, charts data)
- OpenTelemetry metrics: active budgets, total spend, alert count

**Acceptance:** Every model call's cost is recorded within seconds. Budget check returns accurate remaining balance. Alerts fire at 80% and 100%. Breakdown API returns correct per-model and per-provider data. Daily reset works correctly across timezones.

---

## Track D: Memory Plane

### D-001: Memory Plane service (L0-L2)
**Size:** XL
**Blocked-by:** A-002, A-003, A-004, A-005, D-002
**Language:** Python
**Deliverables:**
- Write API (`POST /v1/memory/write`):
  - Accept Markdown + YAML frontmatter document
  - Validate frontmatter schema (RFC-003 §5.1: id, layer, tenant_id, agent_id, title, sensitivity, retention, source, integrity)
  - DLP scan via DLP Scanner service (block/redact/allow)
  - Store in MinIO at canonical path (RFC-003 §6.2)
  - Compute and store SHA-256 integrity hash
  - Emit `memory.write.completed` event
  - Trigger `memory.index.request`
  - Idempotency key dedup
  - Optimistic concurrency via `expected_sha`
- Read API (`GET /v1/memory/{id}`):
  - Retrieve from MinIO
  - Enforce layer access from CapabilityGrant
  - Enforce sensitivity filtering
  - Audit log for sensitive layer reads
- Search API (`POST /v1/memory/search`):
  - Inputs: query, layers[], filters (tags, sensitivity, time range), k
  - Hybrid retrieval: BM25 lexical + vector semantic + reranking
  - Provenance in results: uri, line_start, line_end, sha256, excerpt
  - p95 < 500ms target
  - Respect CapabilityGrant layer restrictions
  - Sensitivity-filtered results
- Promote/Demote APIs:
  - `POST /v1/memory/promote` (L0→L1 heuristic, L1→L2 explicit)
  - `POST /v1/memory/demote`
  - Emit events on transitions
- Tier enforcement (Phase 1: L0-L2 only):
  - L0: session-scoped, 24h retention, hot storage
  - L1: agent-private, 7d retention, hot storage
  - L2: agent-private, 90d or 10MB/agent, warm storage
  - No cross-agent reads of L2 (strict)
- Sensitivity tag enforcement:
  - `public`, `internal`, `sensitive`, `restricted`
  - Input to model router gating and retrieval filtering
- Local embedding model:
  - sentence-transformers/all-MiniLM-L6-v2 (default)
  - Pluggable interface for future model swaps
  - Embedding computed on write and stored alongside document
- Indexer:
  - BM25 index (SQLite-based or Postgres tsvector)
  - Vector index (pgvector or FAISS/Hnswlib for hot cache)
  - Provenance line-map: byte offsets → line numbers per document
  - Incremental updates on write (not full rebuild)
- Reranker:
  - Cross-encoder reranking stage on top-N candidates
  - Local model (cross-encoder/ms-marco-MiniLM-L-6-v2 or similar)
- Retention enforcement:
  - Background job: delete expired L0/L1 documents
  - L2 size enforcement per agent

**Acceptance:** Write → Search roundtrip works with provenance. DLP blocks PII writes. Sensitivity filtering works. Retrieval p95 < 500ms on 10K documents. Cross-agent L2 reads are denied.

---

### D-002: DLP Scanner service (mydlp integration)
**Size:** L
**Blocked-by:** A-001, A-003
**Language:** Python
**Deliverables:**
- mydlp/mydlp deployment (Helm chart + Compose service)
- Orchestack DLP gateway service:
  - REST API: `POST /v1/dlp/scan`
  - Input: content (text/markdown), context (source, destination, sensitivity_class)
  - Output: verdict (allow/redact/block), findings[], redacted_content (if applicable)
- Integration points:
  - Memory writes (called by Memory Plane before storage)
  - Outbound connector messages (called by Loop Runner before egress)
  - Payment metadata (called by Payments Service before onchain submission) [Phase 2]
- Pattern detection (configure mydlp for):
  - Common PII (SSN, email, phone, credit card)
  - PHI patterns (medical record numbers, diagnosis codes)
  - API keys / secrets (common formats)
  - Custom patterns (configurable via policy)
- Actions per policy:
  - `allow` — pass through
  - `redact` — replace detected content with `[REDACTED]` and proceed
  - `block` — reject the operation
  - `escalate` — create ApprovalRequest for human review
- Audit record for every scan (pass or fail), inputs hashed
- NATS event emission for blocks/escalations

**Acceptance:** PII patterns detected and blocked/redacted. Memory writes with PII are rejected. Outbound messages with PII are caught. Audit records created for every scan.

---

## Track E: Execution Plane

### E-001: Daytona Executor service
**Size:** XL
**Blocked-by:** A-002, A-003, A-005, A-006, E-002
**Language:** Go
**Deliverables:**
- Daytona API client library (Go):
  - Sandbox creation/destruction
  - Command execution
  - File upload/download
  - Network policy configuration
- Sandbox lifecycle management:
  - Ephemeral (default): create on task start, destroy on task end
  - Persistent (opt-in): create on agent activation, persist across tasks
  - Cleanup job for orphaned sandboxes
- Resource cordon enforcement (RFC-002 §8.2):
  - CPU: 0.5-4 cores per sandbox
  - Memory: 512MB-8GB
  - Disk: 10GB default
  - Network: rate-limited egress
  - Max concurrent: 20 per agent
- Network egress policy:
  - Deny-all default
  - Per-agent allowlist (domain/IP) from AgentPolicy
  - Audit log for all egress connections
- Filesystem policy:
  - No direct host mounts
  - Read-only reference volumes (platform-managed)
  - Secrets injected via Vault/ESO (short-lived)
  - Config via ConfigMaps
- Tool execution:
  - NATS consumer on `tools.{tool_id}.call` (for sandbox tools)
  - Fetch tool bundle from object storage, verify checksum
  - Extract into sandbox workspace
  - Execute with timeout
  - Capture stdout/stderr, store as artifacts
  - Return result on NATS reply subject
- Idempotency:
  - Accept idempotency key per execution
  - Return cached result on duplicate
- Sandbox image management:
  - Images pinned by digest (RFC-002 §8.2)
  - Centrally curated image list
  - Runtime class toolkits: code (IDE tools), research (web + memory tools), infra (kubectl + terraform)
- OpenTelemetry spans: sandbox_create, tool_execute, sandbox_destroy

**Acceptance:** Sandbox creation < 30s. Tool execution works end-to-end. Egress deny-all blocks unauthorized network access. Resource limits enforced. Idempotent re-execution returns cached result.

---

### E-002: Daytona self-hosted deployment
**Size:** M
**Blocked-by:** A-001
**Deliverables:**
- Research and pin latest open-source Daytona release
- Helm chart for Daytona Server (OpenShift-compatible)
- Docker Compose service definition for local dev
- Storage backend configuration (PVC for K8s, local volume for Podman)
- Network configuration for sandbox egress control
- Base sandbox images:
  - `orchestack-sandbox-code`: Python 3.12+, Node 22+, Go 1.23+, git, common CLIs
  - `orchestack-sandbox-research`: Python 3.12+, browser automation tools, curl
  - `orchestack-sandbox-infra`: kubectl, oc, terraform, ansible
- Image build pipeline (Containerfiles, pinned by digest)
- Health check and monitoring

**Acceptance:** Daytona Server running. Sandboxes can be created from all three base images. Sandboxes are destroyed after use.

---

## Track F: Connectors

### F-001: Connector framework and common message format
**Size:** L
**Blocked-by:** A-002, A-003, A-004
**Language:** Python
**Deliverables:**
- Common normalized message format (RFC-001 ingress):
  ```python
  class NormalizedMessage:
      message_id: str          # connector-specific original ID
      connector_type: str      # discord, slack, email, telegram, webchat
      connector_account_id: str
      thread_id: str           # channel/thread/conversation identifier
      sender_id: str           # connector-specific sender ID
      sender_display_name: str
      content: str             # normalized text content
      attachments: list[AttachmentRef]  # refs to objects in MinIO
      timestamp: datetime
      reply_to: str | None     # if this is a reply
      extra: dict              # connector-specific fields
  ```
- Connector base class (Python):
  - `connect()` — establish connection to platform
  - `listen()` — receive messages, normalize, publish to `ingress.<type>.message`
  - `send(channel, message)` — send reply to platform
  - `map_identity(sender_id) -> OrchestackIdentity` — lookup
  - Health check / heartbeat
  - Reconnection with exponential backoff
  - Graceful shutdown
- Identity mapping service (Ansible AAP-style):
  - Lookup table: `(connector_type, connector_sender_id) → (oidc_sub, ldap_groups[])`
  - REST API for managing mappings: `POST /v1/identity-mappings`, `GET`, `DELETE`
  - Postgres-backed
  - Fallback: unknown senders get `anonymous` role with minimal permissions
- Egress routing:
  - Default: reply to same channel (connector_type + thread_id from originating message)
  - Configurable: route to a common/designated channel per agent
  - NATS consumer on `egress.<connector_type>.message`
- Attachment handling:
  - Upload attachments to MinIO on ingress
  - Download from MinIO and attach on egress
  - Size limit enforcement (10MB max per RFC Architecture Response)
- Token management:
  - Load tokens from Vault via ESO
  - Token refresh heartbeat (before expiry)
- OpenTelemetry spans: message_received, message_normalized, message_sent

**Acceptance:** Base class is instantiable. Identity mapping works. Normalized messages conform to schema. Attachments stored and retrieved from MinIO.

---

### F-002: Discord connector
**Size:** M
**Blocked-by:** F-001
**Language:** Python
**Deliverables:**
- Long-running service using discord.py or equivalent
- Gateway connection with intent configuration
- Message reception → NormalizedMessage → NATS publish
- Thread/channel mapping to session_id
- Reply sending (text, embeds, file attachments)
- Slash command support (optional v1)
- Rate limit handling (Discord API limits)
- Reconnection logic
- Multi-guild support

**Acceptance:** Bot joins configured Discord server. Messages in designated channels create ingress events. Responses appear in the same channel. Attachments work both directions.

---

### F-003: Slack connector
**Size:** M
**Blocked-by:** F-001
**Language:** Python
**Deliverables:**
- Long-running service using Slack Bolt SDK
- Socket Mode (preferred) or Events API
- Message reception → NormalizedMessage → NATS publish
- Channel/thread mapping to session_id
- Reply sending (text, blocks, file uploads)
- App mention handling
- Rate limit handling
- Workspace installation flow

**Acceptance:** Bot responds in Slack channels/threads. Messages create ingress events. Responses appear in the correct thread.

---

### F-004: Email connector (SMTP/IMAP)
**Size:** M
**Blocked-by:** F-001
**Language:** Python
**Deliverables:**
- IMAP polling service for inbound email
- SMTP client for outbound email
- Email → NormalizedMessage mapping:
  - Subject + body → content
  - Attachments → MinIO refs
  - Thread-ID / In-Reply-To → session threading
- Reply construction (proper email threading headers)
- HTML → Markdown conversion for ingress
- Markdown → HTML for egress
- TLS configuration
- Multiple mailbox support

**Acceptance:** Emails to configured address create ingress events. Responses sent as properly-threaded email replies.

---

### F-005: Telegram connector
**Size:** M
**Blocked-by:** F-001
**Language:** Python
**Deliverables:**
- Long-running service using python-telegram-bot or Telethon
- Bot API with long polling or webhook mode
- Message reception → NormalizedMessage → NATS publish
- Chat/group mapping to session_id
- Reply sending (text, markdown, media)
- Inline keyboard support (for approval workflows)
- Rate limit handling
- Group and private chat support

**Acceptance:** Bot responds in Telegram chats. Messages create ingress events. Responses appear in the correct chat.

---

### F-006: Webchat connector
**Size:** L
**Blocked-by:** F-001
**Language:** Python (backend), TypeScript (frontend)
**Deliverables:**
- WebSocket-based chat backend service
- REST API for session management
- Simple embeddable chat widget (TypeScript/HTML/CSS):
  - Message input + display
  - Streaming response display
  - File upload
  - Session persistence (localStorage token)
- Authentication:
  - Anonymous mode (rate-limited)
  - OIDC-authenticated mode
- Message reception → NormalizedMessage → NATS publish
- Response streaming via WebSocket
- CORS configuration
- Rate limiting

**Acceptance:** Chat widget loads in browser. Messages create ingress events. Responses stream back in real-time. OIDC login works.

---

## Track G: Extensibility Framework

### G-001: Extension Manifest schema and validation CLI
**Size:** M
**Blocked-by:** A-001
**Language:** Python
**Deliverables:**
- JSON Schema for `extension.yaml` (RFC-005 §6.1):
  - apiVersion, kind, metadata, spec
  - All extension types: tool, skill, memory, storage, loop, schedule, connector
  - Trust tiers (0-3) with validation rules per tier
  - Security section (signing, SBOM, vuln scan, secrets, network)
  - Interfaces section (per type)
  - Artifacts section (OCI images, bundles)
- `orchestack-ext` CLI tool:
  - `orchestack-ext lint <path>` — validate extension.yaml against schema
  - `orchestack-ext init <type>` — scaffold a new extension from template
  - `orchestack-ext build` — build OCI image from extension package
  - `orchestack-ext sign` — sign with cosign (Vault-backed keys)
  - `orchestack-ext verify` — verify signature
- Scaffolding templates for each extension type:
  - Tier 0 skill template
  - Tier 1 sandbox tool template
  - Tier 0 schedule template
  - Tier 2 service template
- Python SDK for extension authors:
  - Tool descriptor helpers
  - Skill spec builder
  - Schema validation utilities

**Acceptance:** `orchestack-ext lint` correctly validates/rejects extension manifests. `orchestack-ext init skill` produces a valid scaffold. All example extensions from RFC-005 §13 validate.

---

### G-002: Extension Controller (GitOps reconciliation)
**Size:** L
**Blocked-by:** A-003, A-004, G-001
**Language:** Go
**Deliverables:**
- Git repository watcher:
  - Monitor extensions directory in Git for changes
  - Detect new/updated/removed extension packages
- Reconciliation loop:
  - Parse and validate `extension.yaml`
  - Verify signatures (cosign)
  - Check trust tier requirements (approval status)
  - For Tier 1 (sandbox): store bundle in object storage
  - For Tier 2/3 (service): deploy as K8s Deployment or Podman container
  - For Tier 0 (declarative): register specs directly
- Extension Registry population:
  - Insert/update records in Postgres
  - Store tool descriptors, skill specs, etc.
  - Emit `ext.installed`, `ext.updated`, `ext.disabled` events on NATS
- Rollback support:
  - Track previous versions
  - On failure, revert to last known good
- Platform abstraction:
  - K8s mode: create/update Deployments, Services, NetworkPolicies
  - Podman mode: manage systemd units and podman containers
- SBOM storage and vulnerability scan gate:
  - Store SBOM artifacts
  - Block installation if CVSS > threshold (from manifest)
- Dashboard/status API:
  - `GET /v1/extensions` — list installed extensions with status
  - `GET /v1/extensions/{id}` — detail with drift status

**Acceptance:** Merging an extension to Git triggers installation in the cluster. Extension appears in the registry. Unsigned extensions are rejected. Rollback works on deployment failure.

---

### G-003: Tool Protocol (OTP) implementation
**Size:** M
**Blocked-by:** A-002, A-003, G-001
**Language:** Python + Go
**Deliverables:**
- Tool descriptor schema (RFC-005 §7.1.1):
  - tool_id, name, description, input_schema, output_schema
  - Risk class, idempotency behavior, required capabilities, data classification, audit level
- NATS request/reply implementation:
  - Subject: `tools.{tool_id}.call`
  - Request envelope with idempotency_key, capability_grant_id, trace_id
  - Response envelope with result or error
  - Timeout handling
- HTTP/gRPC adapter (for Podman mode):
  - HTTP endpoint that proxies to NATS or calls tools directly
  - gRPC service definition (protobuf)
- Tool discovery API:
  - `GET /v1/tools` — list all registered tools with descriptors
  - `GET /v1/tools/{tool_id}` — single tool descriptor
  - Backed by Extension Registry
- Built-in tool set (Phase 1 minimum):
  - `shell.exec` — execute shell command in sandbox
  - `file.read` / `file.write` — sandbox filesystem operations
  - `git.clone` / `git.commit` / `git.create_pr` — git operations
  - `http.fetch` — HTTP request (through sandbox egress policy)
  - `memory.search` / `memory.write` — memory plane operations
  - `web.search` — web search (via configured provider)

**Acceptance:** Tools can be called via NATS request/reply. Built-in tools work in Daytona sandboxes. Tool descriptors are discoverable. HTTP adapter works for Podman mode.

---

### G-004: Skill specification runtime
**Size:** M
**Blocked-by:** B-004, G-003
**Language:** Python
**Deliverables:**
- Skill spec parser (RFC-005 §7.2):
  - Parse YAML skill definitions
  - Validate: no executable code, only references to tool_ids and model router
  - Parameter validation against JSON Schema
- Step execution engine:
  - Sequential step execution: `memory.search` → `model.call` → `tool.call`
  - Parameter template interpolation
  - Result passing between steps
  - Guardrails enforcement (required approvals, citations, DLP mode)
- Skill registry integration:
  - Load skills from Extension Registry
  - Validate at registration time
- Built-in skills (Phase 1 examples):
  - `code.review` — search memory for context, call model for code review, create PR comment
  - `incident.triage` — search L3 runbooks, analyze incident, produce plan

**Acceptance:** Declarative skills execute correctly. Steps chain results. Guardrails are enforced. Invalid skills (with embedded code) are rejected at registration.

---

### G-005: Schedule Spec compiler
**Size:** M
**Blocked-by:** A-003, G-001
**Language:** Python
**Deliverables:**
- ScheduleSpec parser (RFC-005 §7.6):
  - Cron expression + timezone
  - Concurrency policy (single-flight / allow overlap)
  - Missed-run policy (catch-up / skip)
  - Task template (what to enqueue on NATS)
  - Idempotency key strategy
- Compiler backends:
  - Kubernetes CronJob manifest generator
  - cron/systemd timer generator (for Podman mode)
- Built-in schedules:
  - Health check (30s interval — uses K8s liveness/readiness, not CronJob)
  - Memory compaction (daily 2am)
  - Index refresh (hourly)
  - Infra reconciliation (every 5min)
  - Token refresh (before expiry)
  - Retention cleanup (daily: L0 24h, L1 7d, L2 90d)
  - Audit export to object storage (daily)
  - Budget daily reset (midnight per tenant TZ)

**Acceptance:** ScheduleSpecs produce valid CronJob manifests and cron entries. Built-in schedules are deployed and trigger correctly.

---

## Track H: Observability and Audit

### H-001: OpenTelemetry integration library
**Size:** M
**Blocked-by:** A-001
**Language:** Python + Go
**Deliverables:**
- Shared OTEL configuration library:
  - Trace exporter (OTLP → Jaeger/Tempo)
  - Metrics exporter (OTLP → Prometheus)
  - Log exporter (OTLP → Loki, optional)
- NATS trace propagation:
  - W3C `traceparent` / `tracestate` as NATS headers
  - Auto-instrumentation for NATS publish/consume
- Required span instrumentation for every service:
  - ingest, state_transition, router_call, tool_execution, memory_op, connector_egress
- Python library (`orchestack-telemetry`):
  - FastAPI middleware for auto-tracing
  - NATS consumer/producer instrumentation
  - Postgres query tracing
- Go library (`telemetry`):
  - Similar instrumentation for Go services
- Deployment:
  - Jaeger or Grafana Tempo Helm chart
  - Prometheus + Grafana Helm chart
  - Pre-built Grafana dashboards for Orchestack services

**Acceptance:** End-to-end trace visible from connector ingress through to connector egress. Metrics available in Prometheus. Dashboard shows service health.

---

### H-002: Audit pipeline and retention
**Size:** M
**Blocked-by:** A-003, A-005, H-001
**Deliverables:**
- Audit event producer library:
  - Emit `audit.toolcall` for every tool call Step
  - Emit `audit.approval` for every approval decision
  - Contents: step metadata, hashed inputs, hashed outputs + truncated preview, sandbox identity, actor identity
  - Secrets automatically redacted
- STREAM_AUDIT consumer → Postgres audit table:
  - Queryable audit log
  - Full-text search on previews
- Retention pipeline:
  - 90 days hot in Postgres
  - Export to MinIO (warm) after 90 days
  - Cold storage after 1 year (compressed, in MinIO with lifecycle rules)
  - 7-year cold retention
- Export job (scheduled):
  - Daily export of audit records older than retention threshold
  - Parquet or JSON-lines format in object storage
- Operator inspection API:
  - `GET /v1/audit/events` — query audit log with filters
  - `GET /v1/audit/deadletter` — inspect dead-letter queue
  - `POST /v1/audit/deadletter/{id}/retry` — retry a dead-letter message
  - `POST /v1/audit/deadletter/{id}/discard` — discard

**Acceptance:** Every tool call produces an audit record. Records are queryable. Retention export runs on schedule. Dead-letter queue is inspectable and retryable.

---

## Track I: Deployment and CI/CD

### I-001: Kubernetes Operator
**Size:** XL
**Blocked-by:** all service tracks (can start scaffold early, finish after services exist)
**Language:** Go (kubebuilder)
**Deliverables:**
- Custom Resource Definitions:
  - `Orchestack` — top-level CR that declares desired state for the full platform
  - `OrchestackAgent` — per-agent CR (maps to AgentDefinition)
  - `OrchestackConnector` — per-connector CR
  - `OrchestackExtension` — per-extension CR
- Reconciliation controllers:
  - Deploy all infrastructure (NATS, Postgres, MinIO, Vault config, SPIRE)
  - Deploy all Orchestack services with correct configuration
  - Manage secrets via ESO
  - Manage network policies
  - Rolling updates with health checks
- OpenShift compatibility:
  - SecurityContextConstraints
  - Route objects (instead of Ingress)
  - Image stream support
- Status reporting:
  - CR status reflects deployment health
  - Events for significant state changes
- OLM (Operator Lifecycle Manager) bundle for OpenShift marketplace

**Acceptance:** Applying an `Orchestack` CR on a fresh OpenShift cluster deploys the full platform. Status reflects health. Updates roll out without downtime.

---

### I-002: Tekton pipeline definitions
**Size:** M
**Blocked-by:** A-001
**Deliverables:**
- Tekton Tasks:
  - `lint` — run linters for Go, Python, TypeScript
  - `test-unit` — run unit tests per service
  - `test-integration` — run integration tests (requires dev stack)
  - `build-image` — build OCI image per service
  - `scan-vuln` — vulnerability scan (Trivy or Grype)
  - `generate-sbom` — SBOM generation (Syft)
  - `sign-image` — cosign signing with Vault keys
  - `atlas-migrate` — run Atlas schema migrations
  - `ext-lint` — validate extension manifests
- Tekton Pipelines:
  - `pr-check` — lint + unit test + ext-lint (runs on PR)
  - `build-and-deploy` — full build → scan → sign → deploy (runs on merge)
  - `release` — tagged release pipeline
- TriggerTemplates and EventListeners for webhook integration

**Acceptance:** PR triggers lint + test. Merge triggers build + deploy to staging. Images are signed and SBOMs attached.

---

### I-003: GitLab CI and GitHub Actions templates
**Size:** S
**Blocked-by:** I-002 (port from Tekton definitions)
**Deliverables:**
- `.gitlab-ci.yml` with equivalent stages:
  - lint, test, build, scan, sign, deploy
  - Uses shared runners or self-hosted
- `.github/workflows/ci.yml` with equivalent jobs
- Shared scripts in `deploy/ci/scripts/` used by all three CI systems
- Documentation on configuring each CI system

**Acceptance:** Same test/build/deploy flow works on all three CI systems.

---

# PHASE 2 — Enterprise + Onchain (after Phase 1 core is validated)

## Track J: Memory Plane L3/L4 and Advanced Features

### J-001: Memory Plane L3 (shared, curated) and L4 (archive)
**Size:** XL
**Blocked-by:** D-001 (Phase 1 memory)
**Deliverables:**
- L3 shared tier:
  - Team/org-scoped shared memory
  - Read access controlled by LDAP groups via CapabilityGrant
  - Write requires curation approval workflow:
    - `POST /v1/memory/promote` from L2→L3 creates ApprovalRequest
    - Approval triggers Git commit to L3 repo
  - Git-backed source of truth:
    - L3 documents stored as Git repository
    - Sync job mirrors Git repo → MinIO for uniform retrieval
    - Git operations (commit, PR, merge) for all L3 mutations
- L4 archive tier:
  - Read-only for most agents
  - Only system/curator roles can write
  - Compressed storage (gzipped Markdown)
  - Git repo snapshot bundles stored in MinIO
- Compaction API (`POST /v1/memory/compact`):
  - Scheduled daily at 2am
  - L2→L3: generate curation suggestions (model-assisted summarization)
  - L3→L4: archive + compress aged documents
  - Returns report + created PRs/artifacts
- Cross-team access:
  - L3 read access per team (LDAP group scoped)
  - No cross-team L3 writes without explicit approval
- Retention enforcement:
  - L3: 1 year or 100MB per team
  - L4: indefinite, compressed
- Updated indexer to cover L3/L4 documents

**Acceptance:** L3 curation workflow works end-to-end (propose → approve → Git commit → available in search). L4 archival compresses and stores correctly. Git history is browsable.

---

## Track K: System Agents and Approval Workflows

### K-001: Approval workflow engine
**Size:** L
**Blocked-by:** B-002, B-003, F-001
**Deliverables:**
- ApprovalRequest lifecycle:
  - Created by Task Dispatcher or Loop Runner when action requires approval
  - Status: pending → approved/denied/expired
  - Configurable expiry (default 1 hour)
  - Notification via connector (send approval prompt to designated channel/user)
- Approval interface:
  - Connector-based: react to message (Discord reaction, Slack button, Telegram inline keyboard)
  - REST API: `POST /v1/approvals/{id}/approve` / `POST /v1/approvals/{id}/deny`
- Dual approval support (for break-glass):
  - Configurable: 1 or 2 approvers required
  - Different approver groups per action type
- Timeout handling:
  - Expired approvals transition task to TIMED_OUT or CANCELLED
- Resume on approval:
  - Emit event → Task Dispatcher transitions WAITING_APPROVAL→RUNNING
  - Loop Runner resumes from waiting step

**Acceptance:** High-risk tool calls pause for approval. Approval via connector resumes the task. Expired approvals cancel the task. Break-glass requires dual approval.

---

### K-002: System agent framework
**Size:** L
**Blocked-by:** B-004, K-001, E-001
**Deliverables:**
- System agent base configuration:
  - Runtime class: `infra`
  - Sandbox profile: `orchestack-sandbox-infra` (kubectl, oc, terraform, ansible)
  - Default policy: propose-only (PRs/manifests)
  - Auto-apply allowlist: restarts, non-destructive reconciliations
  - Destructive actions: human approval required
- Infrastructure surfaces:
  - OpenShift/K8s resources (via kubectl/oc in sandbox)
  - Nodes (via SSH/Ansible in sandbox)
  - Networking (DNS/LB management)
  - Storage systems
- Runbook integration:
  - L3 memory as cache, Git as source of truth
  - Sync job: Git commit → L3 update
  - System agent reads runbooks from L3
- Reconciliation agent template:
  - Scheduled every 5min via ScheduleSpec
  - Check cluster state vs desired state
  - Auto-remediate non-destructive drift
  - Propose PR for destructive drift
- Report generation:
  - Health reports
  - Drift reports
  - Cost reports

**Acceptance:** System agent detects configuration drift. Non-destructive remediation auto-applies. Destructive changes create PRs requiring approval.

---

## Track L: Onchain Trust and Payments (RFC-004)

### L-001: Payments Service (x402 buyer mode)
**Size:** XL
**Blocked-by:** A-002, A-003, A-004, A-006, B-003
**Language:** Python
**Deliverables:**
- PaymentIntent lifecycle management:
  - Create from HTTP tool 402 response
  - Status: created → approved → signed → verified → settled / failed / cancelled / expired
  - Idempotency key per intent
  - Store requirements_ref, amount_max, asset, network in Postgres
- Policy validation:
  - Check `can_x402_buy` capability
  - Endpoint domain allowlist check
  - Per-request amount cap check
  - Daily budget check (via Budget Accounting)
  - Sensitivity tag check
- Approval flow (when `can_x402_autopay` not granted):
  - Create ApprovalRequest
  - Wait for human approval
- Integration with Wallet Signer (L-002) for PAYMENT-SIGNATURE generation
- Facilitator integration (L-003) for verify/settle
- HTTP retry flow:
  - After signing, resubmit original request with PAYMENT-SIGNATURE header
  - Parse PAYMENT-RESPONSE header
  - Store settlement details (PaymentSettlement entity)
- NATS events: `payments.x402.intent.*` subjects
- Object storage artifacts: requirements, signatures, responses
- Correlation: task_id ↔ payment_intent_id ↔ tx_hash
- API:
  - `GET /v1/payments` — list intents
  - `GET /v1/payments/{id}` — detail with settlement
  - `POST /v1/payments/intents` — create (internal, from HTTP tool)

**Acceptance:** Agent hits 402 endpoint → PaymentIntent created → policy checked → signed → settled → original resource body returned to agent. Payment proof linked to Task.

---

### L-002: Wallet Signer (Vault-backed)
**Size:** L
**Blocked-by:** A-006
**Language:** Go
**Deliverables:**
- Key management:
  - Generate/import signing keys (secp256k1 for EVM)
  - Store encrypted in Vault (transit or KV)
  - Per-agent key isolation
  - Key rotation procedures
- Signing API (internal only, not exposed externally):
  - `POST /v1/signer/sign` — sign payload with specified key
  - Input: payload bytes, key reference, purpose tag
  - Output: signature
  - Key usage policy enforcement:
    - Rate limits per key
    - Allowlisted callers only (SPIFFE ID)
    - Per-agent budget check
- x402 PAYMENT-SIGNATURE generation:
  - Format per x402 spec
  - Include payment details, nonce, expiry
- ERC-8004 operation signing:
  - Transaction signing for register, setAgentWallet, giveFeedback
- Audit log: every signing operation recorded

**Acceptance:** Keys are generated and stored in Vault. Signing requests are authenticated via SPIFFE. Rate limits enforced. x402 signatures are valid.

---

### L-003: Facilitator Adapter (pluggable)
**Size:** M
**Blocked-by:** L-001
**Language:** Python
**Deliverables:**
- Adapter interface:
  - `verify(payment_payload, signature) -> VerifyResult`
  - `settle(payment_payload, signature) -> SettleResult`
- Implementations:
  - Coinbase CDP facilitator (hosted)
  - Self-hosted facilitator stub (for testing/air-gapped)
  - Local verify/settle (for dev/test, explicitly opt-in only)
- Configuration:
  - Facilitator selection per tenant/agent
  - Endpoint, auth credentials (Vault-backed)
- KYT (Know Your Transaction) result passthrough when facilitator provides it

**Acceptance:** Payment verification and settlement work through at least one facilitator. Adapter is swappable via configuration.

---

### L-004: Trust Service (ERC-8004 identity)
**Size:** L
**Blocked-by:** A-004, L-002
**Language:** Python
**Deliverables:**
- Agent registration file generation:
  - Generate `registration.json` per ERC-8004 spec
  - Include service endpoints, supportedTrust, x402Support
  - Store in object storage at stable URI
  - Optionally publish `.well-known/agent-registration.json`
- Onchain registration:
  - Call ERC-8004 Identity Registry `register(agentURI)` via Wallet Signer
  - Store `erc8004_agent_id` and registry address in `AgentOnchainIdentity` table
- AgentURI update:
  - Policy-gated (requires `can_erc8004_register`)
  - Audit logged
- Postgres entities:
  - `AgentOnchainIdentity` (agent_id, chain_namespace, chain_id, registry_address, erc8004_agent_id, agent_uri, agent_wallet, status)
- NATS events: `trust.erc8004.identity.published`
- API:
  - `POST /v1/trust/agents/{agent_id}/register` — register agent onchain
  - `GET /v1/trust/agents/{agent_id}/identity` — get onchain identity
  - `PATCH /v1/trust/agents/{agent_id}/identity` — update agentURI

**Acceptance:** Homarus agent registered on configured chain. Registration file published and retrievable. agentURI updatable under policy control.

---

### L-005: Onchain payment data model migration
**Size:** S
**Blocked-by:** A-004, L-001
**Deliverables:**
- Atlas migration adding RFC-004 §7.1 entities:
  - `agent_onchain_identities`
  - `payment_intents`
  - `payment_settlements`
  - `trust_signal_cache` (optional, can be empty table for now)
- Indexes for common queries (by task_id, by status, by agent_id)
- NATS stream additions:
  - Add `payments.>` and `trust.>` subject patterns to STREAM_EVENTS

**Acceptance:** Migration applies cleanly. Entities are usable by Payments and Trust services.

---

## Track M: Podman HA Mode

### M-001: Podman HA deployment stack
**Size:** L
**Blocked-by:** all core services
**Deliverables:**
- systemd unit files for each Orchestack service
- Podman pod definitions (or individual containers with shared network)
- systemd-based health monitoring and restart
- cron jobs (compiled from ScheduleSpecs)
- Equivalent security:
  - Podman network isolation (replacing K8s NetworkPolicy)
  - Secret management via Vault AppRole (no ESO in Podman mode)
  - Resource limits via Podman `--cpus`, `--memory`
- NATS, Postgres, MinIO as Podman containers
- Setup script: `orchestack-setup.sh` that bootstraps on a fresh Linux host
- Documentation: 3-5 node HA topology

**Acceptance:** `orchestack-setup.sh` on a fresh Linux host deploys the full stack. Services restart on failure. Security guarantees match K8s mode.

---

# Cross-Cutting Concerns (ongoing throughout)

## X-001: Integration test suite
**Size:** L (ongoing)
**Blocked-by:** A-008
**Deliverables:**
- Docker Compose-based test environment
- End-to-end test scenarios:
  - Message ingress → session creation → task dispatch → model call → tool execution → response egress
  - Subagent spawning and completion
  - Budget limit enforcement
  - Memory write/search/retrieve with provenance
  - Approval workflow (request → approve → resume)
  - Extension installation via GitOps
- NATS integration tests (message flow through all streams)
- Postgres integration tests (state machine transitions, idempotency)
- Performance benchmarks:
  - p95 first-chunk latency < 2s
  - p95 memory retrieval < 500ms
  - 100 concurrent sessions

**Acceptance:** All scenarios pass. Performance benchmarks met.

---

## X-002: Security hardening review
**Size:** M (gate before production)
**Blocked-by:** all core services
**Deliverables:**
- Network policy audit (zero-trust east-west verified)
- Secret audit (no secrets in logs, memory, or environment variables)
- NATS subject permission audit (each service only accesses its subjects)
- Container image audit (all pinned by digest, no root containers)
- DLP effectiveness audit (test with known PII/PHI patterns)
- Dependency vulnerability scan (all images, all language deps)
- SPIFFE/mTLS verification (all service-to-service encrypted)

**Acceptance:** No critical/high findings. All services run non-root. All connections encrypted.

---

## Summary: Suggested Execution Order

```
Week 1-2:   A-001, A-002, E-002, G-001, H-001, I-002 (foundation, in parallel)
Week 3-4:   A-003, A-004, A-005, A-006 (infrastructure, in parallel)
Week 5-6:   A-007, A-008, F-001, D-002 (infra completion + connector framework + DLP)
Week 7-10:  B-001, B-002, B-003, B-004 (orchestrator services, partially parallel)
Week 7-10:  C-001, C-002 (model router + budget, parallel with orchestrator)
Week 7-12:  D-001 (memory plane, parallel with orchestrator)
Week 8-12:  E-001 (Daytona executor, after E-002)
Week 9-12:  F-002 through F-006 (connectors, parallel after F-001)
Week 10-14: G-002, G-003, G-004, G-005 (extensibility, after core services)
Week 12-14: H-002, I-001, I-003 (audit, operator, CI templates)
Week 14:    X-001, X-002 (integration testing + security review)
            --- PHASE 1 REVIEW GATE ---
Week 15-18: J-001 (L3/L4 memory)
Week 15-18: K-001, K-002 (approval workflows + system agents)
Week 16-20: L-001 through L-005 (onchain, after Phase 1 stable)
Week 18-20: M-001 (Podman HA mode)
```

Total estimated timeline: ~20 weeks for full v1 with a Phase 1 review gate at ~14 weeks.
