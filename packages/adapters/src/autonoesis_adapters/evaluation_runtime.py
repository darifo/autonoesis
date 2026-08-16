"""Real in-process Subject Runtime, Grader backends, and repeated-Trial evaluator."""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from autonoesis_domain import EvaluationCase, GraderKind
from autonoesis_evaluation import (
    EvaluationHarness,
    EvaluationSuiteCatalog,
    GraderAssessment,
    GraderPipeline,
    GraderStage,
    IndependentGrader,
    SubjectExecutionResult,
    SuiteAccessContext,
    SuiteAccessRole,
)
from autonoesis_evaluation.pipeline import GraderBackend

from autonoesis_adapters.memory import InMemoryPlatformStore
from autonoesis_adapters.platform_store import PostgreSQLPlatformStore

PlatformStore = PostgreSQLPlatformStore | InMemoryPlatformStore

SubjectCallable = Callable[[dict[str, Any], int], Awaitable[dict[str, Any]]]


class InProcessSubjectRuntime:
    """Executes registered subject callables resolved by artifact reference.

    Each callable receives the Case input and the Trial seed and must compute
    its output by running the subject's actual logic. Code-level sandboxing is
    delegated to P1-06; this runtime never fabricates outputs on its own.
    """

    def __init__(self) -> None:
        self._subjects: dict[str, SubjectCallable] = {}

    def register(self, artifact_ref: str, subject: SubjectCallable) -> None:
        self._subjects[artifact_ref] = subject

    async def execute(
        self, subject_version_id: UUID, input_payload: dict[str, Any], random_seed: int
    ) -> SubjectExecutionResult:
        raise NotImplementedError("resolve by artifact_ref is owned by the evaluator")

    async def execute_artifact(
        self,
        artifact_ref: str,
        subject_version_id: UUID,
        input_payload: dict[str, Any],
        random_seed: int,
    ) -> SubjectExecutionResult:
        try:
            subject = self._subjects[artifact_ref]
        except KeyError as exc:
            raise RuntimeError(f"no subject runtime registered for {artifact_ref}") from exc
        output_payload = await subject(input_payload, random_seed)
        return SubjectExecutionResult(
            subject_version_id=subject_version_id,
            output_payload=output_payload,
            executor_id="in-process-subject-runtime@1",
            evidence_refs=(f"subject://{artifact_ref}/seed/{random_seed}",),
            environment_ref="runtime://in-process/1",
        )


class ExactMatchGraderBackend(GraderBackend):
    """Independent deterministic rule evaluation over expected outcomes."""

    async def evaluate(
        self, case: EvaluationCase, actual_output: dict[str, Any]
    ) -> GraderAssessment:
        from autonoesis_domain import GraderStatus

        mismatches = [
            key
            for key, expected in case.expected_outcome.items()
            if actual_output.get(key) != expected
        ]
        passed = not mismatches
        return GraderAssessment(
            status=GraderStatus.PASS if passed else GraderStatus.FAIL,
            score=1.0 if passed else 0.0,
            rationale=(
                f"exact match on {len(case.expected_outcome)} keys"
                if passed
                else f"value mismatch on: {', '.join(mismatches)}"
            ),
            evidence_refs=(case.case_id,),
        )


class _ArtifactBoundExecutor:
    """Binds the runtime to one artifact so the Harness sees a fixed Subject."""

    def __init__(self, runtime: InProcessSubjectRuntime, artifact_ref: str) -> None:
        self._runtime = runtime
        self._artifact_ref = artifact_ref

    async def execute(
        self, subject_version_id: UUID, input_payload: dict[str, Any], random_seed: int
    ) -> SubjectExecutionResult:
        return await self._runtime.execute_artifact(
            self._artifact_ref, subject_version_id, input_payload, random_seed
        )


class HarnessCandidateEvaluator:
    """Runs the governed Harness against a persisted Candidate as its own Subject.

    Satisfies the Worker `CandidateEvaluator` port. The Candidate version is the
    Subject version (ADR-0026), and Suites load only through the catalog's
    harness-authorized view.
    """

    def __init__(
        self,
        store: PlatformStore,
        subject_runtime: InProcessSubjectRuntime,
        *,
        harness_version: str = "2",
    ) -> None:
        self._store = store
        self._subject_runtime = subject_runtime
        self._harness_version = harness_version

    async def evaluate(self, tenant_id: UUID, candidate_id: UUID) -> Any:
        from autonoesis_domain import Trial

        candidate = await self._store.get_candidate(tenant_id, candidate_id)
        suite = await self._store.get_suite(tenant_id, candidate.suite_id, candidate.suite_version)
        harness_suite = EvaluationSuiteCatalog((suite,)).load_for_harness(
            suite.suite_id,
            suite.version,
            SuiteAccessContext(candidate_id, frozenset({SuiteAccessRole.EVALUATION_HARNESS})),
        )

        executor = _ArtifactBoundExecutor(self._subject_runtime, candidate.artifact_ref)
        pipeline = GraderPipeline(
            (
                GraderStage(
                    GraderKind.DETERMINISTIC,
                    IndependentGrader(
                        GraderKind.DETERMINISTIC,
                        "rule-engine",
                        "1",
                        ExactMatchGraderBackend(),
                    ),
                ),
            )
        )
        harness = EvaluationHarness(
            subject_executor=executor,
            grader_pipeline=pipeline,
            harness_version=self._harness_version,
        )
        trial: Trial = await harness.run_suite(
            harness_suite,
            subject_version_id=candidate_id,
            tenant_id=tenant_id,
            random_seed=secrets.randbits(31),
        )
        return trial


__all__ = [
    "ExactMatchGraderBackend",
    "HarnessCandidateEvaluator",
    "InProcessSubjectRuntime",
]
