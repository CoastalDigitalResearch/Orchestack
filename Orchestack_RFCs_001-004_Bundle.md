# RFC-001: Event and State Model (NATS + Postgres + Object Storage)

**Project:** Orchestack  
**Resident agent name:** Homarus  

**Status:** Draft (v1)  
**Last updated:** 2026-02-07  
**Source of requirements:** Architecture Response Document (repo copy: `Orchestack_Architecture_Response.md`; original: `Homarus_2.0_Architecture_Response.md`), dated 2026-02-06

## 1. Summary

This RFC defines the **event-driven backbone** and **authoritative state model** for Orchestack. The design is optimized for:

- **100+ concurrent agent sessions**
- **Per-session ordering** for chat continuity
- **At-least-once delivery** for tasks and critical events using **NATS JetStream**
- “Exactly-once effects” for state changes and external side effects using **idempotency keys**
- **Large payload offloading** to S3-compatible object storage (and/or NAS) with references carried in events

This RFC deliberately separates:
- **Transport and durability:** NATS JetStream
- **Authoritative state:** Postgres
- **Blob payloads:** object storage / NAS
- **Execution:** Daytona sandboxes (covered in RFC-002)



## 2. Goals

### 2.1 Goals (v1)

1. Define a stable **event envelope** and **subject taxonomy** for inter-service communication.
2. Define the **authoritative state entities** and relationships (Session, Task, Run, Step, Artifact, Approval, Budget).
3. Define **ordering guarantees** (per-session) and how they are enforced.
4. Define **idempotency** and deduplication rules across:
   - connector ingress/egress
   - tool execution
   - model router calls
   - memory writes
5. Define retry, dead-letter, and backpressure behavior for JetStream consumers.
6. Define trace propagation requirements for end-to-end OpenTelemetry.



### 2.2 Non-goals (v1)

- Global message ordering.
- Exactly-once delivery at the transport layer (we achieve exactly-once *effects* through idempotency).
- Hot-reload of connector plugins (deploy-time only v1).
- Multi-tenant isolation semantics beyond v1 single-tenant, but the schema must not block namespace-isolated multi-tenant v2.



## 3. Terminology

- **Tenant:** A top-level administrative boundary. v1 is single-tenant, but schemas include `tenant_id` for v2 readiness. 
- **Workspace:** Unit of ownership and data segregation inside a tenant; owned at the agent level. 
- **Agent:** A configured persona/runtime/tooling boundary.
- **Session:** A conversation or interaction thread (e.g., Discord channel thread, Slack DM thread).
- **Task:** A unit of work to be processed by orchestration/execution. Tasks can spawn sub-tasks (subagents).
- **Run:** One attempt to execute a Task.
- **Step:** A discrete action within a Run (model call, tool call, memory op, connector send).
- **Artifact:** A blob output (logs, transcripts, patches, screenshots) stored off NATS in object storage/NAS.
- **Idempotency key:** A deterministic key used to deduplicate external side effects.
- **Capability grant:** Policy-evaluated permission bundle attached to a task/run (defined in RFC-002).

## 4. System-level SLO targets (inputs to design)

- Interactive chat: **p95 < 2s** end-to-end for first meaningful response chunk. 
- Retrieval (memory search): **p95 < 500ms** (memory plane dependent). 
- Background tasks: **95% complete < 1 hour**. 

### 4.1 Clarifying metric definitions (recommended)

To align “sub-500ms response latency” with “p95 < 2s” for chat, we define:

- **T_ack:** time from connector receipt → system acceptance + session enqueue (target p95 < 500ms)
- **T_first_chunk:** time from connector receipt → first response chunk (target p95 < 2s)

These are measured separately.



## 5. Event envelope

All inter-service messages on NATS MUST conform to the following envelope. The envelope is intentionally small; large payloads are referenced via `payload_ref`.

### 5.1 Envelope schema (JSON)

```json
{
  "v": 1,
  "event_id": "ulid",
  "event_type": "string",
  "occurred_at": "RFC3339 timestamp",
  "tenant_id": "string",
  "workspace_id": "string|null",
  "actor": {
    "actor_type": "human|service|agent",
    "actor_id": "string",
    "auth_context": {
      "oidc_sub": "string|null",
      "ldap_groups": ["string"],
      "spiffe_id": "string|null"
    }
  },
  "trace": {
    "trace_id": "string",
    "span_id": "string|null"
  },
  "correlation": {
    "session_id": "string|null",
    "task_id": "string|null",
    "run_id": "string|null",
    "step_id": "string|null",
    "parent_event_id": "string|null"
  },
  "idempotency_key": "string|null",
  "priority": "interactive|batch|system",
  "payload_ref": {
    "kind": "inline|object",
    "content_type": "string",
    "size_bytes": 0,
    "inline": "string|null",
    "uri": "string|null",
    "sha256": "hex|null"
  },
  "schema": {
    "name": "string",
    "version": 1
  }
}
```

### 5.2 Trace propagation

- All publishers MUST include W3C `traceparent` (and optional `tracestate`) as NATS message headers.
- The envelope `trace.trace_id` MUST match `traceparent`.
- Consumers MUST continue the trace and emit spans for:
  - ingest
  - state transition
  - router call
  - tool execution dispatch
  - memory ops
  - connector egress



## 6. Payload strategy

### 6.1 Constraints

- NATS message payloads MUST stay under **1MB**; large payloads MUST be stored in object storage and referenced via `payload_ref.uri`. 

### 6.2 Object references

Object reference URIs SHOULD be stable and portable:

- `s3://<bucket>/<key>`
- `minio://<bucket>/<key>` (alias to S3 API in on-prem)
- `nas://<share>/<path>` (only where object storage is not viable)

All object refs MUST include:
- `sha256` checksum (computed by producer)
- `content_type`
- `size_bytes`



## 7. NATS subject taxonomy

The following subject naming scheme is normative. Subjects include tenant/workspace only when multi-tenant is enabled; v1 may use `tenant=default`.

### 7.1 Ingress subjects (connectors → system)

- `ingress.discord.message`
- `ingress.slack.message`
- `ingress.email.message`
- `ingress.telegram.message`
- `ingress.whatsapp.message` (singleton connector per account)

Ingress events should carry a `payload_ref` to the normalized message body and attachment references.



### 7.2 Task subjects (orchestrator → workers)

- `tasks.create`
- `tasks.dispatch`
- `tasks.run.started`
- `tasks.run.step.started`
- `tasks.run.step.completed`
- `tasks.run.completed`
- `tasks.run.failed`
- `tasks.cancel`
- `tasks.deadletter`

### 7.3 Memory subjects (system ↔ memory plane)

