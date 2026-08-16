# ADR 0027: Real Subject Runtime, Persisted Suite Catalog, Repeated-Trial Execution

- Status: Accepted
- Date: 2026-08-16

## Context

ADR-0026 gates promotion on persisted Trials, but nothing executed real subjects end to end:
Suites existed only in memory, the Worker had no evaluator wired, and one Trial per attempt could
never satisfy the confidence sample.

## Decision

1. Evaluation Suites persist per tenant in `evaluation_suites` (RLS, unique
   `(tenant_id, suite_id, version)`, migration `0012`, one-way). Candidates pin a Suite reference;
   the catalog is the only source the evaluator reads.
2. `InProcessSubjectRuntime` executes registered subject callables resolved by artifact reference
   with the Case input and Trial seed; it never fabricates outputs. Code-level sandboxing stays
   with P1-06.
3. `ExactMatchGraderBackend` is a real deterministic Grader backend bound through
   `IndependentGrader`, so identity/order separation applies to real grading, not stubs.
4. `HarnessCandidateEvaluator` implements the Worker evaluator port: it loads the Candidate, loads
   its Suite through the catalog's harness-authorized view (never a generator view), treats the
   Candidate version as the Subject version, runs the governed Harness with a fresh random seed,
   and returns the Trial for linkage and persistence.
5. The Worker `evaluate_candidate` activity loops up to `2 × min_valid_trials` attempts: each
   attempt executes, persists, and links one Trial, then retries the confidence gate. Invalid
   Trials consume attempts but never count toward the sample; exhaustion fails closed with the
   recorded incompleteness rationale.
6. A PostgreSQL component test drives the whole chain — real execution, repeated Trials, gate,
   persisted evidence, promotion, tenant isolation — and runs in CI against migrated schema.

## Consequences

- Evaluation evidence now reaches a real-PostgreSQL component baseline; Temporal-driven workflow
  repetition and pack-entry-point subjects with sandboxing remain follow-ups (P1-05/P1-06).
- Subject callables run in-process today; production deployment must not register untrusted
  artifacts until P1-06 isolation lands.
