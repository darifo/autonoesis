"""Real in-process Subject Runtimes, Grader backends, and repeated-Trial evaluator."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import secrets
import sys
from collections.abc import Callable
from typing import Any, Protocol
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

SubjectCallable = Callable[[dict[str, Any], int], Any]


class SubjectRuntime(Protocol):
    async def execute_artifact(
        self,
        artifact_ref: str,
        tenant_id: UUID,
        subject_version_id: UUID,
        input_payload: dict[str, Any],
        random_seed: int,
    ) -> SubjectExecutionResult: ...


async def _invoke(subject: SubjectCallable, input_payload: dict[str, Any], random_seed: int) -> Any:
    outcome = subject(input_payload, random_seed)
    if inspect.isawaitable(outcome):
        outcome = await outcome
    return outcome


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

    async def execute_artifact(
        self,
        artifact_ref: str,
        tenant_id: UUID,
        subject_version_id: UUID,
        input_payload: dict[str, Any],
        random_seed: int,
    ) -> SubjectExecutionResult:
        try:
            subject = self._subjects[artifact_ref]
        except KeyError as exc:
            raise RuntimeError(f"no subject runtime registered for {artifact_ref}") from exc
        output_payload = await _invoke(subject, input_payload, random_seed)
        return SubjectExecutionResult(
            subject_version_id=subject_version_id,
            output_payload=output_payload,
            executor_id="in-process-subject-runtime@1",
            evidence_refs=(f"subject://{artifact_ref}/seed/{random_seed}",),
            environment_ref="runtime://in-process/1",
        )


class PackSubjectRuntime:
    """Resolves subjects from tenant-registered Capability Packs.

    Artifact references use `pack://<pack_id>/<version>`. The pack manifest must
    declare an `evaluation_subject` entry point owned by the pack module; the
    callable is imported once per (tenant, pack, version) and executed with the
    Case input and Trial seed. Packs without a declared subject fail closed.
    In-process execution only: sandbox isolation arrives with P1-06.
    """

    def __init__(self, store: PlatformStore) -> None:
        self._store = store
        self._subjects: dict[tuple[UUID, str], SubjectCallable] = {}

    async def execute_artifact(
        self,
        artifact_ref: str,
        tenant_id: UUID,
        subject_version_id: UUID,
        input_payload: dict[str, Any],
        random_seed: int,
    ) -> SubjectExecutionResult:
        subject = await self._resolve(tenant_id, artifact_ref)
        output_payload = await _invoke(subject, input_payload, random_seed)
        return SubjectExecutionResult(
            subject_version_id=subject_version_id,
            output_payload=output_payload,
            executor_id="pack-subject-runtime@1",
            evidence_refs=(f"subject://{artifact_ref}/seed/{random_seed}",),
            environment_ref="runtime://pack-in-process/1",
        )

    async def _resolve(self, tenant_id: UUID, artifact_ref: str) -> SubjectCallable:
        parts = artifact_ref.removeprefix("pack://").split("/")
        if len(parts) != 2 or not all(parts):
            raise RuntimeError(f"pack artifact reference is malformed: {artifact_ref}")
        pack_id, version = parts
        cached = self._subjects.get((tenant_id, artifact_ref))
        if cached is not None:
            return cached
        try:
            manifest = next(
                item
                for item in await self._store.list_capability_packs(tenant_id)
                if item.pack_id == pack_id and item.version == version
            )
        except StopIteration as exc:
            raise RuntimeError(f"capability pack not registered: {artifact_ref}") from exc
        if manifest.evaluation_subject is None:
            raise RuntimeError(
                f"capability pack {pack_id}@{version} declares no evaluation subject"
            )
        module_name, _, attribute = manifest.evaluation_subject.partition(":")
        try:
            module = importlib.import_module(module_name)
            subject = getattr(module, attribute)
        except (ImportError, AttributeError) as exc:
            raise RuntimeError(f"evaluation subject unavailable for {artifact_ref}: {exc}") from exc
        if not callable(subject):
            raise RuntimeError(f"evaluation subject is not callable: {manifest.evaluation_subject}")
        resolved: SubjectCallable = subject
        self._subjects[(tenant_id, artifact_ref)] = resolved
        return resolved


class SandboxedPackSubjectRuntime:
    """Execute pack subjects in a disposable subprocess with a hard timeout.

    Pack code never runs in the platform process: each execution spawns
    `python -m autonoesis_adapters.pack_subject_worker`, communicates over JSON
    on stdin/stdout only, and is killed on timeout. The child holds no tenant
    credentials, repository access, or Tool Gateway reach (ADR-0035). Failures
    — nonzero exit, timeout, malformed output — fail closed like every other
    subject runtime.
    """

    def __init__(
        self,
        store: PlatformStore,
        *,
        python_executable: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._store = store
        self._python = python_executable or sys.executable
        self._timeout = timeout_seconds

    async def execute_artifact(
        self,
        artifact_ref: str,
        tenant_id: UUID,
        subject_version_id: UUID,
        input_payload: dict[str, Any],
        random_seed: int,
    ) -> SubjectExecutionResult:
        entry_point = await self._resolve_subject_entry_point(tenant_id, artifact_ref)
        module_name, _, function_name = entry_point.partition(":")
        process = await asyncio.create_subprocess_exec(
            self._python,
            "-m",
            "autonoesis_adapters.pack_subject_worker",
            module_name,
            function_name,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        command = json.dumps({"input_payload": input_payload, "random_seed": random_seed})
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(command.encode("utf-8")), timeout=self._timeout
            )
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise RuntimeError(
                f"sandboxed subject timed out after {self._timeout}s: {artifact_ref}"
            ) from exc
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip() or "no stderr"
            raise RuntimeError(
                f"sandboxed subject failed for {artifact_ref} (exit {process.returncode}): {detail}"
            )
        try:
            output_payload = json.loads(stdout.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"sandboxed subject output is not JSON: {exc}") from exc
        if not isinstance(output_payload, dict):
            raise RuntimeError("sandboxed subject output must be a JSON object")
        return SubjectExecutionResult(
            subject_version_id=subject_version_id,
            output_payload=output_payload,
            executor_id="sandboxed-pack-subject-runtime@1",
            evidence_refs=(f"subject://{artifact_ref}/seed/{random_seed}",),
            environment_ref=f"runtime://pack-sandbox/process/1/exit/{process.returncode}",
        )

    async def _resolve_subject_entry_point(self, tenant_id: UUID, artifact_ref: str) -> str:
        parts = artifact_ref.removeprefix("pack://").split("/")
        if len(parts) != 2 or not all(parts):
            raise RuntimeError(f"pack artifact reference is malformed: {artifact_ref}")
        pack_id, version = parts
        try:
            manifest = next(
                item
                for item in await self._store.list_capability_packs(tenant_id)
                if item.pack_id == pack_id and item.version == version
            )
        except StopIteration as exc:
            raise RuntimeError(f"capability pack not registered: {artifact_ref}") from exc
        if manifest.evaluation_subject is None:
            raise RuntimeError(
                f"capability pack {pack_id}@{version} declares no evaluation subject"
            )
        return manifest.evaluation_subject


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

    def __init__(self, runtime: SubjectRuntime, tenant_id: UUID, artifact_ref: str) -> None:
        self._runtime = runtime
        self._tenant_id = tenant_id
        self._artifact_ref = artifact_ref

    async def execute(
        self, subject_version_id: UUID, input_payload: dict[str, Any], random_seed: int
    ) -> SubjectExecutionResult:
        return await self._runtime.execute_artifact(
            self._artifact_ref, self._tenant_id, subject_version_id, input_payload, random_seed
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
        subject_runtime: SubjectRuntime,
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

        executor = _ArtifactBoundExecutor(self._subject_runtime, tenant_id, candidate.artifact_ref)
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
    "PackSubjectRuntime",
    "SandboxedPackSubjectRuntime",
    "SubjectRuntime",
]