- `memory.write.request`
- `memory.write.completed`
- `memory.promote.request`
- `memory.compact.request`
- `memory.index.request`
- `memory.index.completed`



### 7.4 Router subjects (system ↔ model router)

- `router.request`
- `router.completed`
- `router.failed`
- `router.budget.alert`
- `router.metrics` (telemetry can be at-most-once)



### 7.5 Audit/observability subjects (optional)

- `audit.toolcall`
- `audit.approval`
- `telemetry.metrics`
- `telemetry.logs`
- `telemetry.traces`

Telemetry streams can be best-effort; audit streams MUST be durable.



### 7.6 Heartbeat / scheduled work

Heartbeat events are produced by the platform scheduler (K8s CronJob / cron) and published as tasks:

- `heartbeat.healthcheck`
- `heartbeat.memory.compaction`
- `heartbeat.memory.index_refresh`
- `heartbeat.infra.reconcile`
- `heartbeat.connector.token_refresh`

Schedules are defined in RFC-002/RFC-003 operational sections; the event model for heartbeats is defined here.



## 8. JetStream stream definitions

### 8.1 Required streams

1. **STREAM_TASKS**
   - subjects: `tasks.*`
   - retention: work queue / interest
   - max age: 7 days (configurable)
   - storage: file (JetStream) backed by PV on K8s; local disk in Podman mode

2. **STREAM_EVENTS**
   - subjects: `ingress.*`, `memory.*`, `router.*`, `heartbeat.*`
   - retention: limits-based
   - max age: 24 hours for ingress events (since they are persisted in Postgres)
   - storage: file

3. **STREAM_AUDIT**
   - subjects: `audit.*`
   - retention: limits-based
   - max age: 90 days hot (then exported to object storage for warm/cold retention)
   - storage: file + export

Retention targets reflect the compliance retention goals (90d hot / 1y warm / 7y cold) but are implemented via export from JetStream to object storage. 

### 8.2 Consumer patterns

- All consumers MUST be pull-based with explicit ack.
- Retries MUST use exponential backoff with jitter.
- Poison messages MUST be moved to `tasks.deadletter` after N failures, where N is stream-configurable (default 10).

## 9. Authoritative state model (Postgres)

### 9.1 Entity overview

**Tenant**
- `tenant_id` (PK)
- config: routing defaults, budget defaults, retention defaults

**Workspace**
- `workspace_id` (PK)
- `tenant_id` (FK)
- owner `agent_id`

**Agent**
- `agent_id` (PK)
- `tenant_id` (FK)
- `agent_definition_ref` (git ref + digest)
- runtime class: code/research/infra
- policy tags: privacy, budget class

**Session**
- `session_id` (PK)
- `tenant_id` (FK)
- connector identity mapping:
  - `connector_type`, `connector_account_id`, `thread_id`
- `state` (active/archived)
- `next_ingress_seq` (int)
- `last_processed_ingress_seq` (int)

**IngressMessage**
- `(tenant_id, session_id, ingress_seq)` unique
- `connector_message_id`
- `received_at`
- `payload_ref`

**Task**
- `task_id` (PK)
- `tenant_id` (FK)
- `session_id` (FK nullable for batch/system)
- `agent_id`
- `parent_task_id` (nullable)
- `task_type` (interactive|batch|system)
- `status` (see state machine)
- `budget_id`
- `capability_grant_id`
- `workspace_path` (deterministic)

**Run**
- `run_id` (PK)
- `task_id` (FK)
- `attempt` (int)
- `status`
- `started_at`, `ended_at`
- `failure_reason` (nullable)

**Step**
- `step_id` (PK)
- `run_id` (FK)
- `step_type` (model_call|tool_call|memory|connector_send|approval_wait)
- `status`
- `idempotency_key` (unique per tenant)
- `input_ref`, `output_ref` (artifact refs)

**Artifact**
- `artifact_id` (PK)
- `tenant_id`
- `uri`, `sha256`, `size_bytes`, `content_type`
- `created_at`
- `retention_class` (hot|warm|cold)

**ApprovalRequest**
- `approval_id` (PK)
- `tenant_id`
- `task_id/run_id/step_id`
- `requested_by`
- `status` (pending|approved|denied|expired)
- `expires_at`
- `decision_by`, `decision_at`

**Budget**
- `budget_id` (PK)
- `scope` (tenant|agent)
- `daily_limit`, `monthly_limit`, `soft_threshold` (80%), `hard_threshold` (100%)
- `spend_today`, `spend_month`
- `updated_at`



## 10. Ordering guarantees

### 10.1 Requirement

Per the requirements, the system MUST maintain **per-session ordering** for chat continuity. 

### 10.2 Enforcement approach (normative for v1)

Ordering is enforced at the **authoritative state layer**, not by relying on NATS delivery affinity:

1. **Ingress normalization**: connector ingests a message, stores normalized body in object storage, publishes `ingress.<connector>.message` with `payload_ref`.
2. **Ingress persistence**: orchestrator consumer writes an `IngressMessage` row with a monotonically increasing `ingress_seq` per session (transactionally incrementing `Session.next_ingress_seq`).
3. **Session scheduler**: orchestrator selects the next unprocessed ingress message for a session in order (smallest `ingress_seq > last_processed_ingress_seq`) and creates a Task only when:
   - the session has no active interactive Task in RUNNING/WAITING state
   - the previous ingress message has been processed
4. **Single-flight lock**: orchestrator uses a Postgres advisory lock keyed by `(tenant_id, session_id)` during scheduling and task state transitions.

This yields deterministic ordering independent of NATS consumer concurrency.



## 11. Task state machines

### 11.1 Task status enum (v1)

- `NEW`
- `QUEUED`
- `RUNNING`
- `WAITING_APPROVAL`
- `COMPLETED`
- `FAILED`
- `CANCELLED`
- `TIMED_OUT`

### 11.2 Allowed transitions

- NEW → QUEUED
- QUEUED → RUNNING
- RUNNING → WAITING_APPROVAL
- WAITING_APPROVAL → RUNNING
- RUNNING → COMPLETED | FAILED | TIMED_OUT | CANCELLED
- QUEUED → CANCELLED
- WAITING_APPROVAL → CANCELLED | TIMED_OUT

Transitions MUST be implemented as a state machine with:
- optimistic concurrency (row version) OR transactional locks
- immutable transition event logs emitted on `tasks.run.*` subjects

### 11.3 Subagent tasks

Subagent spawning is represented as:
- parent Task RUNNING creates child Task with `parent_task_id`
- max depth v1 = 2 (parent → child)
- max concurrent children v1 = 8
- child Task inherits:
  - a restricted CapabilityGrant (RFC-002)
  - isolated memory scope by default



## 12. Idempotency

### 12.1 Requirement

