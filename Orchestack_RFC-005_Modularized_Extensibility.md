# RFC-005: Modularized Extensibility Framework (Tools, Skills, Memory, Storage, Loops, Scheduling)

**Project:** Orchestack  
**Resident agent name:** Homarus  

**Status:** Draft (v1)  
**Last updated:** 2026-02-07  
**Source of requirements:** Architecture Response Document (repo copy: `Orchestack_Architecture_Response.md`; original: `Homarus_2.0_Architecture_Response.md`), dated 2026-02-06

---

## 1. Summary

This RFC defines the **Orchestack Extensibility Framework (OEF)**: a modular, secure-by-default, GitOps-compatible system for extending Orchestack with:

- **Tools** (sandbox-executed and service-provided)
- **Skills** (declarative procedures/macros that compose tools + prompts)
- **Memory** (indexers/retrievers and optional additional memory “collections”)
- **Storage backends** (object/NAS drivers and artifact stores)
- **Agent loops** (declarative loop specs and optionally loop services)
- **Scheduling** (portable schedule/job specs that compile to local schedulers)

The framework is designed so that **humans and agents** can create extensions safely via:
- a small **manifest standard** (YAML, validated against schemas)
- **scaffolding templates** and an SDK
- a **GitOps promotion path** (PR → review → build → scan → sign → deploy)

OEF intentionally avoids “dynamic in-process plugins” for control-plane services. Extensions run as **containers** (or are purely declarative), communicate through stable protocols, and are governed by **capability grants** (RFC-002) and the event backbone (RFC-001).

---

## 2. Goals and non-goals

### 2.1 Goals (v1)

1. Provide a single, easy-to-author **Extension Manifest** standard for all extension types.
2. Support **deploy-time installation** of extensions through GitOps reconciliation.
3. Support safe extension authoring by:
   - humans (CLI + templates)
   - agents (generate PRs; no direct deploy rights)
4. Preserve Orchestack’s trust boundaries:
   - **Execution** happens in **Daytona sandboxes** by default (RFC-002).
   - Service extensions run with least privilege and strong isolation.
5. Make extensions portable across:
   - OpenShift / Kubernetes
   - “servers running Podman” (systemd + podman + cron)
6. Provide a governance model: signing, SBOMs, scanning, allowlists, trust tiers.

### 2.2 Non-goals (v1)

- Hot-reload of executable extensions in production without redeploy (planned for v2, restricted to specific categories).
- Arbitrary dynamic code loading inside the orchestrator/router/memory plane processes.
- A “public marketplace” for third-party extensions in v1 (the design allows it later, but v1 assumes controlled internal registry).

---

## 3. Terminology

- **Extension (Ext):** A packaged capability that augments Orchestack.
- **Extension Package:** A unit of distribution (Git directory and/or OCI image + manifest).
- **Extension Manifest (ExtMan):** YAML describing the extension, its interfaces, security requirements, and compatibility.
- **Extension Registry:** Authoritative catalog (Postgres) of installed and enabled extensions, versions, and descriptors.
- **Extension Controller:** Reconciles desired-state from Git into the runtime platform (K8s/Podman), updates the registry.
- **Trust tier:** Security classification that drives required controls and approval gates.
- **Tool:** A callable operation exposed to agent runs. Tools MUST be policy-gated and audited.
- **Skill:** A declarative recipe that composes tools/models/memory patterns.
- **Loop:** The control logic that turns messages/tasks into actions (model calls, tool calls, memory ops).
- **Schedule Job:** A portable scheduled task definition that triggers Orchestack tasks using local schedulers.

---

## 4. Design principles

1. **Progressive disclosure:** strict defaults, explicit escape hatches.
2. **GitOps for everything:** desired state is stored in Git, reconciled into runtime.
3. **Least privilege and capability grants:** extensions declare required capabilities; grants are computed by policy (RFC-002).
4. **Portable packaging:** containers + manifests; avoid platform-specific assumptions.
5. **Clear trust boundaries:** execution in Daytona, services isolated by the platform; no long-lived secrets in sandboxes.
6. **Strong supply-chain posture:** pinned digests, SBOMs, signing, and vulnerability scanning.

---

## 5. Extension taxonomy

OEF defines six first-class extension types (plus optional connector extensions).

### 5.1 Tool Extensions

Tools come in two execution modes:

