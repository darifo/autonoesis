# ADR 0030: Shadow Deployments Cannot Produce External Side Effects

- Status: Accepted
- Date: 2026-08-16

## Context

P1-05 requires that a Shadow Candidate produces no external side effects. Shadow runs are silent
mirrors with no user impact, but nothing in the execution path knew which Runs were shadowed, so a
shadowed Candidate could still reach the governed tool gateway and perform writes.

## Decision

1. `Run` carries an optional `deployment_id` identifying the deployment that drives it; it is
   persisted inside the run's JSON definition (no schema migration) and round-tripped losslessly.
2. `ShadowWriteGuard` is a narrow execution-time port with one method, `assert_writable(tenant_id,
   run_id)`. `GoalExecutionApplication` accepts an optional guard and invokes it before the governed
   gateway executes any L2+ write action (reversible write, high-impact write, or privileged).
3. `SqlShadowWriteGuard` resolves the Run, loads its deployment, and refuses with `PermissionError`
   when the deployment is still in Shadow. Runs without a deployment, or bound to Canary/Stable
   deployments, are unaffected — Canary carries real traffic and may write.
4. The API and Worker assemblies inject `SqlShadowWriteGuard` into `GoalExecutionApplication`.

## Consequences

- The execution path now fails closed for shadowed writes, satisfying the "Shadow Candidate cannot
  call write tools" acceptance rule at the mechanism level.
- Shadow reads and compute (L0/L1) are permitted so shadow runs can still observe and compare
  without side effects.
- ADR-0031 adds the application-level paired Stable/Candidate orchestrator and comparison evidence.
  Production Worker traffic mirroring and the independent Release Executor remain P1-05 work.