State changes and side effects MUST be deduplicated using idempotency keys. 

### 12.2 Key format (recommended)

`idem:{tenant}:{task_id}:{run_attempt}:{step_type}:{step_seq}`

Examples:
- `idem:default:tsk_01HW...:1:connector_send:3`
- `idem:default:tsk_01HW...:1:tool_call:7`

### 12.3 Deduplication rules

- For each side-effecting Step, `idempotency_key` MUST be unique in Postgres.
- Connector egress MUST store `(connector, account, destination, idempotency_key)` and treat duplicates as no-ops.
- Tool execution (Daytona) MUST accept an idempotency key and return the previous result if repeated.
- Memory writes MUST dedupe based on key + target path.

## 13. Failure handling

### 13.1 Retry policy

- Transient errors: retry with exponential backoff (base 250ms, max 60s) with jitter.
- Permanent errors: mark Step FAILED and propagate to Task FAILED unless policy allows fallback.

### 13.2 Dead-letter

- After N retries (default 10), publish to `tasks.deadletter` with failure metadata and store in Postgres for operator review.

## 14. Observability and audit hooks

### 14.1 OpenTelemetry

- All services MUST emit OTEL traces and metrics.
- Trace IDs MUST be propagated via NATS headers, stored in Postgres for correlation, and included in audit records. 

### 14.2 Audit events (normative)

Each tool call Step MUST emit an `audit.toolcall` event containing:
- Step metadata
- hashed inputs
- hashed outputs + truncated preview
- sandbox identity (Daytona)
- actor identity (human/service/agent)

Audit retention goals are defined in the requirements (90d hot / 1y warm / 7y cold). 

## 15. Security notes (transport-level)

- NATS connections MUST use mTLS.
- Authorization MUST enforce per-subject publish/subscribe permissions. 
- For v2 multi-tenant, subject patterns MUST incorporate `tenant_id` and be permissioned per tenant.

## 16. Open questions / TBD (explicit)

These items are explicitly listed as unresolved in the requirements document and remain TBD for implementation planning:
- JetStream storage backend selection and topology (single cluster vs per-tenant). 
- Multi-tenant scaling approach in v2 (namespace isolation vs stronger). 

## 17. Implementation checklist (v1)

1. Implement the envelope schema library (Go/TS/Python) and validate on publish/consume.
2. Stand up JetStream streams: TASKS, EVENTS, AUDIT.
3. Implement Postgres schema and migrations for entities in Section 9.
4. Implement ingress persistence + session scheduler enforcing per-session ordering.
5. Implement idempotency key propagation across connectors, router, executor, memory plane.
6. Implement dead-letter handling + operator inspection UI.


---

# RFC-002: Isolation and Policy (OIDC/LDAP + SPIFFE + Vault + Daytona)

**Project:** Orchestack  
**Resident agent name:** Homarus  

**Status:** Draft (v1)  
**Last updated:** 2026-02-07  
**Source of requirements:** Architecture Response Document (repo copy: `Orchestack_Architecture_Response.md`; original: `Homarus_2.0_Architecture_Response.md`), dated 2026-02-06

## 1. Summary

This RFC defines the **security model, identity model, policy evaluation, and isolation boundaries** for Orchestack.

Core principles:

- **Progressive disclosure:** strict secure defaults with explicitly audited escape hatches. 
- **Service isolation** is provided by the platform (OpenShift/Kubernetes/Podman), enforced with network policy and least-privileged service accounts. 
- **Agent execution isolation** is provided by **Daytona sandboxes**, not by the control plane. Sandboxes are ephemeral by default with deny-all egress. 
- **Human identity:** OIDC authentication with LDAP as group/role source. 
- **Service identity:** SPIFFE/SPIRE SVIDs with mutual TLS everywhere. SVID TTL <= 24h. 
- **Secrets:** Vault is mandatory; ESO is the standard delivery mechanism; rotations enforced. 
- **DLP scanning** is mandatory for memory writes and outbound messages. 

This RFC also defines **subagent delegation controls** and the capability model that enforces least privilege.



## 2. Goals

### 2.1 Goals (v1)

1. Define identity and authentication/authorization flows for:
   - humans (OIDC + LDAP groups)
   - services (SPIFFE/SPIRE)
2. Define the RBAC/capability model and where it is enforced.
3. Define agent and subagent policy objects and evaluation rules.
4. Define sandbox isolation requirements for Daytona:
   - lifecycle (ephemeral default)
   - egress (deny-all default)
   - filesystem constraints
   - resource cordons
   - runtime class toolkits
5. Define audit requirements (tool-call hashing/truncation, retention).
6. Define approval workflows for high-risk actions (esp. infra actions).



### 2.2 Non-goals (v1)

- User-extensible sandbox images (centrally curated only).
- Auto-apply of destructive infra changes (human approval required).
- Multi-tenant security boundaries beyond v1 (but policies include tenant identifiers for v2 readiness).



## 3. Threat model (prioritized)

The v1 threat model priorities (highest to lower) are:

1. Compromised connector tokens
2. Prompt injection via untrusted content
3. Malicious internal users
4. Supply chain risks
5. External attackers

Mitigations in this RFC map to these priorities.



## 4. Identity and authentication

### 4.1 Human authentication

- Humans authenticate via **OIDC (SSO)**.
- LDAP is the source of truth for group membership/roles (either via IdP group claims or an authoritative LDAP query service).

Normative requirement: **all privileged actions MUST have an attributable human identity** (OIDC subject), even when executed by system agents on behalf of humans.



### 4.2 Service-to-service identity

- All services MUST use **SPIFFE/SPIRE** workload identity.
- All service-to-service calls MUST use **mutual TLS** with short-lived SVIDs (<= 24 hours).
- Services MUST be authorized based on SPIFFE ID + policy (not on static IPs).



### 4.3 NATS identity

The requirements specify **mTLS + JWT** and per-tenant subject permissions, with NKeys for service accounts. 

Normative v1 implementation guidance:

- NATS server requires mTLS for all connections.
- Each service uses an NKey to authenticate; NATS JWT is used to scope publish/subscribe permissions.
- For v2 multi-tenant, subject permissions MUST be tenant-scoped.



## 5. Authorization model

### 5.1 Roles

The following high-level roles exist (LDAP-backed):

- `operator`
- `agent-owner`
- `auditor`
- `infra-admin`



### 5.2 Capabilities

Fine-grained permissions are expressed as LDAP-backed capability groups, e.g.:

- `can_spawn_subagents`
- `can_use_network`
- `can_write_memory_L2`
- `can_apply_infra_changes`

Capabilities are combined into a **CapabilityGrant** that is attached to every Task/Run.



### 5.3 Progressive disclosure (escape hatches)

