"""Recoverable Run-request Outbox dispatcher and DB/Temporal reconciler."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from autonoesis_adapters.persistence_schema import goals, outbox, runs
from autonoesis_runtime import IsolationRiskPool, TenantNamespaces
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.service import RPCError, RPCStatusCode

from autonoesis_worker.contracts import GoalRunInput
from autonoesis_worker.workflows import GoalRunWorkflow


def workflow_id_for_run(tenant_id: str, run_id: str) -> str:
    return TenantNamespaces(UUID(tenant_id)).workflow_id(UUID(run_id))


@dataclass(frozen=True, slots=True)
class RunDispatchRequest:
    event_id: str
    command: GoalRunInput


@dataclass(frozen=True, slots=True)
class ReconciliationRun:
    command: GoalRunInput
    database_status: str


@dataclass(frozen=True, slots=True)
class WorkflowObservation:
    exists: bool
    running: bool
    status: str


@dataclass(frozen=True, slots=True)
class ReconciliationFinding:
    run_id: str
    kind: str
    recovered: bool
    detail: str


class RunDispatchStore(Protocol):
    async def list_pending(self, limit: int) -> tuple[RunDispatchRequest, ...]: ...

    async def mark_dispatched(self, event_id: str) -> None: ...

    async def list_reconciliation_runs(self, limit: int) -> tuple[ReconciliationRun, ...]: ...


class RunWorkflowControl(Protocol):
    async def start(self, command: GoalRunInput) -> str: ...

    async def observe(self, workflow_id: str) -> WorkflowObservation: ...


class PostgreSQLRunDispatchStore:
    """Read cross-tenant Run requests with a dedicated BYPASSRLS relay role."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        dispatch_role: str = "autonoesis_relay",
        tenant_id: UUID | None = None,
    ) -> None:
        if re.fullmatch(r"[a-z_][a-z0-9_]*", dispatch_role) is None:
            raise ValueError("dispatch PostgreSQL role is not a safe identifier")
        self._sessions = sessions
        self._dispatch_role = dispatch_role
        self._tenant_id = tenant_id

    async def list_pending(self, limit: int = 100) -> tuple[RunDispatchRequest, ...]:
        async with self._sessions.begin() as session:
            await self._scope(session)
            query = select(outbox.c.id, outbox.c.tenant_id, outbox.c.payload).where(
                outbox.c.schema == "autonoesis.run.requested.v1",
                outbox.c.published_at.is_(None),
            )
            if self._tenant_id is not None:
                query = query.where(outbox.c.tenant_id == str(self._tenant_id))
            rows = (
                (await session.execute(query.order_by(outbox.c.created_at.asc()).limit(limit)))
                .mappings()
                .all()
            )
            requests: list[RunDispatchRequest] = []
            for row in rows:
                run_id = str(row["payload"]["object_id"])
                request = await self._load_request(
                    session, str(row["id"]), str(row["tenant_id"]), run_id
                )
                if request is not None:
                    requests.append(request)
                else:
                    await session.execute(
                        update(outbox)
                        .where(outbox.c.id == str(row["id"]))
                        .values(published_at=datetime.now(UTC))
                    )
            return tuple(requests)

    async def mark_dispatched(self, event_id: str) -> None:
        async with self._sessions.begin() as session:
            await self._scope(session)
            await session.execute(
                update(outbox)
                .where(outbox.c.id == event_id, outbox.c.published_at.is_(None))
                .values(published_at=datetime.now(UTC))
            )

    async def list_reconciliation_runs(self, limit: int = 1000) -> tuple[ReconciliationRun, ...]:
        async with self._sessions() as session:
            await self._scope(session)
            query = select(
                runs.c.id,
                runs.c.tenant_id,
                runs.c.goal_id,
                runs.c.status,
                goals.c.contract,
            ).join(
                goals,
                (goals.c.tenant_id == runs.c.tenant_id) & (goals.c.id == runs.c.goal_id),
            )
            if self._tenant_id is not None:
                query = query.where(runs.c.tenant_id == str(self._tenant_id))
            rows = (await session.execute(query.limit(limit))).mappings().all()
        return tuple(
            ReconciliationRun(
                self._command_from_row(
                    str(row["tenant_id"]),
                    str(row["goal_id"]),
                    str(row["id"]),
                    row["contract"],
                ),
                str(row["status"]),
            )
            for row in rows
        )

    async def _load_request(
        self,
        session: AsyncSession,
        event_id: str,
        tenant_id: str,
        run_id: str,
    ) -> RunDispatchRequest | None:
        row = (
            (
                await session.execute(
                    select(runs.c.goal_id, runs.c.status, goals.c.contract)
                    .join(
                        goals,
                        (goals.c.tenant_id == runs.c.tenant_id) & (goals.c.id == runs.c.goal_id),
                    )
                    .where(runs.c.tenant_id == tenant_id, runs.c.id == run_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None or row["status"] in {"succeeded", "failed", "cancelled"}:
            return None
        return RunDispatchRequest(
            event_id,
            self._command_from_row(tenant_id, str(row["goal_id"]), run_id, row["contract"]),
        )

    async def _scope(self, session: AsyncSession) -> None:
        if self._tenant_id is None:
            # The legacy shared dispatcher remains available for migrations. Production
            # workers configure tenant_id and use RLS instead of this relay identity.
            await session.execute(text(f'SET LOCAL ROLE "{self._dispatch_role}"'))
        else:
            await session.execute(
                select(func.set_config("app.tenant_id", str(self._tenant_id), True))
            )

    @staticmethod
    def _command_from_row(
        tenant_id: str, goal_id: str, run_id: str, contract: dict[str, object]
    ) -> GoalRunInput:
        deadline = datetime.fromisoformat(str(contract["deadline"]))
        risk_tier = str(contract.get("risk_tier", "low"))
        return GoalRunInput(
            tenant_id,
            goal_id,
            run_id,
            deadline.timestamp(),
            requires_approval=risk_tier in {"high", "critical"},
            risk_tier=risk_tier,
        )


class TemporalRunWorkflowControl:
    def __init__(
        self,
        client: Client,
        task_queue: str,
        *,
        tenant_id: UUID | None = None,
        risk_pool: IsolationRiskPool | None = None,
    ) -> None:
        self._client = client
        self._task_queue = task_queue
        self._tenant_id = tenant_id
        self._risk_pool = risk_pool

    async def start(self, command: GoalRunInput) -> str:
        if self._tenant_id is not None and command.tenant_id != str(self._tenant_id):
            raise PermissionError("workflow worker pool is bound to another tenant")
        requested_pool = IsolationRiskPool.from_risk_tier(command.risk_tier)
        if self._risk_pool is not None and requested_pool is not self._risk_pool:
            raise PermissionError("workflow worker pool is bound to another risk tier")
        workflow_id = workflow_id_for_run(command.tenant_id, command.run_id)
        await self._client.start_workflow(
            GoalRunWorkflow.run,
            command,
            id=workflow_id,
            task_queue=self._task_queue,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        )
        return workflow_id

    async def observe(self, workflow_id: str) -> WorkflowObservation:
        try:
            description = await self._client.get_workflow_handle(workflow_id).describe()
        except RPCError as exc:
            if exc.status is RPCStatusCode.NOT_FOUND:
                return WorkflowObservation(False, False, "not_found")
            raise
        status = description.status
        if status is None:
            return WorkflowObservation(True, False, "unspecified")
        return WorkflowObservation(
            True,
            status is WorkflowExecutionStatus.RUNNING,
            status.name.lower(),
        )


class RunWorkflowDispatcher:
    def __init__(self, store: RunDispatchStore, workflows: RunWorkflowControl) -> None:
        self._store = store
        self._workflows = workflows

    async def poll_once(self, limit: int = 100) -> int:
        dispatched = 0
        for request in await self._store.list_pending(limit):
            try:
                await self._workflows.start(request.command)
            except Exception:
                # The event remains unpublished and the next poll recovers it.
                continue
            await self._store.mark_dispatched(request.event_id)
            dispatched += 1
        return dispatched


class RunWorkflowReconciler:
    def __init__(self, store: RunDispatchStore, workflows: RunWorkflowControl) -> None:
        self._store = store
        self._workflows = workflows

    async def reconcile_once(self, limit: int = 1000) -> tuple[ReconciliationFinding, ...]:
        findings: list[ReconciliationFinding] = []
        active_statuses = {"pending", "running", "awaiting_evidence"}
        for item in await self._store.list_reconciliation_runs(limit):
            workflow_id = workflow_id_for_run(item.command.tenant_id, item.command.run_id)
            observed = await self._workflows.observe(workflow_id)
            if item.database_status not in active_statuses:
                if observed.exists and observed.running:
                    findings.append(
                        ReconciliationFinding(
                            item.command.run_id,
                            "running_workflow_with_terminal_or_manual_run",
                            False,
                            f"Temporal={observed.status}; DB={item.database_status}",
                        )
                    )
                continue
            if not observed.exists:
                try:
                    await self._workflows.start(item.command)
                except Exception as exc:
                    findings.append(
                        ReconciliationFinding(
                            item.command.run_id,
                            "missing_workflow",
                            False,
                            type(exc).__name__,
                        )
                    )
                else:
                    findings.append(
                        ReconciliationFinding(
                            item.command.run_id,
                            "missing_workflow",
                            True,
                            "fixed workflow ID started",
                        )
                    )
            elif not observed.running:
                findings.append(
                    ReconciliationFinding(
                        item.command.run_id,
                        "closed_workflow_with_active_run",
                        False,
                        f"Temporal={observed.status}; DB={item.database_status}",
                    )
                )
        return tuple(findings)


async def run_dispatch_and_reconcile_loop(
    dispatcher: RunWorkflowDispatcher,
    reconciler: RunWorkflowReconciler,
    *,
    poll_seconds: float = 1.0,
    reconcile_every: int = 30,
) -> None:
    iteration = 0
    while True:
        await dispatcher.poll_once()
        iteration += 1
        if iteration % reconcile_every == 0:
            await reconciler.reconcile_once()
        await asyncio.sleep(poll_seconds)
