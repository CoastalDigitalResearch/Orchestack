# Orchestack Architecture Response Document
**Project:** Orchestack  
**Prepared by (resident agent):** Homarus  
**Prepared for: System Architect**  
**Date: February 6, 2026**  
**Stakeholders: IT Director + Principal Developer + AI Researcher**

---

## EXECUTIVE SUMMARY

After analyzing the 78-question architecture questionnaire through three lenses—IT infrastructure, software engineering, and AI research—we've identified a **unified architectural vision** that balances enterprise security, developer ergonomics, and cutting-edge AI capabilities.

**Core Principle:** Build for enterprise adoption from day one, but don't let enterprise constraints stifle innovation. Use progressive disclosure: strict defaults with escape hatches for power users.

---

## SECTION-BY-SECTION RESPONSES

### 1) Outcomes, Scope, and Non-Goals

| Question | Response | Rationale |
|----------|----------|-----------|
| **P0: Top 3 measurable outcomes** | 1. **Handle 100+ concurrent agent sessions** with sub-500ms response latency<br>2. **Reduce agent deployment time from hours to minutes** (Dayana provisioning <30s)<br>3. **Automate 80% of routine infrastructure tasks** via system agents | Infrastructure scalability, operational efficiency, ROI demonstration |
| **P0: Explicitly out of scope for v1** | • Voice calling (P2)<br>• Image generation pipelines<br>• GUI automation (RPA-style)<br>• Mobile device nodes<br>• Real-time video processing | Focus on text/code agent core; defer until v2 when patterns stabilize |
| **P1: OpenClaw parity requirement** | **"Parity only for what we use"** — Non-negotiable features:<br>• Discord/Telegram connectors<br>• Subagent spawning<br>• File/memory tools<br>• Web search/fetch<br>• Node remote execution<br>• Cron scheduling | Don't over-commit to unused features; focus on validated use cases |
| **P1: Primary user persona** | **Internal operators only for v1**<br>Selected external users (v1.5)<br>Multi-tenant SaaS (v2) | Crawl-walk-run: prove internal value before external exposure |

---

### 2) Tenancy and Isolation Model

| Question | Response | Rationale |
|----------|----------|-----------|
| **P0: Single vs multi-tenant** | **Single-tenant (our org only) for v1**<br>Architecture supports multi-tenant via namespace isolation for v2 | Enterprise IT: start controlled; Developer: design for future scale |
| **P0: Isolation requirements** | **Namespace isolation** minimum<br>**Cluster isolation** for air-gapped deployments<br>RBAC + network policies everywhere | Defense in depth; IT compliance; research isolation |
| **P1: Per-team/project separation** | **Yes — "workspaces" as unit of ownership**<br>Ownership: **agent-level** (not team/project to avoid complexity) | Research: agent-level granularity matches cognitive boundaries |
| **P1: Air-gapped deployments** | **Yes — anticipated for sensitive workloads**<br>Full offline capability required for memory embeddings | AI researcher: critical for sensitive IP/proprietary models |

---

### 3) Identity, Authentication, and LDAP RBAC

| Question | Response | Rationale |
|----------|----------|-----------|
| **P0: Identity source-of-truth** | **LDAP + OIDC (SSO) for humans**<br>LDAP as group source, OIDC for auth<br>Service accounts: Kubernetes + mTLS | IT: integrates with existing IdP; Developer: standard patterns |
| **P0: Service-to-service identity** | **SPIFFE/SPIRE** for workload identity<br>Mutual TLS everywhere<br>Short-lived SVIDs (24h max) | Security best practice; automatic rotation |
| **P0: RBAC objects in LDAP** | **Roles:** operator, agent-owner, auditor, infra-admin<br>**Groups per capability:** can_spawn_subagents, can_use_network, can_write_memory_L2, can_apply_infra_changes | Least privilege; IT governance |
| **P0: Agent policy creation rights** | **"Agent owners" with admin guardrails**<br>Self-service for authenticated users with budget caps | Balance autonomy with control |
| **P1: Break-glass access** | **Yes — required for incident response**<br>Controls: 4-hour time-bound, dual approval, full audit log, hardware MFA | IT compliance; emergency procedures |