The system ships with strict defaults (deny-all egress, local embeddings, ephemeral sandboxes). Escape hatches (external models/embeddings, persistent sandboxes, expanded egress) MUST be:

- explicitly configured in agent policy
- allowed by org policy
- fully audited



## 6. Policy objects and evaluation

### 6.1 Two-layer policy

All policy evaluation is the intersection of:

1. **OrgPolicy** (admin-controlled, hard guardrails)
2. **AgentPolicy** (agent-owner controlled, must be a strict subset of OrgPolicy)

This prevents self-escalation by agent owners or agents.



### 6.2 AgentDefinition (git-backed)

Agent configuration is GitOps-managed. An AgentDefinition includes:

- identity:
  - `agent_id`, `owner_groups`
- runtime:
  - `runtime_class`: `code|research|infra`
  - `sandbox_profile` (Daytona)
- model routing policy tags:
  - `privacy_class`: `sensitive|standard`
  - `budget_class`: `low|standard|high`
- memory access policy:
  - allowed layers for read/write (L0-L4)
- tool policy:
  - allowlist of tool families (e.g., git, http, kubectl)
- egress policy:
  - deny-all default with allowlist

Agent owners may edit AgentDefinition within OrgPolicy constraints.



### 6.3 SubagentTemplate

Subagents are spawned only from approved templates.

Template controls:

- `max_depth` (v1 fixed at 2)
- `max_concurrent_children` (v1 default 8)
- `max_wall_time_seconds` (v1 default 3600)
- `max_cost` / `max_tokens` per parent (configurable per agent)
- tool allowlist subset
- memory sharing rules (default deny; explicit share only through L3)



### 6.4 CapabilityGrant (runtime-issued)

A CapabilityGrant is a signed/immutable record that includes:

- subject (human/service/agent)
- task/run scope
- allowed tools and constraints
- allowed model classes/providers
- memory read/write layers
- sandbox profile (Daytona) + quotas
- expiry

CapabilityGrants MUST be stored in Postgres and referenced by Task/Run (RFC-001).

## 7. Delegation and subagent controls

Normative v1 constraints:

- Max depth: 2 (parent → child)
- Max concurrent children: 8
- Max wall time per child: 1 hour (extendable via approval)
- Tool inheritance: whitelist (never implicit)
- Memory view: isolated by default; explicit share via L3 only



## 8. Isolation boundaries

### 8.1 Service isolation (platform)

Service isolation is handled by:
- namespaces (v1 single-tenant; v2 tenant namespaces)
- network policies (zero-trust east-west)
- RBAC/service accounts

Security parity MUST be maintained across OpenShift, Kubernetes, and Podman-mode (implementation differs, guarantees should not). 

### 8.2 Agent execution isolation (Daytona)

All agent tool execution happens in Daytona sandboxes:

#### Sandbox lifecycle
- Default: ephemeral (destroy after task)
- Optional: persistent for long-running agents (explicit opt-in)



#### Network egress
- Default: deny-all
- Allowlist: per agent policy (domain/IP list)
- Any allowlist expansion MUST be audited.



#### Filesystem
- No direct host mounts
- Read-only “reference volumes” are allowed (platform-managed)
- Secrets are injected via External Secrets + Vault
- Config via ConfigMaps



#### Resource cordons (v1 baseline)
- CPU: 0.5–4 cores per sandbox
- Memory: 512MB–8GB
- Disk: 10GB default
- Network: rate-limited egress
- Max concurrent sandboxes: 20 per agent
- GPU: 0 in v1 (flag-gated in v2)



#### Reproducibility and supply chain
- Sandbox images MUST be pinned by digest.
- Only centrally curated images in v1.



## 9. Secrets management

Normative requirements:

- Vault is mandatory.
- ESO is used to sync secrets into the runtime.
- Rotation:
  - API keys: 90 days
  - tokens: 24 hours where feasible

Secrets MUST never be written to memory layers or logs; redaction is mandatory.



## 10. DLP and content scanning

DLP scanning is mandatory for:
- memory writes
- outbound connector messages

Minimum v1 behavior:
- detect common PII/PHI patterns
- redact or block based on policy
- generate an approval request for borderline cases



## 11. Audit and governance

### 11.1 Tool call logging

All tool calls MUST be recorded:
- inputs: hashed
- outputs: hashed + truncated preview
- metadata: full retention
- secrets: redacted

Retention: 90 days hot, 1 year warm, 7 years cold (via export). 

### 11.2 Break-glass

Break-glass is required for incident response with:
- 4-hour time bound
- dual approval
- hardware MFA
- full audit



## 12. System agents (infra) policy

v1 posture:

- system agents **propose changes** via PRs/manifests
- auto-apply only for a tight allowlist (restarts, non-destructive reconciliations)
- destructive actions require human approval

Runbooks are Git source-of-truth; L3 memory is a cache synced from Git. 

## 13. Operational requirements

### 13.1 Scheduled jobs (heartbeat)

The platform scheduler triggers:
- health checks every 30s
- infra reconciliation every 5m
- token refresh before expiry
- memory compaction daily 2am
- index refresh hourly

Job concurrency rules:
- infra: single-flight
- reports: overlap OK
- idempotency keys required for all

Timezone: per-tenant configurable, default UTC. 

## 14. Open questions / TBD

The requirements document flags the following as unresolved:
- Daytona deployment specifics (version; self-hosted vs managed; GPU timeline)
- Vault deployment specifics (existing vs new; auth method)
- OpenShift baseline version and deprecated API avoidance

These are configuration decisions and do not change the policy/contract surfaces in this RFC. 

## 15. Implementation checklist (v1)

1. Implement policy objects:
   - OrgPolicy
   - AgentDefinition (git-backed)
   - SubagentTemplate
   - CapabilityGrant
2. Implement policy evaluation service:
   - OIDC auth, LDAP group resolution
   - SPIFFE auth for services
3. Integrate Vault + ESO; enforce secret redaction.
4. Integrate Daytona executor with enforceable sandbox profiles.
5. Implement DLP scanning gates for memory writes and outbound messages.
6. Implement break-glass workflow and auditing.


---

# RFC-003: Memory Plane (Hierarchical, File-Based, Cluster-Optimized)

**Project:** Orchestack  
**Resident agent name:** Homarus  

**Status:** Draft (v1)  
**Last updated:** 2026-02-07  
**Source of requirements:** Architecture Response Document (repo copy: `Orchestack_Architecture_Response.md`; original: `Homarus_2.0_Architecture_Response.md`), dated 2026-02-06

## 1. Summary

This RFC defines the **Memory Plane** for Orchestack: a hierarchical, file-based memory system with:

