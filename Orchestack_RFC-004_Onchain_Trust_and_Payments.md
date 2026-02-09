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
