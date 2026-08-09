# Tool Invocation Contract

> Status: baseline · Last reviewed: 2026-08-09

## Invocation Envelope

Every governed external tool call must carry this envelope:

```yaml
invocation_id: uuid
tenant_id: uuid
run_id: uuid
task_id: uuid
action_id: uuid
actor_id: uuid
principal_id: uuid
agent_identity: string
delegation_ref: string
tool: string
tool_version: string
operation: string
resource_scope: string
arguments: object
argument_digest: sha256
risk_level: l0_compute | l1_read | l2_reversible_write | l3_high_impact_write | l4_privileged
idempotency_key: string
budget_ref: string
approval_ref: string | null
policy_version: string
expected_effect: string
deadline: rfc3339
traceparent: string
data_classification: public | internal | confidential | restricted
```

## Risk Levels

| Level | Examples | Default Controls |
|---|---|---|
| L0 Compute | Local reasoning, pure computation, no outbound generation | Sandbox, resource caps |
| L1 Read | Reading documents, querying business data | ACL, data minimization, audit |
| L2 Reversible Write | Creating drafts, reversible configuration | Explicit policy, idempotency, verification, compensation |
| L3 High-Impact Write | Issuing payments, publishing, deleting, external sends | Exact-parameter approval, dual-person optional, strong evidence |
| L4 Privileged | IAM, security policy, production infrastructure | Default deny autonomous execution; dedicated controlled process required |

## Execution Pipeline

```text
Resolve Identity
  → Verify Delegation
  → Policy Decision
  → Tool/Operation/Resource Scope Check
  → Schema & Semantic Validation
  → Risk Classification
  → Budget / Quota / Rate Check
  → Exact-Parameter Approval
  → Credential Brokering
  → Idempotency Reservation
  → Execute in Egress/Sandbox Boundary
  → Normalize Result
  → Verify Effect
  → Record Evidence and Audit
```

## Tool Result Semantics

Results must use unified status semantics:

| Status | Meaning |
|---|---|
| `accepted` | Request accepted by external system; outcome not yet confirmed |
| `succeeded` | Operation completed and verified |
| `failed` | Operation definitively failed |
| `denied` | Operation denied by external system's own authorization |
| `unknown` | Result cannot be determined; reconciliation required |

Additional result fields:

```yaml
status: accepted | succeeded | failed | denied | unknown
retryable: boolean
side_effect_possible: boolean
external_reference: string | null
verification_required: boolean
evidence_refs: [string]
output: object | null
error: object | null
```

## Approval Binding

- Approval is bound to exact `argument_digest` (SHA-256 of canonical sorted parameters).
- Any parameter change after approval produces a different digest → execution is rejected and re-approval is required.
- Approval has an expiry (`expires_at`). Expired approvals cannot authorize execution.
- Policy version is recorded in the approval. If policy changes, existing approvals may be invalidated.

## Idempotency

- Every write Action must carry a stable, unique `idempotency_key`.
- The Tool Gateway records every completed invocation by `idempotency_key`.
- Duplicate invocations return the cached result without re-executing.
- Idempotency records are tenant-scoped and retained according to data policy.