- Tiered memory layers (L0–L4) with defined retention and access policies
- Canonical, human-readable storage format: **Markdown + YAML frontmatter**
- Cluster-optimized indexing and retrieval (hybrid lexical + vector + reranking)
- Mandatory provenance: **file + line ranges**
- Mandatory DLP scanning on writes (and outbound messages handled elsewhere)
- Off-cluster durable storage for long-term intelligence using:
  - S3-compatible object storage (MinIO primary)
  - NAS (NFS) for shared workspaces where needed
- Git-style history and rollback for curated/shared memory and archives

QMD (or similar) is supported as a retrieval/index plugin, but the system must not depend on a single backend.



## 2. Goals

### 2.1 Goals (v1)

1. Define memory tiers (L0–L4), retention, and access boundaries.
2. Define canonical document format (Markdown + YAML frontmatter).
3. Define storage layout across object store + NAS and replication targets (RPO/RTO).
4. Define APIs for:
   - write/read
   - search
   - promote/demote
   - compaction
   - snapshot/versioning
5. Define indexing + retrieval pipeline:
   - local embeddings required by default
   - hybrid retrieval + reranking
   - p95 retrieval < 500ms
6. Define provenance rules and citation requirements.
7. Define curation workflows for L3 and archival policies for L4.



### 2.2 Non-goals (v1)

- External embedding APIs as a default path (allowed only as opt-in).
- Cross-agent L2 memory reads (explicitly disallowed).
- Fully automated promotion into L3 without approval (curation required).



## 3. Terminology

- **Memory document:** A Markdown file with YAML frontmatter and an optional attachments bundle.
- **Provenance:** Evidence metadata for retrieval hits: `{uri, line_start, line_end, sha256}`.
- **Compaction:** Summarization/merging of lower-tier documents into curated higher-tier documents.
- **Curation:** Human-reviewed promotion to shared organizational memory (L3).

## 4. Memory tiers

### 4.1 Tier definitions (normative)

The following tiers are mandatory:

| Layer | Name | Visibility | Default retention | Storage class |
|---|---|---|---:|---|
| L0 | Scratch | session-only | 24 hours | hot |
| L1 | Working | agent-private | 7 days | hot |
| L2 | Durable | agent-private | 90 days **or** 10MB per agent | warm |
| L3 | Shared | org/team shared | 1 year **or** 100MB per team | warm |
| L4 | Archive | historical | indefinite (compressed) | cold |



### 4.2 Cross-agent access rules (normative)

- No agent may read another agent’s L2 (strict isolation).
- L3 is shared but curated:
  - reads allowed to authorized groups
  - writes require approval workflow
- L4 is read-only for most agents; only system/curator roles can write.



### 4.3 Sensitivity tags

Every memory document MUST have a sensitivity tag in frontmatter:
- `public`
- `internal`
- `sensitive` (includes PII/PHI)
- `restricted` (highly sensitive; may require on-prem-only routing)

Sensitivity tags are inputs to:
- model router gating
- retrieval filtering
- export policy



## 5. Canonical document format

### 5.1 YAML frontmatter schema (minimum)

```yaml
id: mem_01HW...            # ULID
layer: L1                  # L0|L1|L2|L3|L4
tenant_id: default
agent_id: agent_...
workspace_id: ws_...       # optional for shared docs
title: "string"
created_at: 2026-02-07T01:23:45Z
updated_at: 2026-02-07T02:00:00Z
authors:
  - oidc:sub:abc123
tags:
  - incident-response
  - runbook
sensitivity: internal      # public|internal|sensitive|restricted
retention:
  expires_at: null         # optional override
source:
  type: tool|human|import
  ref: "task:tsk_..."      # link back to Task/Run/Step
integrity:
  sha256: "..."            # of canonical content
```

### 5.2 Body conventions

- The Markdown body should support:
  - headings, lists, tables
  - code fences
  - explicit citations to other memory docs via `memref:` URIs

The system MUST preserve the canonical file as the source of truth (no hidden fields outside frontmatter).



## 6. Storage layout

### 6.1 Primary storage requirements

The requirements mandate both:
- S3-compatible object storage for artifacts (MinIO on-prem primary)
- NAS for shared workspaces (NFS)

Memory should treat object storage as canonical for documents and NAS as optional/auxiliary for collaboration spaces.



### 6.2 Object key layout (recommended)

Bucket: `homarus-memory`

Keys:

- Agent-private:
  - `tenants/{tenant_id}/agents/{agent_id}/L{n}/{yyyy}/{mm}/{id}.md`
- Shared (L3):
  - `tenants/{tenant_id}/shared/{team_id}/L3/{yyyy}/{mm}/{id}.md`
- Archive (L4):
  - `tenants/{tenant_id}/archive/{scope}/{yyyy}/{mm}/{id}.md.gz`
- Attachments:
  - `tenants/{tenant_id}/attachments/{sha256[0:2]}/{sha256}`

All writes MUST be content-addressed or include checksums to enable integrity verification.

### 6.3 Git-backed history

- L3 and L4 MUST support git-style history and rollback.
- Canonical approach:
  - L3 is maintained as a Git repository (source-of-truth for curated docs).
  - A sync job mirrors the Git repo into object storage for uniform retrieval.
  - L4 can be stored as a Git repo snapshot bundle (compressed) and also mirrored.

This aligns with “GitOps for everything” and “L3 memory is cache; Git is source of truth.” 

## 7. APIs (service contract)

The Memory Plane is a service with both synchronous APIs (for writes/search) and asynchronous indexing/compaction workers.

### 7.1 Write API

`POST /v1/memory/write`

Request:
- `layer`
- `path` (optional; server can assign by ID)
- `document` (Markdown + frontmatter)
- `idempotency_key`
- `expected_sha` (optional optimistic concurrency)

Behavior:
- DLP scan
- validate schema
- store in object storage (and git repo if L3/L4)
- emit `memory.write.completed`
- trigger indexing via `memory.index.request`

### 7.2 Search API

`POST /v1/memory/search`

Inputs:
- `query`
- `layers[]`
- `filters`:
  - tags
  - sensitivity <= requested
  - time range
- `k`

Output:
- list of hits:
  - `uri`
  - `score`
  - `provenance: {line_start, line_end, sha256}`
  - small excerpt (bounded)

Normative requirement: provenance MUST include file + line ranges. 

### 7.3 Promote/Demote APIs

- `POST /v1/memory/promote`
- `POST /v1/memory/demote`

Promotion rules are governed by policy:
- L0→L1: heuristic allowed
- L1→L2: explicit memory write tool required
- L2→L3: curation approval required
- L3→L4: scheduled archiving/compaction



### 7.4 Compaction API

`POST /v1/memory/compact`

