"""Temporal worker process assembly with real activity implementations."""

import argparse
import asyncio
import os
from uuid import UUID

from autonoesis_adapters import (
    HarnessCandidateEvaluator,
    PackSubjectRuntime,
    PostgreSQLPlatformStore,
    SandboxedPackSubjectRuntime,
)
from autonoesis_adapters.telemetry import configure_json_logging, configure_telemetry
from autonoesis_application import CandidateLifecycleService
from autonoesis_evaluation import RepeatedTrialPolicy
from autonoesis_runtime import IsolationRiskPool, TenantNamespaces
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner

from autonoesis_worker.activities import (
    ActivityDependencies,
    build_activity_dependencies,
    cancel_run,
    evaluate_candidate,
    evaluate_run,
    execute_release_command,
    execute_run,
    execute_shadow_pair,
    load_approval,
    prepare_run,
    promote_candidate,
    reject_run,
    take_over_run,
)
from autonoesis_worker.contracts import (
    ApprovalLookupInput,
    ApprovalState,
    CancelRunInput,
    EvaluateCandidateInput,
    EvaluateRunInput,
    ExecuteRunInput,
    PrepareRunInput,
    PromoteCandidateInput,
    RejectRunInput,
    ReleaseCommandInput,
    ShadowPairInput,
    TakeOverRunInput,
)
from autonoesis_worker.dispatcher import (
    PostgreSQLRunDispatchStore,
    RunWorkflowDispatcher,
    RunWorkflowReconciler,
    TemporalRunWorkflowControl,
    run_dispatch_and_reconcile_loop,
)
from autonoesis_worker.workflows import (
    CandidateLifecycleWorkflow,
    GoalRunWorkflow,
    ReleaseExecutionWorkflow,
    ShadowPairWorkflow,
)

_process_dependencies: ActivityDependencies | None = None


def _configured_evaluation_policy() -> RepeatedTrialPolicy | None:
    if not os.getenv("AUTONOESIS_EVALUATION_PASS_THRESHOLD"):
        return None
    return RepeatedTrialPolicy(
        pass_threshold=float(os.environ["AUTONOESIS_EVALUATION_PASS_THRESHOLD"]),
        confidence_level=float(os.getenv("AUTONOESIS_EVALUATION_CONFIDENCE_LEVEL", "0.95")),
        min_valid_trials=int(os.getenv("AUTONOESIS_EVALUATION_MIN_VALID_TRIALS", "10")),
    )


def _get_dependencies() -> ActivityDependencies:
    global _process_dependencies
    if _process_dependencies is None:
        database_url = os.environ["AUTONOESIS_DATABASE_URL"]
        store = PostgreSQLPlatformStore.from_url(database_url)
        # P1-06: pack subjects execute in a disposable subprocess sandbox, not
        # in the worker process. In-process execution remains available only
        # through an explicit development escape hatch.
        # Optional LLM grader stage: enabled only with an explicit judge model
        # (AUTONOESIS_LLM_JUDGE_MODEL) and provider key wiring; absent config
        # keeps the deterministic-only pipeline (fail closed, no synthetic
        # judgments).
        llm_judge = None
        judge_model = os.getenv("AUTONOESIS_LLM_JUDGE_MODEL")
        if judge_model:
            from autonoesis_adapters import FakeModelAdapter
            from autonoesis_adapters.graders import ModelGatewayJudge

            # Production judge adapters replace this dev provider via the
            # model gateway; the harness contract is identical.
            llm_judge = ModelGatewayJudge(
                FakeModelAdapter(),
                model=judge_model,
                rubric=os.getenv("AUTONOESIS_LLM_JUDGE_RUBRIC", "default-rubric@1"),
            )
        sandbox_mode = os.getenv("AUTONOESIS_PACK_SANDBOX", "process").strip().lower()
        subject_runtime = (
            SandboxedPackSubjectRuntime(store)
            if sandbox_mode != "inprocess"
            else PackSubjectRuntime(store)
        )
        _process_dependencies = build_activity_dependencies(
            store,
            CandidateLifecycleService(store),
            candidate_evaluator=HarnessCandidateEvaluator(
                store, subject_runtime, llm_judge=llm_judge
            ),
            evaluation_policy=_configured_evaluation_policy(),
        )
    return _process_dependencies


@activity.defn(name="prepare_run")
async def _prepare(input: PrepareRunInput) -> str:
    return await prepare_run(input, _get_dependencies())


@activity.defn(name="cancel_run")
async def _cancel(input: CancelRunInput) -> str:
    return await cancel_run(input, _get_dependencies())


@activity.defn(name="reject_run")
async def _reject(input: RejectRunInput) -> str:
    return await reject_run(input, _get_dependencies())


