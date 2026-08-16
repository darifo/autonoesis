# ADR 0024: Repeated-Trial Statistical Confidence Gates

- Status: Accepted
- Date: 2026-08-16

## Context

A single Trial, or a fixed small number of repeated Trials, cannot demonstrate that a Subject
Version reliably passes a Suite. Stochastic Subjects and Graders make pass rate a random variable,
so "N runs, N passes" is a sample, not evidence of the underlying rate. Conversely, infrastructure
failures produce Invalid Trials that must neither inflate the green rate nor silently shrink the
required sample. The roadmap therefore requires statistical confidence rather than a fixed run
count at Evaluation Gate 1.

## Decision

1. Repeated-Trial acceptance is decided by a `TrialConfidenceGate` over a `RepeatedTrialPolicy`
   that names the target pass threshold, the confidence level, and the minimum valid sample.
2. The policy threshold must be strictly between zero and one. A threshold of one is rejected
   because the Wilson lower bound stays below one for every finite sample: perfection cannot be
   demonstrated statistically, only a target rate.
3. The gate computes the two-sided Wilson score interval over valid (Passed/Failed) Trials and
   accepts only when the lower bound at the configured confidence level is at or above the
   threshold. For an all-pass sample the lower bound reduces to n / (n + z²), which makes the
   required run count for a target explicit and auditable.
4. Invalid Trials are excluded from both the pass count and the sample size. They are reported
   in the assessment as infrastructure evidence and can never close a sample shortfall, so the
   gate fails closed during outages instead of borrowing infrastructure failures as either green
   or red Subject evidence.
5. The gate only assesses terminal Trials that are homogeneous in tenant, Suite id and version,
   Subject Version, and Harness Version. Duplicate Trial ids, in-flight Trials, and mixed-subject
   samples are rejected rather than averaged into one estimate.
6. Every decision is recorded as a `TrialConfidenceAssessment` carrying the policy, counts,
   point estimate, interval bounds, and rationale so downstream Candidate gates and Evidence
   chains can cite the exact statistical claim.

## Consequences

- Confidence is computed with the standard library (`statistics.NormalDist`); no numerical
  dependency enters the domain-adjacent evaluation package.
- The gate is deliberately conservative: small samples return `insufficient_sample`, and mixed
  results must accumulate enough valid Trials before the lower bound can cross the threshold.
- The current evidence is unit-level. Binding Candidate promotion to a persisted
  `TrialConfidenceAssessment`, real Subject runtimes producing repeated Trials, and
  Application-layer closure remain follow-up work inside P1-04.