Used by scheduled jobs:
- daily at 2am: L2→L3 curation suggestions; L3→L4 archival bundling
- returns a report + artifacts (e.g., PRs created)



## 8. Indexing and retrieval pipeline

### 8.1 Retrieval approach (normative)

- Hybrid retrieval:
  - BM25 lexical search for recall
  - Vector search for semantic matching
  - Reranking stage for final ordering
- Local embeddings are required by default.
- External embedding APIs are opt-in only.

Default local embedding model (initial): `sentence-transformers/all-MiniLM-L6-v2`. 

**Note:** code-focused embedding model selection is an explicit open item in the requirements; the embedding interface must allow swaps without changing agent logic. 

### 8.2 Index update triggers

On every successful write/promote/demote:
- emit `memory.index.request` with the affected document URI(s)
- indexer consumes and updates:
  - lexical index
  - vector index
  - provenance map (line offsets)

An hourly index refresh job is also required. 

### 8.3 Plugin interface (indexer/retriever)

To avoid coupling to QMD, define an internal plugin interface:

- `IndexPlugin.index(doc_uris[]) -> index_version`
- `SearchPlugin.search(query, layers, filters, k) -> hits[]`
- `SearchPlugin.explain(hit_id) -> provenance`

A QMD-based plugin may implement these; a local SQLite/BM25+vec plugin may also implement them.

## 9. Provenance and line ranges

### 9.1 Requirement

Retrieval results MUST include exact file + line ranges. 

### 9.2 Implementation guidance

- Store canonical Markdown as bytes.
- At index time, compute newline offsets and store a line map:
  - `line_number -> byte_offset`
- For each retrieval hit, store the byte range and translate to line_start/line_end.
- Excerpts are generated from byte range but must be bounded (avoid leaking large sensitive content).

## 10. Performance requirements

### 10.1 Latency

- p95 retrieval latency < 500ms. 

Achieve via:
- hot cache of top-N documents per agent/session
- precomputed embeddings
- incremental indexing (avoid full rebuild)
- layered search: narrow filters before reranking

### 10.2 Scalability target

Memory plane must support:
- 100+ concurrent sessions
- peak ingestion of ~100 messages/minute
- attachment sizes up to 10MB (stored as artifacts, referenced)



## 11. Security, compliance, and DLP

### 11.1 Encryption

- Encryption at rest is required beyond provider defaults.
- Keys are managed via Vault or KMS, with per-tenant keys for future multi-tenant.



### 11.2 DLP scanning on write (normative)

All writes MUST be scanned:
- detect PII/PHI patterns
- redact or block based on sensitivity + policy
- log an audit record (inputs hashed) regardless of allow/deny



### 11.3 Access control

Memory service MUST enforce:
- layer access controls from CapabilityGrant (RFC-002)
- sensitivity filtering
- audit logging for all reads/searches of sensitive layers

## 12. Retention, compaction, and scheduling

Normative scheduled jobs:
- Memory compaction: daily at 2am
- Index refresh: hourly

Retention defaults:
- L0: 24h
- L1: 7d
- L2: 90d or 10MB/agent
- L3: 1y or 100MB/team
- L4: indefinite compressed

Missed job behavior:
- stateful jobs: catch-up
- idempotent jobs: skip if safe



## 13. Disaster recovery and durability

Storage and recovery targets:
- RPO: 1 hour overall; L2-L3: 15 minutes
- RTO: 4 hours full recovery

Implementation guidance:
- replicate object store (or use distributed backend)
- periodic export of JetStream audit/events to object store
- snapshot Git repos (L3/L4) and store bundles in object storage



## 14. Open questions / TBD

The requirements document flags the following memory-related open decisions:
- Whether `all-MiniLM-L6-v2` is sufficient; need for larger/code embeddings.
- Vault/KMS key management specifics.
- NAS usage scope for shared workspaces beyond artifacts.

These are parameter choices; the API and tier semantics in this RFC are intended to remain stable regardless.



## 15. Implementation checklist (v1)

1. Implement document schema validation and canonicalization.
2. Implement write/read/search APIs with CapabilityGrant enforcement.
3. Implement object storage layout + checksums; integrate Vault-backed encryption.
4. Implement DLP scanning pipeline and audit records.
5. Implement local hybrid indexer (BM25 + vectors + rerank) with plugin interface.
6. Implement provenance line-map generation and citation returns.
7. Implement scheduled compaction and hourly index refresh jobs.
8. Implement Git-backed L3 curation repo + sync job to object store.


---

# RFC-004: Onchain Trust and Payments (ERC-8004 + x402)

- **Project:** Orchestack
- **Resident agent name:** Homarus
- **RFC:** 004
- **Title:** Onchain Trust and Payments (ERC-8004 + x402)
- **Status:** Draft
- **Authors/Owners:** Adam (System Architect), Orchestack Core Team
- **Last updated:** February 07, 2026
- **Related RFCs:** RFC-001 (Event + State), RFC-002 (Isolation + Policy), RFC-003 (Memory Plane)

## 1. Purpose

This RFC defines **native Orchestack support** for:

1. **ERC-8004 (Trustless Agents)** as an optional onchain trust layer for agent identity, discovery, reputation, and validation.
2. **x402 (HTTP 402 Payment Required)** as an HTTP-native payment protocol enabling agents to **pay for resources** (buyer mode) and Orchestack services to **charge for resources** (seller mode).

The design is **modular** and **policy-gated** to preserve enterprise defaults:
- disabled by default in sensitive deployments
- allowlisted enablement by agent/tenant
- all signing keys managed outside agent sandboxes

## 2. Goals

### 2.1 Functional goals
- Allow Orchestack agents to autonomously purchase access to external HTTP resources using x402 **under explicit policy and budget controls**.
- Allow Orchestack to expose selected HTTP endpoints as x402-paywalled resources (multi-tenant ready).
- Allow Orchestack agents (starting with Homarus) to:
  - publish an ERC-8004 registration file and onchain identity
  - optionally submit/consume standardized reputation signals
  - optionally request/record validation events for high-stakes outputs

### 2.2 Non-functional goals
- Maintain Orchestack isolation boundaries:
  - **platform** isolates services
  - **Daytona** isolates agent execution environments
  - private keys never enter Daytona sandboxes
- Ensure strong auditability:
  - deterministic linking of `task_id` ↔ `payment_intent_id` ↔ onchain tx hash
- Preserve portability:
  - Kubernetes/OpenShift native
  - “servers with Podman” compatible (systemd + podman + cron)

## 3. Non-goals (v1)
- Full decentralized “agent economy marketplace” (discovery + negotiation + escrow) is out of scope for v1.
- Fiat settlement is out of scope for v1 (supported later via x402 V2 facilitators where available).
- Automated onchain reputation publishing for every interaction is out of scope for v1 (manual/allowlisted in v1; expand later).

