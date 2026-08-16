# ADR 0023: Independent Grader pipeline and protected Evaluation Suites

- Status: Accepted
- Date: 2026-08-14

## Context

Fixed Subject execution prevents synthetic Trials, but it does not by itself prevent self-grading,
out-of-order grading, or Candidate overfitting to hidden and production-replay Cases. A plain mapping
of Graders also cannot express which authority produced an Outcome, Trajectory, LLM, or Human result.

## Decision

1. Grader stages execute only in this order: Deterministic, Outcome, Trajectory, LLM, Human.
2. Every stage binds an immutable kind, Grader identity, version and separately injected backend.
3. A non-Pass result stops lower-priority stages. Reused identities and mismatched result kinds
   invalidate evaluation rather than being silently accepted.
4. Subject Executor identity cannot also appear as a Grader identity.
5. Evaluation Cases declare `public`, `hidden`, or `production_replay` visibility. Candidate Generator
   views contain only public Case descriptors and a protected count.
6. Full protected Suites are returned only to a Principal with the Evaluation Harness role and no
   Candidate Generator role. A protected raw Suite passed directly to the Harness fails closed before
   Subject execution.
7. Gating Case failure overrides the weighted Suite pass rate.

## Consequences

- Real Outcome, Trajectory, LLM and Human implementations remain replaceable backends; provider
  objects do not enter domain records.
- The current evidence is unit-level. Catalog persistence, policy enforcement across processes,
  production replay DLP and real Grader backends are required before an integrated claim.
