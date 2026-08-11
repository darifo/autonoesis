# ADR-0018: Require Real-Component E2E and Archived CI Evidence

- Status: Accepted
- Date: 2026-08-11

## Context

Component tests proved individual PostgreSQL, Temporal, OPA, and MinIO boundaries, but no single
test drove a public Goal request through all of them to a verified terminal Goal. The HTTP contract
was generated at runtime but not frozen, dependency and secret scans were absent, and CI results
were not retained as hash-addressed evidence.

## Decision

1. Temporal Activities accept capability-owned `RunPlanner` and `RunExecutor` ports. Core Worker
   code remains industry-neutral; a capability executor may only advance facts through Application
   use cases.
2. The Field Service reference E2E starts at the public ASGI API and uses PostgreSQL 17, Temporal,
   OPA, PostgreSQL atomic execution reservations, KMS-backed MinIO, independent approval, trusted
   readback, and the chained audit log. A deterministic external-system simulator is used so the
   test can inject and assert side effects without claiming a production third-party integration.
3. A successful Run with all required verified Outcomes causes the Worker evaluation Activity to
   satisfy its Goal through the Application layer.
4. OpenAPI 3.1 is frozen at `docs/contracts/generated/openapi-v1.json`; source/snapshot drift fails
   CI. Every public mutation must retain its idempotency header, and no Action/Outcome write bypass
   may appear.
5. CI runs Python and Node dependency audits plus an exact-fingerprint secret scanner. Reviewed
   local/CI fixture credentials are recorded in `.secret-baseline.toml`; changed lines are new
   findings.
6. Python/component, Cockpit, contract, and security outputs are hashed into evidence manifests and
   archived as 30-day CI artifacts, including failed-run partial evidence.

## Consequences

- A Capability Pack needs a planner/executor adapter before the generic Worker can execute it.
- The `worker` service role is recognized by OPA, but delegation, exact tool version, schema, risk,
  approval, budget, credential, kill-switch, and egress checks still apply.
- The reference E2E raises the covered slice to `integrated`; it does not prove production KMS,
  real third-party reliability, multi-region operation, HA, capacity, or disaster recovery.
- The npm audit command explicitly uses the official npm registry because the configured mirror
  does not implement the audit endpoint and can otherwise emit an error with a successful exit.

## Verification

- `tests/e2e/test_reference_goal_e2e.py`
- `apps/api/tests/test_http_consumer_contract.py`
- `tests/security/test_secret_scanner.py`
- `apps/cockpit/src/maturity.test.ts`
- `.github/workflows/ci.yml` evidence artifact jobs
