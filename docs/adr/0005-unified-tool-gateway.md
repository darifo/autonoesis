# ADR-0005: All External Side Effects Through Unified Tool Gateway

- Status: accepted
- Date: 2026-08-09

## Context

Agent models, skills, and code paths all need to interact with external systems. Without a single enforcement point, authorization, idempotency, and audit become fragmented. Each integration path would need to independently implement the governance pipeline, creating gaps and inconsistency.

## Decision

- Every external side effect (API call, database write, message publish, file modification) must pass through the unified Tool Gateway.
- The Tool Gateway enforces a fixed execution pipeline: Identity → Delegation → Policy Decision → Schema Validation → Risk Classification → Budget/Quota Check → Exact-Parameter Approval → Credential Brokering → Idempotency Reservation → Execute → Verify Effect → Record Evidence and Audit.
- Tool Invocation Envelope carries: identity, delegation, tool version, operation, resource scope, argument digest, risk level, idempotency key, budget reference, approval reference, policy version, expected effect, deadline, and data classification.
- Tool Result uses unified semantics: `accepted | succeeded | failed | denied | unknown`, plus `retryable`, `side_effect_possible`, `verification_required`, and `evidence_refs`.

## Consequences

- A single pipeline ensures consistent governance regardless of how a tool is invoked.
- Adding new adapters (MCP, A2A, custom API) means implementing the Tool Gateway port—not rebuilding authorization.
- The pipeline is latency-sensitive; non-blocking checks (budget, idempotency) must be optimized.
- Direct integration bypassing the Gateway is a security boundary violation.

## Verification

- Tool Gateway tests cover all pipeline stages for each risk level.
- Adapter tests verify MCP and A2A tools route through the same Gateway.
- Negative tests confirm denied, expired-approval, and idempotency-collision paths.
