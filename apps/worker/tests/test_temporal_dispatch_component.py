"""PostgreSQL Outbox → real Temporal dispatch and reconciliation component test."""

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from autonoesis_adapters import PostgreSQLPlatformStore
from autonoesis_application import AuditEvent
from autonoesis_domain import (
    BudgetAmount,
    GoalContract,
    JsonObject,
    RiskTier,
    Run,
    SubjectRef,
    SuccessCriterion,
)
from autonoesis_worker.contracts import (
    CancelRunInput,
    EvaluateRunInput,
    ExecuteRunInput,
    PrepareRunInput,
    RejectRunInput,
    TakeOverRunInput,
)
from autonoesis_worker.dispatcher import (
    PostgreSQLRunDispatchStore,
    RunWorkflowDispatcher,
    RunWorkflowReconciler,
    TemporalRunWorkflowControl,
    WorkflowObservation,
    workflow_id_for_run,
)
from autonoesis_worker.workflows import GoalRunWorkflow
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner

pytestmark = pytest.mark.skipif(
    not all(
        os.getenv(name)
        for name in (
            "AUTONOESIS_TEST_DATABASE_URL",
            "AUTONOESIS_TEST_ADMIN_DATABASE_URL",
            "AUTONOESIS_TEST_DISPATCH_DATABASE_URL",
            "AUTONOESIS_TEST_TEMPORAL_TARGET",
        )
    ),
    reason="requires explicitly configured PostgreSQL, dispatch role, and Temporal",
)


@activity.defn(name="prepare_run")
async def dispatch_prepare(input: PrepareRunInput) -> str:
    return "planned"


@activity.defn(name="execute_run")
async def dispatch_execute(input: ExecuteRunInput) -> str:
    return "dispatched"


@activity.defn(name="evaluate_run")
async def dispatch_evaluate(input: EvaluateRunInput) -> str:
    return "succeeded"


@activity.defn(name="cancel_run")
async def dispatch_cancel(input: CancelRunInput) -> str:
    return "cancelled"


@activity.defn(name="reject_run")
async def dispatch_reject(input: RejectRunInput) -> str:
    return "rejected"


@activity.defn(name="take_over_run")
async def dispatch_takeover(input: TakeOverRunInput) -> str:
    return "taken_over"


class FailFirstStart:
    def __init__(self, delegate: TemporalRunWorkflowControl) -> None:
        self._delegate = delegate
        self._failed = False

    async def start(self, command: object) -> str:
        if not self._failed:
            self._failed = True
            raise ConnectionError("injected Temporal start failure")
        from autonoesis_worker.contracts import GoalRunInput

        assert isinstance(command, GoalRunInput)
        return await self._delegate.start(command)

    async def observe(self, workflow_id: str) -> WorkflowObservation:
        return await self._delegate.observe(workflow_id)


async def _provision_tenant(tenant_id: UUID) -> None:
    engine = create_async_engine(os.environ["AUTONOESIS_TEST_ADMIN_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO tenants (id, name, created_at) "
                    "VALUES (:id, :name, CURRENT_TIMESTAMP) ON CONFLICT (id) DO NOTHING"
                ),
                {"id": str(tenant_id), "name": f"dispatch-{tenant_id}"},
            )
    finally:
        await engine.dispose()


def _audit(goal: GoalContract, event_type: str, object_id: UUID) -> AuditEvent:
    return AuditEvent(
        goal.tenant_id,
        goal.owner_id,
        goal.owner_id,
        event_type,
        "run" if event_type == "run.requested" else "goal",
        str(object_id),
        uuid4(),
        {"version": 1},
    )


@pytest.mark.asyncio
async def test_dispatch_recovers_failed_start_and_reconciles_closed_mismatch() -> None:
    tenant_id = uuid4()
    await _provision_tenant(tenant_id)
    store = PostgreSQLPlatformStore.from_url(os.environ["AUTONOESIS_TEST_DATABASE_URL"])
    dispatch_engine = create_async_engine(os.environ["AUTONOESIS_TEST_DISPATCH_DATABASE_URL"])
    client = await Client.connect(os.environ["AUTONOESIS_TEST_TEMPORAL_TARGET"])
    task_queue = f"p006-dispatch-{uuid4()}"
    try:
        goal = GoalContract(
            tenant_id=tenant_id,
            goal_type="dispatch.test",
            statement="dispatch durable Run",
            desired_outcome="Temporal starts exactly once",
            subject_refs=(SubjectRef("test", "run", "1"),),
            success_criteria=(SuccessCriterion("started", "started", "history"),),
            constraints=(),
            owner_id=uuid4(),
            risk_tier=RiskTier.LOW,
            budget_limit=BudgetAmount(100),
            deadline=datetime.now(UTC) + timedelta(minutes=5),
            input_payload=JsonObject.from_value({}),
        )
        await store.add_goal(goal, _audit(goal, "goal.created", goal.goal_id))
        run = Run(tenant_id, goal.goal_id, uuid4())
        await store.add_run(run, _audit(goal, "run.requested", run.run_id))

        dispatch_store = PostgreSQLRunDispatchStore(
            async_sessionmaker(dispatch_engine, expire_on_commit=False)
        )
        temporal = TemporalRunWorkflowControl(client, task_queue)
        dispatcher = RunWorkflowDispatcher(dispatch_store, FailFirstStart(temporal))
        async with Worker(
            client,
            task_queue=task_queue,
            workflows=[GoalRunWorkflow],
            activities=[
                dispatch_prepare,
                dispatch_execute,
                dispatch_evaluate,
                dispatch_cancel,
                dispatch_reject,
                dispatch_takeover,
            ],
            workflow_runner=SandboxedWorkflowRunner(),
        ):
            assert await dispatcher.poll_once() == 0
            assert len(await dispatch_store.list_pending()) == 1
            assert await dispatcher.poll_once() == 1
            handle = client.get_workflow_handle(workflow_id_for_run(str(run.run_id)))
            assert await handle.result() == "succeeded"

        assert await dispatch_store.list_pending() == ()
        findings = await RunWorkflowReconciler(dispatch_store, temporal).reconcile_once()
        matching = [item for item in findings if item.run_id == str(run.run_id)]
        assert matching[0].kind == "closed_workflow_with_active_run"
        assert matching[0].recovered is False
    finally:
        await store.close()
        await dispatch_engine.dispose()