#### A) Sandbox Tools (default)
- Executed inside a Daytona sandbox via the Daytona Executor.
- Suitable for: scripts, CLIs, build tools, repo ops, data transforms.
- Security: inherits Daytona resource cordons and egress allowlists.

#### B) Service Tools (restricted)
- Executed by an in-cluster service that implements the tool protocol.
- Suitable for: privileged integrations (payments signer), memory indexers, connectors, infra adapters.
- Security: isolated service account, NetworkPolicy, Vault-scoped secrets, strict auditing.

### 5.2 Skill Extensions

- Declarative procedures/macros.
- No executable code.
- Refer to tools by `tool_id` and provide:
  - parameter templates
  - validation rules
  - best-practice prompts
  - “explainability hints” (what to cite, what to log)

### 5.3 Memory Extensions

Two categories:

#### A) Indexer/Retriever plugins (service extensions)
- Provide additional retrieval methods (BM25-only, vector-only, hybrid, rerankers).
- QMD-style sidecars fit here.
- MUST provide provenance (file + line ranges) where possible.

#### B) Memory collections (declarative)
- Adds named “collections” that map into existing tiers (L0–L4).
- Example: `L2:engineering-decisions`, `L3:runbooks-cache`.
- In v1, **new tiers beyond L0–L4 are not supported**. Collections are supported if they map to existing tier semantics.

### 5.4 Storage Extensions

- Add/replace implementations for:
  - object store (S3-compatible, cloud S3, etc.)
  - NAS backends (NFS variants)
  - artifact stores (tiered retention)
- Storage extensions are privileged and typically **Tier 2/3**.

### 5.5 Agent Loop Extensions

Loop extensions define “how the agent reasons” and therefore are highly sensitive.

Two modes:

#### A) Declarative LoopSpec (recommended for v1)
- YAML-defined state machine / workflow graph.
- References models, tools, and skills.
- Safe by default because it is validated and constrained.

#### B) Loop Service (v2+)
- A dedicated loop runner service, isolated from the orchestrator.
- Requires higher trust tier and explicit approvals.

### 5.6 Scheduling Extensions

Scheduling extensions define jobs that run via a **local scheduler**:
- Kubernetes/OpenShift: CronJobs
- Podman mode: system cron or systemd timers

Scheduling extensions are declarative and compile to platform-specific scheduler resources.

---

## 6. Extension Manifest standard (ExtMan)

### 6.1 Manifest overview

All extension packages MUST include an `extension.yaml` at the root.

```yaml
apiVersion: orchestack.io/ext/v1alpha1
kind: Extension
metadata:
  id: "com.acme.tools.gitops"
  name: "GitOps Utilities"
  version: "1.2.0"
  description: "Tools and skills for GitOps workflows."
  license: "Apache-2.0"
  maintainers:
    - name: "Platform Team"
      email: "platform@example.com"
spec:
  type: tool|skill|memory|storage|loop|schedule|connector
  compatibility:
    orchestack_api: ">=1.0.0 <2.0.0"
    ext_api: "v1alpha1"
  trust:
    tier: 0|1|2|3
    rationale: "Why this tier is required."
    approvals:
      required: true|false
      reviewers_ldap_groups: ["orchestack-auditors", "orchestack-infra-admins"]
  security:
    signing:
      required: true
      public_keys:
        - "cosign://k8s://orchestack/cosign-pubkey"
    sbom:
      required: true
      format: "spdx|cyclonedx"
    vuln_scan:
      required: true
      max_cvss: 7.0
    secrets:
      required: ["vault://kv/orchestack/discord/token"]
    network:
      egress:
        default: "deny"
        allow:
          - "api.github.com:443"
          - "vault.service.local:8200"
  interfaces:
    tools: []
    skills: []
    memory: {}
    storage: {}
    loop: {}
    schedule: []
  artifacts:
    oci_images:
      - name: "ghcr.io/acme/orchestack-ext-gitops"
        digest: "sha256:..."
    bundles:
      - path: "bundles/gitops-tools.tar.gz"
        sha256: "..."
  observability:
    otel:
      enabled: true
    audit:
      level: "metadata|full"
```

### 6.2 Trust tiers (normative)

- **Tier 0 (Config-only):** declarative specs only (skills, schedules, loop specs). No code execution.  
  - Approval: recommended.
- **Tier 1 (Sandbox-executed):** executable artifacts run only inside Daytona sandboxes.  
  - Approval: required if it adds new outbound egress domains.
