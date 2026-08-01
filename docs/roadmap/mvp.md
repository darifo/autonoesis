# MVP roadmap

## Phase 0 — Baseline

- [x] Monorepo and dependency boundaries
- [x] Architecture and initial ADRs
- [x] Contract, domain, application, and runtime seams
- [x] API health endpoint and worker bootstrap entry point
- [ ] Lock dependencies and add full CI after the initial review
- [ ] Define SQL model, migrations, outbox, inbox, and audit fields
- [ ] Select the first vertical use case and 10–20 evaluation cases

## Phase 1 — Minimum reliable loop

- Goal, Case, Session, Run, Task, Action, Outcome, and Evidence lifecycle
- PostgreSQL authoritative state and Temporal durable execution
- Context snapshot and one model adapter
- One read-only tool and one reversible write tool
- Execution-time authorization, approval, idempotency, cancellation, and recovery
- Cockpit Run timeline, approval, and evidence views
- Rule grader and human grader

## Exit evidence

The first vertical slice must pass normal, adversarial, duplicate-delivery, process-restart, timeout-unknown, and approval-denied scenarios without duplicate side effects.