## 4. Background (normative references)

### 4.1 ERC-8004 overview
ERC-8004 defines three lightweight onchain registries:
- **Identity Registry**: ERC-721 token where tokenId is `agentId` and tokenURI is `agentURI` pointing to an agent registration file.
- **Reputation Registry**: standardized feedback submissions keyed by `(agentId, clientAddress, feedbackIndex)` with optional offchain attachments.
- **Validation Registry**: request/response events for validator smart contracts to attest to agent work.

The ERC-8004 registration file schema includes (not exhaustive):
- list of `services` (A2A/MCP/OASF/ENS/DID/email endpoints)
- `registrations` pointing to chain+registry identifiers
- `x402Support` boolean to advertise payment capability

See: https://eips.ethereum.org/EIPS/eip-8004

### 4.2 x402 overview
x402 is an HTTP-native payment standard centered on HTTP **402 Payment Required**:
- A resource server responds with `402` and a `PAYMENT-REQUIRED` header describing payment requirements.
- A client resubmits the request with a `PAYMENT-SIGNATURE` header carrying a signed payment payload.
- The server verifies/settles the payment (locally or via a facilitator), and returns a `PAYMENT-RESPONSE` header with settlement details.

Key x402 references:
- https://www.x402.org/
- https://docs.x402.org/
- https://docs.cdp.coinbase.com/x402/
- https://github.com/coinbase/x402

x402 V2 emphasizes:
- plugin-driven SDK architecture
- modern header conventions: `PAYMENT-REQUIRED`, `PAYMENT-SIGNATURE`, `PAYMENT-RESPONSE`

## 5. Architectural overview

Orchestack adds a **Trust & Payments Plane** composed of the following modules:

### 5.1 Payments Service (x402)
A long-lived control-plane service responsible for:
- generating payment requirements for Orchestack paywalled endpoints (seller mode)
- verifying and settling payments (via facilitator adapters)
- creating/approving outbound payment intents on behalf of agents (buyer mode)
- maintaining payment ledgers and linking payment proofs to Orchestack artifacts

**Important:** The Payments Service is the only component that can request signatures from wallet key material.

### 5.2 Wallet Signer (HSM/Vault-backed)
A small service (or library inside Payments Service) responsible for:
- signing x402 payment payloads
- signing ERC-8004 operations (agent registration, setAgentWallet, etc.)
- enforcing key usage policy (rate limits, allowlists, per-agent budgets)

Key material must be stored encrypted and access-controlled. Implementation options:
- HSM (preferred where available)
- Vault-backed encrypted keys with restrictive policies
- smart contract wallet + external signer (EIP-1271) when appropriate

### 5.3 Facilitator Adapter (pluggable)
An adapter layer that can:
- call a hosted facilitator (e.g., Coinbase CDP) or
- call a self-hosted facilitator or
- verify/settle locally when explicitly enabled

The adapter interface allows Orchestack deployments to choose compliance posture and connectivity assumptions.

### 5.4 Trust Service (ERC-8004)
A service responsible for:
- publishing and maintaining ERC-8004 registrations for selected agents
- indexing ERC-8004 identity/reputation/validation events (optional subgraph integration later)
- exposing trust signals to Orchestack policy decisions (e.g., “autopay allowed if reputation ≥ threshold”)

### 5.5 Onchain Indexers (optional)
Background workers that subscribe to:
- blockchain event streams (ERC-8004 registry events)
- x402 settlement confirmations (where not handled by facilitator callbacks)
and materialize:
- trust signals
- payment proofs
into the Orchestack data model (Postgres + object store).

## 6. Policy model (extensions to RFC-002)

ERC-8004 and x402 require additional capability groups. At minimum:

- `can_x402_buy`: initiate outbound payments (buyer mode)
- `can_x402_sell`: operate paywalled endpoints (seller mode)
- `can_x402_autopay`: allow autonomous payment without human approval under defined conditions
- `can_erc8004_register`: register agent identity / update agentURI
- `can_erc8004_set_wallet`: update ERC-8004 `agentWallet` (high risk)
- `can_erc8004_feedback_write`: submit onchain reputation feedback
- `can_erc8004_validation_request`: request validation on-chain
- `can_erc8004_validation_respond`: validator role only

### 6.1 Default policy stance (enterprise-safe)
- All onchain capabilities are **disabled by default**.
- `can_x402_buy` may be enabled for specific agents with:
  - per-agent spend budgets
  - endpoint allowlists
  - human approval required unless `can_x402_autopay` is granted
- `can_x402_sell` is enabled only for explicit “public monetized endpoints”.
- `can_erc8004_*` capabilities are enabled only for agents that must be discoverable outside the organization.

### 6.2 Autopay guardrails (required)
Autopay is permitted only if **all** are true:
- endpoint domain allowlisted, AND
- payment amount ≤ per-request cap, AND
- agent has remaining daily budget, AND
- counterparty passes trust checks (optional), AND
- request is marked non-sensitive by policy tags

Trust checks may include:
- ERC-8004 reputation summary from allowlisted reviewers
- validation tags / prior success rate
- local allowlist overrides

## 7. Data model (extensions to RFC-001)

### 7.1 Postgres entities (minimum)

**AgentOnchainIdentity**
- `agent_id` (Orchestack agent UUID)
- `chain_namespace` (e.g., `eip155`)
- `chain_id`
- `identity_registry_address`
- `erc8004_agent_id` (uint256)
- `agent_uri` (string)
- `agent_wallet` (address)
- `status` (`draft|published|disabled`)
- `created_at`, `updated_at`

**PaymentIntent**
- `payment_intent_id` (UUID)
- `task_id` (nullable, links to RFC-001 Task)
- `run_id` (nullable)
- `mode` (`buy|sell`)
- `protocol` (`x402`)
- `resource` (URL or service identifier)
- `requirements_ref` (object store ref; server-provided `PAYMENT-REQUIRED`)
- `amount_max` (string; smallest unit)
- `asset` (CAIP-19 or equivalent)
- `network` (CAIP-2 or equivalent)
- `status` (`created|approved|signed|verified|settled|failed|cancelled|expired`)
- `idempotency_key`
- `created_at`, `updated_at`

**PaymentSettlement**
- `payment_intent_id`
- `settlement_ref` (object store ref; includes `PAYMENT-RESPONSE`)
- `tx_hash` (nullable)
- `facilitator` (identifier)
- `verified_at`, `settled_at`
- `kyt_result` (nullable; if provided by facilitator)

**TrustSignalCache** (optional v1; recommended v1.5)
- materialized reputation/validation summaries for policy/routing decisions