---

### 4) Agent Types, Hierarchy, and Delegation

| Question | Response | Rationale |
|----------|----------|-----------|
| **P0: Agent taxonomy** | 1. **User-facing assistants** (chat agents)<br>2. **Background workers** (batch/reporting)<br>3. **System agents** (infrastructure)<br>4. **Connector agents** (per-channel) | Clear separation of concerns |
| **P0: Nested subagents** | **Single level sufficient for v1**<br>Architecture supports nesting for v2 | Simpler to reason about; defer complexity |
| **P0: Delegation controls** | • Max depth: 2 (parent → child)<br>• Max concurrent children: 8<br>• Max tokens/cost per parent: configurable per agent<br>• Max wall time per child: 1 hour (extendable)<br>• Tool inheritance: whitelist, not blacklist | Prevent runaway costs; safety guardrails |
| **P1: Subagent memory view** | **Isolated memory view (default deny)**<br>Explicit share via memory L3 (shared org) | Security default; researcher: mimics human team structure |
| **P1: Workspace assignment** | **Deterministic per-task folder**<br>`/workspaces/{agent-id}/{task-id}/`<br>Ephemeral for background jobs | Reproducibility; auditability |
| **P2: Different runtimes** | **Yes — toolkit differentiation**<br>Code agent: heavy IDE tools<br>Research agent: web + memory tools<br>Infra agent: kubectl + terraform only | Specialized capabilities per role |

---

### 5) Execution Plane with Daytona

| Question | Response | Rationale |
|----------|----------|-----------|
| **P0: "Execution environment" definition** | Core: shell + git + Python/Node/Go runtimes<br>Extended: browser automation, kubectl/oc, ansible<br>Future: GPU access (flag-gated) | Match current OpenClaw capabilities |
| **P0: Daytona sandbox lifecycle** | **Ephemeral by default** (destroy after task)<br>**Persistent option** for long-running agents (opt-in) | Security + resource efficiency |
| **P0: Network egress defaults** | **Deny-all by default with allowlist per agent**<br>Explicit domain/IP list in agent policy | Zero trust; IT compliance |
| **P0: Filesystem policy** | **No direct host mounts**<br>Read-only "reference" volumes via PVC<br>Secrets via External Secrets Operator<br>Config via ConfigMap | Security hardening |
| **P1: Resource controls** | CPU: 0.5-4 cores per sandbox<br>Memory: 512MB-8GB<br>Disk: 10GB default<br>Network: rate-limited egress<br>Max concurrent: 20 per agent<br>GPU: 0 for v1 | Resource fairness; cost control |
| **P1: Reproducible builds** | **Yes — pinned base images per agent**<br>Image digest in agent manifest<br>Immutable tags only | Reproducibility; supply chain security |
| **P2: User-extensible images** | **Centrally curated only for v1**<br>Custom Dockerfile support in v2 after security review | Security first; innovation later |

---

### 6) Memory System (Hierarchical, File-Based, Cluster-Optimized)