- **Tier 2 (Service extension):** in-cluster service with explicit network/secrets.  
  - Approval: required; signing + SBOM + scanning mandatory.
- **Tier 3 (Privileged):** infra-impacting or cluster-admin adjacent extensions.  
  - Approval: required; break-glass policies apply.

---

## 7. Protocols and contracts

### 7.1 Tool Protocol (Orchestack Tool Protocol, OTP)

All tools MUST be invocable via a stable request/response protocol. OEF supports two backends:

- **NATS request/reply** (preferred inside cluster)
- **HTTP/gRPC** (for Podman mode or edge deployments)

#### 7.1.1 Tool descriptor

Each tool MUST have a descriptor with:
- `tool_id` (globally unique)
- name, description
- `input_schema` (JSON Schema)
- `output_schema` (JSON Schema)
- risk class (low/med/high)
- idempotency behavior
- required capabilities
- data classification constraints
- audit level requirements

Descriptors are stored in the Extension Registry and are discoverable by orchestrator and UI.

#### 7.1.2 NATS subjects

- Request: `tools.{tool_id}.call`
- Response: NATS reply subject (standard request/reply)
- Tool events: `tools.{tool_id}.events` (optional; long-running progress)

Requests and responses MUST use the RFC-001 envelope and MUST carry:
- `idempotency_key`
- `capability_grant_id`
- `trace_id`

Payloads larger than NATS limits MUST use `payload_ref` (RFC-001).

### 7.2 Skill specification

A Skill is a declarative object with:
- `skill_id`
- parameters + validation rules
- steps that reference `tool_id` and/or model calls via the Model Router
- optional “guardrails” (required approvals, required citations, DLP mode)

Skills MUST be pure data; no embedded executable code.

### 7.3 Memory plugin contract

Memory plugins MUST implement:

- `index(updates[]) -> index_version`
- `search(query, scope, k, filters) -> hits[]`
- `explain(hit) -> provenance`

Where `hits[]` MUST include:
- `file_ref` (tier/collection/path)
- `line_ranges` (where applicable)
- `score` and `method` (bm25/vector/hybrid)

### 7.4 Storage driver contract

Storage drivers MUST implement:

- `put(ref, bytes|stream, metadata) -> etag/version`
- `get(ref, range?) -> bytes|stream`
- `list(prefix, filters) -> refs[]`
- `delete(ref) -> ok`
- optional: `lock(ref, ttl)` for singleton semantics

Storage drivers MUST support encryption-at-rest integration and key rotation hooks.

### 7.5 LoopSpec contract

A LoopSpec MUST define:

- entrypoints (`on_message`, `on_task`, `on_schedule`)
- state machine nodes with:
  - model calls (via Router)
  - tool calls (via Tool Protocol)
  - memory ops (via Memory Plane)
- budget limits:
  - max tokens/cost
  - max tool calls
  - max wall time
- output contracts (structured response shape)

LoopSpecs are validated and executed by a LoopRunner component (may be in orchestrator v1, moved out-of-process later).

### 7.6 ScheduleSpec contract

A ScheduleSpec MUST define:

- schedule (cron + timezone)
- concurrency policy (single-flight / allow overlap)
- missed-run policy (catch-up / skip)
- Task template (what to enqueue on NATS)
- idempotency key strategy

ScheduleSpecs compile to:
- Kubernetes CronJob manifests (K8s/OCP)
- cron/systemd units (Podman mode)

---

## 8. Extension lifecycle and governance

### 8.1 GitOps workflow (v1)

1. **Author** extension package in Git:
   - `extension.yaml`
   - descriptors/specs/schemas
   - code (optional; for service/sandbox extensions)
2. Open PR. Agents may generate the PR, but cannot merge.
3. CI pipeline runs:
   - schema validation
   - unit tests
   - integration tests (optional env)
   - SBOM generation
   - vulnerability scan
4. If passing, CI builds OCI images and signs them.
5. Merge triggers the Extension Controller reconciliation:
   - installs/updates extension in the runtime
   - registers descriptors in the Extension Registry
   - emits `ext.*` events

### 8.2 Runtime enablement

Extensions are installed but not necessarily enabled for all agents.
AgentDefinitions (git) declare allowed extensions by:
- extension id and version range
- allowed tool_ids / skill_ids

Policy service enforces:
- org-level allowlists/denylists
- trust tier requirements
- capability grants

### 8.3 Hot reload (v2)