### 7.2 Object store artifacts
- `payments/requirements/{payment_intent_id}.json` (parsed form of `PAYMENT-REQUIRED`)
- `payments/signatures/{payment_intent_id}.json` (signed payload; access controlled)
- `payments/responses/{payment_intent_id}.json` (parsed `PAYMENT-RESPONSE`)
- `erc8004/registration/{orchestack_agent_id}/registration.json` (agent registration file)
- `erc8004/feedback/{...}.json` (offchain feedback attachment, may include proofOfPayment)
- `erc8004/validation/{request_hash}.json` (inputs/outputs evidence bundle)

All objects must be encrypted at rest and access controlled.

## 8. Event model (extensions to RFC-001)

### 8.1 NATS subjects (recommended)
- `payments.x402.intent.created`
- `payments.x402.intent.approval.requested`
- `payments.x402.intent.approved`
- `payments.x402.intent.signed`
- `payments.x402.intent.verified`
- `payments.x402.intent.settled`
- `payments.x402.intent.failed`

- `trust.erc8004.identity.published`
- `trust.erc8004.reputation.feedback.submitted`
- `trust.erc8004.validation.requested`
- `trust.erc8004.validation.responded`

### 8.2 Correlation requirements
All payment/trust events MUST include:
- `trace_id`
- `task_id` / `run_id` (if applicable)
- `payment_intent_id` (for payments)
- `orchestack_agent_id` and `erc8004_agent_id` (when relevant)
- `idempotency_key`

## 9. Workflows

### 9.1 Buyer workflow: agent pays an external x402 resource

1. Agent in Daytona attempts HTTP request via Orchestack HTTP tool.
2. If response is `402 Payment Required`, the tool forwards the `PAYMENT-REQUIRED` header and request context to Payments Service.
3. Payments Service:
   - validates policy (allowlist + budgets + sensitivity tags)
   - creates a `PaymentIntent` (`mode=buy`) with idempotency key
   - if required: requests human approval
4. Wallet Signer produces `PAYMENT-SIGNATURE` payload.
5. Payments Service calls facilitator `verify` (optional but recommended), then resubmits request with `PAYMENT-SIGNATURE` header.
6. Server returns `200` with `PAYMENT-RESPONSE` header; Payments Service stores settlement details and emits `payments.x402.intent.settled`.
7. HTTP tool returns the original resource body to the agent plus a payment proof reference (tx hash if available).

### 9.2 Seller workflow: external client pays Orchestack for an endpoint

1. External client calls Orchestack endpoint.
2. API gateway / middleware detects endpoint requires payment.
3. Orchestack returns `402` with `PAYMENT-REQUIRED` header describing accepted payment methods.
4. Client resubmits request with `PAYMENT-SIGNATURE` header.
5. Payments Service verifies/settles payment via facilitator.
6. On success, Orchestack returns `200` with `PAYMENT-RESPONSE` header and response body.

### 9.3 ERC-8004 identity workflow (publish Homarus or other agent)

1. Generate agent registration file `registration.json`:
   - includes service endpoints (A2A/MCP/etc), supportedTrust, and `x402Support`.
2. Publish registration file to a stable URI (HTTPS or IPFS) with integrity controls.
3. Trust Service submits ERC-8004 `register(agentURI)` on target chain identity registry.
4. Store `erc8004_agent_id` and registry address in `AgentOnchainIdentity`.
5. Optionally publish `.well-known/agent-registration.json` for domain verification.

### 9.4 Reputation workflow (optional v1.5)
1. After a completed task/interaction, Orchestack may produce a feedback bundle (offchain JSON) including:
   - task identifiers
   - outcome measures (success/failure, latency, etc.)
   - optional `proofOfPayment` (tx hash, from/to, chainId) when relevant
2. Submit minimal onchain feedback via `giveFeedback(...)`.
3. Store mappings in `TrustSignalCache`.

### 9.5 Validation workflow (optional v2)
1. Agent requests validation for a produced artifact/output.
2. Create request bundle (inputs/outputs + evidence) in object store/IPFS; compute `keccak256` hash.
3. Trust Service calls `validationRequest(validatorAddress, agentId, requestURI, requestHash)`.
4. Validator contract posts `validationResponse(...)`.
5. Indexer updates `TrustSignalCache` and attaches result to the original Orchestack Task.

## 10. Security considerations

### 10.1 Key custody
- Signing keys MUST NOT be accessible from Daytona sandboxes.
- Keys MUST be:
  - encrypted at rest
  - access-controlled per capability
  - rotated or replaceable via controlled procedures

### 10.2 Onchain privacy / immutability
- Never include PII/PHI in onchain data.
- Treat all onchain submissions as permanent.
- Keep sensitive details in offchain artifacts with strict access control.

### 10.3 DLP and compliance
- Run DLP scanning on:
  - outbound payments’ metadata (to avoid leaking sensitive info in URIs/notes)
  - feedback/validation offchain bundles
- Prefer facilitators with built-in compliance screening when policy requires it.

### 10.4 Replay, duplication, and idempotency
- All payment operations MUST use RFC-001 idempotency keys.
- Settlements and external side effects MUST be recorded in Postgres before acknowledging completion to callers.

## 11. Portability considerations

- In air-gapped deployments:
  - x402 is supported only if an internal network/facilitator is reachable.
  - ERC-8004 is supported only if chain RPC access exists (internal chain or allowed egress).
- In Podman HA mode:
  - NATS JetStream + Postgres + Payments/Trust services run under systemd supervision.
  - Cron-based heartbeat triggers are used.

## 12. Acceptance criteria

### 12.1 x402 buyer mode
- When an agent hits a paywalled endpoint:
  - Orchestack detects 402
  - creates PaymentIntent with idempotency
  - enforces policy/budgets
  - successfully settles and retries
  - stores proof (PAYMENT-RESPONSE + tx hash) linked to the Task

### 12.2 x402 seller mode
- Orchestack endpoint returns compliant 402 challenge and processes payment successfully.
- Double-submission of the same payment intent is idempotent.

### 12.3 ERC-8004 identity
- Homarus can be registered on a configured chain/registry.
- Registration file is published and retrievable.
- Orchestack can refresh/update agentURI under policy control.

### 12.4 Auditability
- Every payment and trust operation is traceable:
  - `task_id` ↔ `payment_intent_id` ↔ `tx_hash` (if available)
  - all logs include trace_id

## 13. Rollout plan (recommended)

- **Phase A (MVP):** x402 buyer mode integrated into HTTP tool + PaymentIntent ledger
- **Phase B:** ERC-8004 identity publish for Homarus + minimal Trust Service
- **Phase C:** x402 seller mode for selected Orchestack endpoints (multi-tenant ready)
- **Phase D:** ERC-8004 reputation + validation integration (policy-gated)