| Question | Response | Rationale |
|----------|----------|-----------|
| **P0: Memory layers** | Confirm: **L0-L4 all required**<br>• L0: Scratch (session-only)<br>• L1: Working (agent-private)<br>• L2: Durable agent memory<br>• L3: Shared org/team<br>• L4: Archive (cold storage) | Matches cognitive science + practical needs |
| **P0: Canonical format** | **Markdown + frontmatter metadata**<br>YAML frontmatter for structured fields<br>Body for narrative content | Human-readable; machine-parseable |
| **P0: Promotion/demotion rules** | **Hybrid approach:**<br>• Heuristic for L0→L1 (recency + usage)<br>• Explicit "memory write" tool for L1→L2<br>• Scheduled compaction for L2→L3→L4 | Balance automation with intent |
| **P0: Retention policy** | L0: 24 hours<br>L1: 7 days<br>L2: 90 days or 10MB per agent<br>L3: 1 year or 100MB per team<br>L4: indefinite, compressed | Tiered storage economics |
| **P0: Cross-agent memory access** | **No agent reads another's L2** (strict isolation)<br>**L3 curated by team leads**<br>Write approval workflow for L3 | Privacy + collaboration balance |
| **P1: Encryption-at-rest** | **Yes — beyond provider defaults**<br>Key management: HashiCorp Vault or AWS KMS<br>Per-tenant keys for multi-tenant future | Compliance; defense in depth |
| **P1: Retrieval approach** | **Vector hybrid + reranking**<br>BM25 for lexical fallback<br>Local embeddings: sentence-transformers/all-MiniLM-L6-v2<br>Max latency: 500ms for retrieval | Performance + accuracy tradeoff |
| **P1: Embedding APIs** | **Local embeddings required** (no external calls)<br>Optional: external API for higher quality (opt-in) | Privacy default; quality escape hatch |
| **P1: Provenance in retrieval** | **Yes — exact file + line ranges**<br>Citations mandatory in responses | Explainability; verification |
| **P2: Versioning** | **Yes — git-style history**<br>Audit trail + rollback capability<br>Stored as Git repo in L4 | Research: critical for reproducibility |

---

### 7) Off-Cluster Storage and Artifact Management

| Question | Response | Rationale |
|----------|----------|-----------|
| **P0: Preferred storage** | **Both: S3-compatible for artifacts, NAS for shared work**<br>MinIO primary (on-prem S3)<br>NFS for team collaboration spaces | Flexibility; performance |
| **P0: RPO/RTO targets** | RPO: 1 hour (near-real-time sync)<br>RTO: 4 hours for full recovery<br>Memory L2-L3: 15 min RPO | Business continuity |
| **P1: Artifact types** | Logs, transcripts, code repos/patches, binaries, datasets, screenshots | Full audit trail |
| **P1: Data residency** | **On-prem only option required**<br>Regional constraints for multi-tenant (EU data stays EU) | Compliance; GDPR readiness |

---

### 8) NATS Bus: Semantics and Topology

| Question | Response | Rationale |
|----------|----------|-----------|
| **P0: Durable streams** | **JetStream required** for tasks/events<br>Best-effort only for telemetry | Reliability for critical ops |
| **P0: Delivery semantics** | • Telemetry: at-most-once<br>• Tasks: at-least-once<br>• State changes: exactly-once (via idempotency keys) | Match criticality to guarantees |
| **P0: Ordering** | **Per-session ordering** (chat continuity)<br>Per-agent for state changes<br>Avoid global ordering (scalability bottleneck) | Performance + correctness balance |
| **P1: Message sizes** | **Store payloads in object store, pass references**<br>Max NATS message: 1MB | Efficiency; NATS limits |
| **P1: Security** | **mTLS + JWT**<br>Per-tenant subject permissions<br>NKeys for service accounts | Defense in depth |

---

### 9) Connector Plugin System

| Question | Response | Rationale |
|----------|----------|-----------|
| **P0: Required connectors (ranked)** | 1. Discord (primary)<br>2. Slack (enterprise)<br>3. Email (SMTP/IMAP)<br>4. Telegram<br>5. Webchat | Match current usage patterns |
| **P0: Singleton session connectors** | **WhatsApp in scope** (your use case)<br>Signal optional | Your explicit requirement |
| **P1: Message volume** | 50 concurrent conversations<br>100 messages/minute peak<br>10MB max attachment | Capacity planning |
| **P1: Delivery guarantees** | **At-least-once with dedupe**<br>Idempotency keys per message | Practical reliability |
| **P1: Identity mapping** | **Map connector IDs to LDAP via lookup table**<br>Discord/Slack user → LDAP group membership | RBAC continuity |
| **P2: Hot-reload** | **Deploy-time only for v1**<br>Hot-reload in v2 after security review | Stability first |

---

### 10) Model Router Requirements

