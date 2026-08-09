# Tool Gateway Threat Model

> Status: baseline · Last reviewed: 2026-08-09

## Scope

The Tool Gateway is the single enforcement point for all external side effects. Its compromise enables unauthorized writes, data exfiltration, credential theft, and audit bypass.

## Assets

- Tool credentials (API keys, certificates, service accounts)
- Authorization pipeline integrity
- Idempotency records
- Action execution history
- Credential brokering mechanism

## Threats

### TG-001: Gateway Bypass

**Description**: A component calls an external system directly, skipping the Tool Gateway's identity, delegation, policy, and approval checks.

**Controls**:
- All external outbound network access from Worker/Harness restricted to Tool Gateway.
- Network policy: Worker cannot reach external systems directly.
- Architecture dependency tests verify no direct external calls from non-Gateway packages.

### TG-002: Credential Leakage

**Description**: Tool credentials appear in prompts, logs, artifacts, or traces.

**Controls**:
- Credential brokering: short-lived credentials injected at execution time only.
- Credentials never enter Prompt, Context Snapshot, or agent memory.
- Log/Artifact scanning for credential patterns.
- Egress network allowlist restricts credential usage to authorized destinations.

### TG-003: Policy Decision Bypass

**Description**: Attacker manipulates the policy check to return `allow` for unauthorized operations.

**Controls**:
- Policy version recorded in every decision.
- Policy decision digest recorded in audit.
- Application-level hard invariants (not just OPA policies) for critical checks.
- Policy changes trigger re-evaluation of pending authorizations.

### TG-004: Idempotency Collision

**Description**: Two different Actions accidentally generate the same idempotency key, causing one to be incorrectly deduplicated.

**Controls**:
- Idempotency keys are UUIDs or tenant-scoped unique identifiers.
- Keys include action type and resource identifier.
- Collision detection: if cached result parameters differ from current Action parameters, reject as collision rather than silently returning wrong result.

### TG-005: Risk Level Misclassification

**Description**: A tool is registered with L1 (Read) but actually performs L3 (High-Impact Write) operations.

**Controls**:
- Tool registration requires explicit side effect class declaration.
- Tool adapter must implement verification that confirms the actual operation matches the declared risk level.
- Audit trail records actual vs. declared risk for anomaly detection.

### TG-006: Time-of-Check to Time-of-Use (TOCTOU)

**Description**: Authorization, budget, or approval state changes between when the check was performed and when the Action executes.

**Controls**:
- All checks re-executed atomically at execution time in the Gateway pipeline.
- Approval has explicit expiry.
- Budget reservation is made before execution, settled after.
- Policy version recorded; if policy changed since authorization, re-check required.
