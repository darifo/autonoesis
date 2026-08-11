# ADR-0013: Make PostgreSQL the Process-Independent Business Authority

- Status: accepted
- Date: 2026-08-11

## Context

The preview API used a hybrid store: Goal and Run could be delegated to SQLAlchemy while
Capability, Agent, Approval, Evidence, Candidate, Release, idempotency, and audit reads remained
in process memory. Worker Activities also created a new Store and Engine per invocation. Two
replicas therefore observed different accepted facts, process restart lost governance state, and
the initial Alembic revision dynamically imported current metadata instead of describing a frozen
historical schema.

## Decision

- PostgreSQL is the authority for accepted Goal, Run, Plan, Task, Action, Approval, Evidence,
  Outcome, Budget, Audit, Capability, Agent, configuration asset, Candidate, Trial, Deployment,
  Release, Kill Switch, idempotency, Inbox, and Outbox facts.
- Repository ports are organized around aggregates and use cases. Public production paths do not
  expose a generic CRUD Repository.
- Every tenant table references `tenants`, exposes `(tenant_id, id)` as a composite reference
  target, and uses tenant-composite foreign keys for aggregate relationships.
- Mutable aggregates use compare-and-swap on `optimistic_version`. Immutable writes rely on
  database unique, check, and foreign-key constraints.
- Stable Release pointers use a partial unique index over active `(tenant_id, stable_slot)` rows.
- Business writes append Audit and Outbox records in the same database transaction. Failure of any
  member rolls back the complete fact set.
- Migration history is self-contained. Revision `0001` explicitly describes the preview schema;
  revision `0002` upgrades it to tenant-safe authoritative state and adds Deployment.
- Migration owner, application, relay, and read-only audit roles are separate. Application roles
  cannot create Tenant Authority records or bypass RLS. Tenant provisioning requires the migration
  authority and an explicit administrative command.
- API and Worker each create one process-scoped Engine/Store and dispose it during graceful
  shutdown. In-memory stores remain test/offline-development adapters only.

## Consequences

- A production process cannot start a configured Capability Pack unless its bootstrap Tenant was
  provisioned first.
- P0-04 Application use cases can now own transactions without depending on process-local state.
- `0002` is not safely downgradeable in place because the preview schema cannot represent new
  authoritative facts. Operational rollback restores the mandatory pre-upgrade backup.
- RLS, role grants, composite foreign keys, optimistic conflicts, Stable uniqueness, multi-Store
  visibility, and transaction rollback require real PostgreSQL component tests in CI.

## Verification

- CI starts PostgreSQL 17, installs authority roles, runs both Alembic revisions, and executes
  `packages/adapters/tests/test_postgres_authority.py`.
- Component tests use two independent Engine/Store instances to verify shared Capability,
  Approval, Kill Switch, and Release state.
- Negative tests cover stale optimistic updates, cross-tenant foreign keys, hostile cross-tenant
  reads, forbidden Tenant creation, duplicate Active Stable pointers, incomplete persisted
  Evidence, Approval/Action and Outcome/Evidence binding tampering, and Audit/Outbox rollback.
