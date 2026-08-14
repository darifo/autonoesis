# ADR 0022: Fixed-subject evaluation trials fail closed

- Status: Accepted
- Date: 2026-08-14

## Context

The initial Evaluation Harness graded an empty output without executing the requested Subject
Version. The Temporal Candidate activity then recorded a synthetic perfect score. A Candidate could
therefore reach `awaiting_approval` without evidence that its immutable artifact had run.

Evaluation infrastructure failures and uncertain grader results must also remain distinct from a
content regression. Counting either as a failed or passed case corrupts release statistics.

## Decision

1. A Harness executes every Case through an injected Subject Executor and passes the exact requested
   Subject Version ID and deterministic random seed.
2. The Executor returns the executed version, output, environment, model, tools, cost, executor
   identity and Evidence references. A version mismatch invalidates the Trial.
3. Trial JSON is the authoritative evaluation record for Case inputs, outputs, fixed conditions,
   costs, failures and independent Grader results.
4. Grader results use `pass`, `fail`, `unknown` and `invalid`. `unknown` and `invalid` invalidate the
   Trial and never contribute to a green pass rate.
5. Missing execution wiring and infrastructure exceptions fail closed. The Worker must never invent
   a score or silently promote a Candidate.

## Consequences

- Candidate evaluation remains unavailable in a production Worker until a real Subject Runtime and
  Grader pipeline are injected; this is intentional and safer than a synthetic fallback.
- `evaluation_trials.result` JSON carries the richer record. Migration `0009` invalidates legacy
  passed/failed rows with empty results and removes the fixed-condition uniqueness constraint so
  statistically repeated Trials can coexist.
- This raises Evaluation evidence within `unit-tested` only. Hidden-data isolation, repeated-Trial
  statistics, independent multi-kind Graders and Candidate/Evidence component integration are still
  required before an `integrated` claim.
