# ADR 0026: Persisted Evaluation Evidence Gates Candidate Promotion

- Status: Accepted
- Date: 2026-08-16

## Context

Even with fixed Subjects, ordered Graders, and statistical confidence, the Candidate lifecycle still
accepted a caller-supplied evaluation outcome: both the API evaluate endpoint and the Worker activity
derived a pass decision from arguments or a single Trial's status and transitioned the Candidate to
Awaiting Approval. Nothing persisted the link between a Candidate and the Trials that judged it, so
an approval could not be audited against complete evaluation evidence — violating the P1-04
acceptance rule that a Candidate without complete evaluation evidence must not enter Awaiting
Approval.

## Decision

1. `Trial` carries an optional `candidate_id`; Trials persisted without one (for example baseline
   probes) simply do not count toward any Candidate's evidence.
2. A new immutable `CandidateEvaluation` record persists, for every completion attempt: the gate
   decision (`met` / `not_met` / `insufficient_sample`), the referenced Trial ids, the full
   confidence assessment payload (counts, bounds, policy, rationale), and the grading principal.
   The `candidate_evaluations` table is tenant-scoped, RLS-enforced, append-only, and audited via
   the `candidate.evaluated` audit event (migration `0011`, one-way).
3. `CandidateLifecycleService.complete_evaluation` is the only path from Evaluating onward. It loads
   persisted Trials for the Candidate, rejects Trials that executed a different subject or used a
   different Suite than the Candidate's fixed references, runs the `TrialConfidenceGate`, persists
   the record, and only then transitions: `met` → Awaiting Approval, `not_met` → Rejected,
   `insufficient_sample` → no transition and an error. Caller-supplied pass/score decisions are no
   longer accepted anywhere; the `EvaluationDecision` input type is removed.
4. For Candidate evaluation the Candidate version itself is the Subject version: linked Trials must
   record `subject_version_id == candidate_id`, which the use case verifies against persisted rows.
5. Approval decisions must carry a rationale; it is persisted on the Candidate
   (`approval_reason`) alongside the independent approver identity. Release results were already
   persisted as `Release` records with audit; the evaluation record now completes the chain
   Candidate → CandidateEvaluation → Trials → Grader Results → subject Evidence refs.
6. The confidence policy is governed configuration (API environment variables, Worker dependency
   injection), never request input; graders cannot weaken thresholds, confidence levels, or sample
   minimums through the API.

## Consequences

- The evidence for a promotion decision is now queryable: every Awaiting-Approval Candidate has a
  persisted record pointing at the complete Trial set and the statistical claim it relied on.
- API evaluate requests no longer accept a body, and decision requests require a reason; the frozen
  OpenAPI contract is regenerated.
- Insufficient samples keep the Candidate in Evaluating instead of rejecting it, so orchestration
  may run more repeated Trials; the Worker converts this into a non-retryable activity failure.
- Real Subject Runtimes must persist Trials with `candidate_id` set for the gate to see them; until
  they are wired, evaluation fails closed with an insufficient-sample error. Running repeated Trials
  end to end over PostgreSQL/Temporal remains the next increment.