Hot reload is a future feature:
- allowed only for Tier 0 (declarative) and selected Tier 1 artifacts
- still requires signature verification and policy checks
- can be disabled entirely in hardened environments

---

## 9. Extension Registry (authoritative catalog)

The Extension Registry is a Postgres-backed catalog with:

- installed extensions (id, version, digest, trust tier, enabled)
- tool descriptors
- skill specs
- memory plugin endpoints
- storage driver endpoints
- loop specs
- schedule specs

The registry is the source of truth for discovery and UI visualization.
Git remains the desired state; the registry reflects installed state.

---

## 10. Security and compliance requirements

1. **No long-lived secrets in Daytona sandboxes.**
2. **All executable extensions MUST be signed** and pinned by digest.
3. **Supply chain:** SBOM + scan gating required for Tier 2/3.
4. **Network:** deny-by-default egress for extensions; allowlists required.
5. **Audit:** all tool invocations MUST emit audit metadata (hashed inputs/outputs where required).
6. **DLP:** skill/tool descriptors may require DLP scanning for certain outputs or memory writes.

---

## 11. Observability

- All extension services MUST emit OpenTelemetry traces and metrics.
- Tool calls MUST be correlated via `trace_id`, `task_id`, `run_id`, `step_id`.
- Extension Controller MUST expose reconciliation status and drift metrics.

---

## 12. Portability requirements

OEF MUST work in three deployment modes:

1. **OpenShift / Kubernetes**
   - Extension Controller deploys extension services as Deployments/Jobs
   - ScheduleSpecs compile to CronJobs
2. **Podman HA (systemd + podman + cron)**
   - Extension Controller deploys as systemd-managed podman containers
   - ScheduleSpecs compile to cron/systemd timers
3. **Air-gapped**
   - All extension artifacts must be available via local Git + local OCI registry
   - No required external build-time dependencies

---

## 13. Examples

### 13.1 Skill-only extension (Tier 0)

```yaml
apiVersion: orchestack.io/ext/v1alpha1
kind: Extension
metadata:
  id: "orchestack.skills.incident-triage"
  name: "Incident Triage Skill Pack"
  version: "0.1.0"
spec:
  type: skill
  trust:
    tier: 0
  interfaces:
    skills:
      - skill_id: "incident.triage.v1"
        description: "Triage an incident and produce a runbook-linked plan."
        params_schema:
          type: object
          properties:
            severity: { type: string, enum: ["sev1","sev2","sev3"] }
            system: { type: string }
          required: ["severity","system"]
        steps:
          - type: "memory.search"
            scope: { tiers: ["L3"] }
            query: "runbook {system}"
          - type: "model.call"
            router_policy: { privacy: "sensitive" }
          - type: "tool.call"
            tool_id: "git.create_pr"
```

### 13.2 Sandbox tool bundle (Tier 1)

- Provide a tarball of scripts (`bundles/*.tar.gz`) plus a tool descriptor that tells the Daytona Executor how to run it.
- The Daytona Executor fetches the bundle from object storage, verifies checksum, extracts into the sandbox workspace, then executes.

### 13.3 Memory indexer plugin (Tier 2)

- Deploys a service implementing the memory plugin contract (`index/search/explain`).
- Registered in the Extension Registry as a memory plugin.

### 13.4 Schedule extension (Tier 0)

- Defines a daily memory compaction trigger that enqueues a task on NATS.
- Compiles to CronJob/cron.

---

## 14. Implementation plan (recommended)

### 14.1 v1 deliverables

1. Extension manifest schema + validation tooling (`orchestack-ext lint`)
2. Extension Controller (GitOps reconciliation) with:
   - install/update/disable
   - registry population
3. Tool descriptor registry and discovery API
4. Tier 0 + Tier 1 support:
   - skills
   - schedule specs
   - sandbox tool bundles
5. Tier 2 support for a small internal set:
   - memory indexer plugin interface
   - storage driver plug points (behind feature flags)

### 14.2 v2 deliverables

- Hot reload for Tier 0 and selected Tier 1.
- Loop service extensions.
- Public extension registry support with strict signing policies.

---

## 15. Open questions

1. Should the tool protocol default to NATS-only in v1, with HTTP/gRPC as an adapter in Podman mode?
2. Do we require cosign as the sole signing mechanism, or allow pluggable signers (still using Vault keys)?
3. How should extension-level budgets (cost/time/tool-call count) be represented and enforced across loops?