| Question | Response | Rationale |
|----------|----------|-----------|
| **P0: Model providers** | **Both: hosted APIs + local models**<br>Hosted: OpenAI, Anthropic, OpenCode Zen<br>Local: vLLM on Mac Studio, llama.cpp on Hyde | Flexibility; cost control; privacy |
| **P0: Routing criteria (priority)** | 1. Privacy (sensitive data → local)<br>2. Cost (budget optimization)<br>3. Quality (task complexity)<br>4. Latency (user-facing vs batch)<br>5. Context length | Privacy-first default |
| **P0: Per-tenant/agent budgets** | **Yes — daily budgets with soft/hard limits**<br>Alerts at 80%, block at 100%<br>Monthly rollover option | Cost governance |
| **P1: Fallback rules** | 1. Same provider, different model<br>2. Different provider (if privacy allows)<br>3. Degrade to local model with warning | Graceful degradation |
| **P1: Evaluation harness** | **Manual tuning for v1**<br>Closed-loop automatic routing in v2 (requires eval infra) | Crawl-walk-run |
| **P1: Policy gating** | **Yes — "infra agents → on-prem only"**<br>Tag-based routing: `privacy:sensitive` → local models | Compliance enforcement |
| **P1: OpenClaw-model-router behaviors** | Preserve: classifier logic, cost tracking, model registry format<br>Add: policy gating, budget enforcement | Compatibility + enhancement |

---

### 11) Scheduling and Heartbeat

| Question | Response | Rationale |
|----------|----------|-----------|
| **P0: Scheduled job types** | • Health checks (every 30s)<br>• Memory compaction (daily 2am)<br>• Index refresh (hourly)<br>• Infra reconciliation (every 5min)<br>• Token refresh (before expiry) | Comprehensive coverage |
| **P0: Job requirements** | • Missed: catch-up for stateful, skip for idempotent<br>• Concurrency: single-flight for infra, overlap OK for reports<br>• Idempotency: UUID keys for all | Reliability patterns |
| **P1: Timezone** | **Configurable per tenant**<br>Default UTC<br>Override per agent | Global operations |

---

### 12) System Agents and Infrastructure Maintenance

| Question | Response | Rationale |
|----------|----------|-----------|
| **P0: System agent permissions** | **Propose changes (PRs/manifests) for v1**<br>Auto-apply only for whitelist (restarts, non-destructive)<br>Full auto in v2 after maturity | Safety first |
| **P0: Infrastructure surfaces** | • OpenShift/K8s resources<br>• Nodes (via SSH/Ansible)<br>• Networking (DNS/LB)<br>• External servers (limited)<br>• Storage systems | Full stack coverage |
| **P1: Approval workflows** | **Human approval for destructive changes**<br>Auto-remediation for: pod restarts, service reconciliation, config drift (non-destructive) | Balance autonomy + safety |
| **P1: Runbooks source-of-truth** | **Git repo (primary) + Memory L3 (cache)**<br>Sync: git → L3 on commit<br>Agent reads from L3 (faster) | Speed + auditability |

---

### 13) Observability, Audit, and Governance

| Question | Response | Rationale |
|----------|----------|-----------|
| **P0: Audit requirements** | **Record every tool call**<br>Inputs: hashed (privacy)<br>Outputs: hashed + truncated<br>Metadata: full retention<br>Secrets: redacted automatically | Compliance; privacy |
| **P0: Log retention** | 90 days hot, 1 year warm, 7 years cold (compliance) | Regulatory requirements |
| **P1: Tracing** | **Yes — end-to-end OpenTelemetry**<br>Connector → Router → Agent → Daytona → Memory<br>Trace ID propagated via NATS headers | Full observability |
| **P1: SLOs** | • Interactive chat: p95 < 2s<br>• Background tasks: 95% complete in 1 hour<br>• Memory retrieval: p95 < 500ms | User experience targets |
| **P2: Explainability** | **Yes — required for v1.5**<br>Report: memory hits (file + line), tools used, model selected, routing decision | Trust + debugging |

---

### 14) Security Posture and Threat Model

