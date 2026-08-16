# ADR 0028: Pack-Declared Evaluation Subjects and Temporal-Driven Evaluation

- Status: Accepted
- Date: 2026-08-16

## Context

ADR-0027 established a real in-process runtime and a PostgreSQL component baseline, but subjects
had to be hand-registered per deployment, the production Worker still had no evaluator wired, and
no test exercised candidate evaluation through a real Temporal workflow.

## Decision

1. Capability Pack manifests may declare an optional `evaluation_subject` entry point
   (`module:function`). Validation mirrors `python_entry_point`: normalized shape and ownership by
   the pack's own module root. Unknown manifest fields remain rejected.
2. `PackSubjectRuntime` resolves `pack://<pack_id>/<version>` artifact references against the
   tenant's registered packs, imports the declared subject once per (tenant, pack, version), and
   executes it with the Case input and Trial seed. Sync and async callables are both supported.
   Missing packs, undeclared subjects, malformed references, and unimportable entry points fail
   closed as infrastructure errors (Invalid Trials).
3. The production Worker assembles `HarnessCandidateEvaluator` over `PackSubjectRuntime`; the
   confidence policy comes from `AUTONOESIS_EVALUATION_*` environment variables, never from
   request or workflow input.
4. The `CandidateLifecycleWorkflow` — already durable on Temporal — is now covered by a real-Temporal
   component test: the workflow drives the real `evaluate_candidate` activity (repeated Trials to a
   confident gate over real PostgreSQL), waits for the approval signal, and promotes; the test
   performs the independent approval through the Application use case, then verifies persisted
   Trials, the evaluation evidence record, and the final Candidate state.
5. The Field Service reference pack declares `field_service.plugin:recovery_subject`, a
   deterministic decision function mirroring its suite, making the reference pack evaluable by its
   own suite.

## Consequences

- Candidate evaluation now runs end to end under Temporal durability with pack-declared subjects;
  the maturity gap narrows to code-level sandboxing and isolation (P1-06) and outcome/LLM/human
  Grader backends.
- In-process import of pack code remains gated on tenant-registered, manifest-validated packs;
  untrusted third-party packs must not be registered before P1-06 isolation lands.
- Manifests gain one optional field; existing manifests parse unchanged.