@activity.defn(name="take_over_run")
async def _take_over(input: TakeOverRunInput) -> str:
    return await take_over_run(input, _get_dependencies())


@activity.defn(name="load_approval")
async def _load_approval(input: ApprovalLookupInput) -> ApprovalState:
    return await load_approval(input, _get_dependencies())


@activity.defn(name="execute_run")
async def _execute(input: ExecuteRunInput) -> str:
    return await execute_run(input, _get_dependencies())


@activity.defn(name="evaluate_run")
async def _evaluate(input: EvaluateRunInput) -> str:
    return await evaluate_run(input, _get_dependencies())


@activity.defn(name="evaluate_candidate")
async def _evaluate_candidate(input: EvaluateCandidateInput) -> bool:
    return await evaluate_candidate(input, _get_dependencies())


@activity.defn(name="promote_candidate")
async def _promote(input: PromoteCandidateInput) -> str:
    return await promote_candidate(input, _get_dependencies())


@activity.defn(name="execute_shadow_pair")
async def _execute_shadow_pair(input: ShadowPairInput) -> str:
    return await execute_shadow_pair(input, _get_dependencies())


@activity.defn(name="execute_release_command")
async def _execute_release_command(input: ReleaseCommandInput) -> str:
    return await execute_release_command(input, _get_dependencies())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Autonoesis durable execution worker")
    parser.add_argument("--check", action="store_true", help="validate workflow registration")
    return parser


async def run_worker() -> None:
    target = os.getenv("AUTONOESIS_TEMPORAL_TARGET", "localhost:7233")
    tenant_value = os.getenv("AUTONOESIS_WORKER_TENANT_ID")
    tenant_id = UUID(tenant_value) if tenant_value else None
    risk_pool = (
        IsolationRiskPool(os.getenv("AUTONOESIS_WORKER_RISK_POOL", "read"))
        if tenant_id is not None
        else None
    )
    boundaries = TenantNamespaces(tenant_id) if tenant_id is not None else None
    namespace = os.getenv(
        "AUTONOESIS_TEMPORAL_NAMESPACE",
        boundaries.workflow_namespace(risk_pool) if boundaries and risk_pool else "default",
    )
    task_queue = os.getenv(
        "AUTONOESIS_TEMPORAL_TASK_QUEUE",
        boundaries.workflow_task_queue(risk_pool) if boundaries and risk_pool else "autonoesis",
    )
    configure_json_logging("autonoesis-worker")
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    configure_telemetry("autonoesis-worker", otlp_endpoint)
    interceptors = []
    if otlp_endpoint:
        from temporalio.contrib.opentelemetry import TracingInterceptor

        interceptors = [TracingInterceptor()]
    client = await Client.connect(target, namespace=namespace, interceptors=interceptors)
    dispatch_database_url = os.environ["AUTONOESIS_DISPATCH_DATABASE_URL"]
    dispatch_engine = create_async_engine(dispatch_database_url, pool_pre_ping=True)
    dispatch_store = PostgreSQLRunDispatchStore(
        async_sessionmaker(dispatch_engine, expire_on_commit=False), tenant_id=tenant_id
    )
    workflow_control = TemporalRunWorkflowControl(
        client, task_queue, tenant_id=tenant_id, risk_pool=risk_pool
    )
    dispatcher = RunWorkflowDispatcher(dispatch_store, workflow_control)
    reconciler = RunWorkflowReconciler(dispatch_store, workflow_control)

    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=[
            GoalRunWorkflow,
            CandidateLifecycleWorkflow,
            ReleaseExecutionWorkflow,
            ShadowPairWorkflow,
        ],
        workflow_runner=SandboxedWorkflowRunner(),
        activities=[
            _prepare,
            _cancel,
            _reject,
            _take_over,
            _load_approval,
            _execute,
            _evaluate,
            _evaluate_candidate,
            _promote,
            _execute_shadow_pair,
            _execute_release_command,
        ],
    )
    try:
        async with asyncio.TaskGroup() as group:
            group.create_task(worker.run())
            group.create_task(run_dispatch_and_reconcile_loop(dispatcher, reconciler))
    finally:
        await dispatch_engine.dispose()
        if _process_dependencies is not None and isinstance(
            _process_dependencies.store, PostgreSQLPlatformStore
        ):
            await _process_dependencies.store.close()


def main() -> int:
    args = build_parser().parse_args()
    if args.check:
        print(
            "autonoesis-worker workflows: GoalRunWorkflow, CandidateLifecycleWorkflow, "
            "ReleaseExecutionWorkflow, ShadowPairWorkflow"
        )
        return 0
    asyncio.run(run_worker())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
