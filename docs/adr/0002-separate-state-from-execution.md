# ADR-0002: Separate authoritative state from durable execution

- Status: accepted
- Date: 2026-08-01

## Context

Long-running agent tasks must survive failures, approvals, cancellation, and retries. Workflow history is optimized for deterministic continuation, while enterprise business state needs relational constraints, explicit ownership, querying, retention, and audit semantics.

## Decision

- PostgreSQL is authoritative for Case, Goal, Plan, Decision, Run, Task, Action, Approval, Outcome, Evidence metadata, and Release records.
- Temporal is authoritative for workflow history, timers, retries, signals, and continuation.
- State changes and event publication use transactional outbox; consumers use inbox/idempotency records.
- A workflow never treats its private history as proof that the external business outcome occurred.

## Consequences

- Recovery and business truth remain explicit.
- Dual-write coordination requires outbox/inbox patterns and reconciliation.
- Workflow code must be deterministic and avoid direct unversioned domain writes.

## Alternatives considered

- Store all state in workflow history: rejected for business authority and query limitations.
- Store orchestration only in database jobs: rejected for durable timers, signals, and recovery complexity.

## Verification

Integration tests must cover process restart, duplicate delivery, timeout with unknown outcome, cancellation, and resume after authorization changes.
