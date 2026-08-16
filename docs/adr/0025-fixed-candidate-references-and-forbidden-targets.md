# ADR 0025: Fixed Candidate References and Doubly-Prohibited Improvement Targets

- Status: Accepted
- Date: 2026-08-16

## Context

A Candidate could previously be registered with only an artifact URI and a generator identity. Nothing
pinned which immutable artifact content was evaluated, or which Suite version would judge it, so the
evaluation claim could silently drift between the artifact that was tested and the artifact that was
released. Proposal and Candidate creation also lived directly in the API assembly, and the forbidden
improvement targets named by ADR-0011 existed only as documentation: the closed `ImprovementTarget`
enum was the single enforcement point, with no independent policy layer behind it.

## Decision

1. `CandidateVersion` requires an immutable `artifact_digest` (lowercase sha256 hex), a fixed
   `suite_id` and `suite_version`, next to the existing `baseline_version_id` and `generator_id`.
   The digest and Suite references are domain invariants, not caller conventions.
2. Proposal and Candidate creation move into `CandidateLifecycleService` use cases
   (`propose_improvement`, `register_candidate`). The API assembly only translates requests.
3. A Candidate must be graded against its Proposal's `validation_suite_id`; a mismatching Suite is
   rejected before the Candidate exists.
4. Forbidden improvement targets (identity, delegation, tenant isolation, policy roots, audit
   retention, Kill Switch, production code, infrastructure) are prohibited twice and independently:
   - Application layer: `require_improvement_target_allowed` rejects the raw target string before
     any enum coercion, at proposal creation and again when registering a Candidate against a
     persisted Proposal.
   - Policy layer: an optional `ImprovementTargetPolicy` port, backed by `OPAImprovementTargetPolicy`
     against `infra/policies/improvement.rego`, denies the same targets from outside the process and
     fails closed on missing decisions.
5. Migration `0010` retires legacy digest-less Candidates as terminal `rejected` records with
   placeholder references. They cannot re-enter evaluation, and the migration is one-way.

## Consequences

- Candidate creation requests gain required fields; the frozen OpenAPI contract is regenerated and
  consumer tests are updated in lockstep.
- The OPA policy mirrors the domain forbidden set; both lists must change together through review,
  which is the intended friction for widening evolvable scope.
- Without `AUTONOESIS_OPA_URL` configured, the in-process Application guard remains the single
  active layer; production assembly must configure OPA for the double prohibition to span processes.
- Binding Candidates to persisted Trials, Grader Results and Evidence — including the confidence
  assessment — remains the next P1-04 increment.