| Question | Response | Rationale |
|----------|----------|-----------|
| **P0: Threat model** | Priority: 1. Compromised connector tokens<br>2. Prompt injection via untrusted content<br>3. Malicious internal users<br>4. Supply-chain risks<br>5. External attackers | Risk-based defense |
| **P0: Secret management** | **External secret manager required: HashiCorp Vault**<br>Kubernetes External Secrets Operator<br>Rotation: 90 days for API keys, 24h for tokens | Enterprise grade |
| **P0: Data classification** | **Yes — PII/PHI anticipated**<br>Prepare for HIPAA (healthcare use case)<br>SOC2 Type II target | Compliance-ready |
| **P1: Network policy** | **Zero-trust east-west**<br>Strict egress for services<br>Deny-all default for Daytona sandboxes | Defense in depth |
| **P1: Content scanning** | **Yes — DLP for memory writes**<br>Pattern matching for PII<br>Outbound message scanning | Data loss prevention |

---

### 15) Portability Targets

| Question | Response | Rationale |
|----------|----------|-----------|
| **P0: "Servers with Podman" meaning** | **Small HA cluster without Kubernetes**<br>3-5 nodes with Podman + systemd<br>For: edge deployments, cost-sensitive environments, air-gapped sites | Deployment flexibility |
| **P1: Minimum portable substrate** | **systemd + podman + cron**<br>Docker Compose for orchestration<br>k3s as upgrade path | Lowest common denominator |
| **P1: Security parity** | **Same security guarantees in all modes**<br>Implementation varies (K8s NetworkPolicy vs Podman network)<br>Effect: identical | Security doesn't degrade |

---

## SYNTHESIZED ARCHITECTURAL PRINCIPLES

From the three-perspective analysis, these principles emerged:

### 1. **Progressive Security Disclosure**
Strict defaults (deny-all, local embeddings, ephemeral sandboxes) with documented escape hatches for power users. This satisfies IT compliance without blocking AI research.

### 2. **Agent-Centric Design**
Ownership at agent level (not team/project) matches how AI researchers think about cognitive boundaries. Teams share via L3 memory, not shared agent instances.

### 3. **GitOps for Everything**
Runbooks, policies, agent definitions — all in git. Memory L3 is a cache, git is source-of-truth. This gives developers auditability + AI systems speed.

### 4. **Privacy-First Model Routing**
Default to local models for sensitive data, external APIs only for non-sensitive + quality-critical tasks. Explicit policy gating enforces this.

### 5. **Tiered Memory = Tiered Storage Economics**
Hot (in-cluster) → Warm (NAS) → Cold (object) → Archive (compressed git). Cost optimization without losing researcher access to historical context.

---

## RECOMMENDED IMPLEMENTATION ORDER

**Phase 1 (MVP - 6 weeks):**
- Tenancy: Single-tenant, namespace isolation
- Identity: LDAP + OIDC, SPIFFE service mesh
- Execution: Daytona ephemeral sandboxes, deny-all egress
- Memory: L0-L2 only, local embeddings, hybrid retrieval
- Bus: NATS JetStream, per-session ordering
- Connectors: Discord, Slack, Email
- Router: Local + OpenCode Zen, budget enforcement

**Phase 2 (Enterprise - +6 weeks):**
- L3-L4 memory, cross-team sharing workflows
- System agents with approval workflows
- Full observability + explainability
- DLP + compliance scanning
- Podman portability

**Phase 3 (Scale - +3 months):**
- Multi-tenant architecture
- Hot-reload plugins
- Closed-loop model routing
- GPU support

---

## UNRESOLVED QUESTIONS FOR ARCHITECT

1. **Daytona specifics:** Version? Self-hosted or managed? GPU node integration timeline?
2. **NATS deployment:** Single cluster or per-tenant? JetStream storage backend (PVC vs external)?
3. **Vault deployment:** Existing or new? Kubernetes auth method?
4. **Embedding models:** Local model choice (all-MiniLM-L6-v2 sufficient? Need larger for code?)
5. **OpenShift version:** 4.15+? Any deprecated APIs we should avoid?

---

**Document prepared by:** Homarus  
**For review by:** Adam + System Architect  
**Next step:** Architect review + Phase 1 detailed design

---

Ready for your review and refinement.
