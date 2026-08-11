"""PostgreSQL repositories for tenant-authoritative platform aggregates."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from autonoesis_application import (
    AuditEvent,
    ConcurrencyConflict,
    EvidenceCaptureSaga,
    EvidenceCaptureStatus,
    EvidenceDeletionRecord,
    EvidenceDeletionStatus,
    RecordNotFound,
)
from autonoesis_capability import CapabilityPackManifest, GoalTypeManifest, parse_manifest
from autonoesis_domain import (
    Action,
    ActionAttempt,
    AgentVersion,
    ApprovalRequest,
    AssetStage,
    BudgetAmount,
    BudgetUnit,
    CandidateVersion,
    ContextSnapshot,
    DataClassification,
    DataPolicy,
    Deployment,
    Evidence,
    ExecutionMode,
    GoalContract,
    GoalStatus,
    ImprovementProposal,
    JsonObject,
    LoopPolicy,
    MemoryRecord,
    Outcome,
    Plan,
    Release,
    RiskTier,
    Run,
    SubjectRef,
    SuccessCriterion,
    Task,
    Trial,
)
from autonoesis_runtime import TenantNamespaces, TenantTelemetryRecord
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from autonoesis_adapters.persistence_codec import (
    action_attempt_from_row,
    action_attempt_payload,
    action_from_row,
    action_payload,
    approval_from_row,
    approval_payload,
    candidate_from_row,
    candidate_payload,
    context_snapshot_from_row,
    context_snapshot_payload,
    deployment_from_row,
    deployment_payload,
    evidence_from_row,
    evidence_payload,
    outcome_from_row,
    outcome_payload,
    plan_from_rows,
    proposal_from_row,
    proposal_payload,
    release_from_row,
    release_payload,
    run_from_row,
    run_payload,
    task_payload,
    transition_payload,
    transitions_from,
    trial_from_row,
    trial_payload,
)
from autonoesis_adapters.persistence_schema import (
    action_attempts,
    actions,
    agent_versions,
    approvals,
    audit_events,
    budget_ledger,
    budgets,
    candidates,
    capability_packs,
    context_snapshots,
    deployments,
    evaluation_trials,
    evidence,
    evidence_capture_sagas,
    evidence_deletions,
    goals,
    idempotency_records,
    improvement_proposals,
    memory_records,
    outcomes,
    plans,
    policy_versions,
    releases,
    runs,
    skill_versions,
    tasks,
    telemetry_records,
    tenant_resource_namespaces,
    tool_versions,
)
from autonoesis_adapters.persistence_schema import inbox as inbox
from autonoesis_adapters.persistence_schema import kill_switches as kill_switches
from autonoesis_adapters.persistence_schema import metadata as metadata
from autonoesis_adapters.persistence_schema import outbox as outbox


class _ExistingSessionContext:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *_: object) -> None:
        return None


class _TransactionAwareSessions:
    """Reuse the Application-owned session without changing aggregate methods."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        current: ContextVar[AsyncSession | None],
    ) -> None:
        self._factory = factory
        self._current = current

    def __call__(self) -> Any:
        session = self._current.get()
        return _ExistingSessionContext(session) if session is not None else self._factory()

    def begin(self) -> Any:
        session = self._current.get()
        return _ExistingSessionContext(session) if session is not None else self._factory.begin()


class SqlAlchemyPlatformRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = sessions
        self._current_session: ContextVar[AsyncSession | None] = ContextVar(
            f"autonoesis_repository_session_{id(self)}", default=None
        )
        self._sessions = _TransactionAwareSessions(sessions, self._current_session)
        bind = sessions.kw.get("bind")
        self._uses_postgresql = bind is not None and bind.dialect.name == "postgresql"

    @property
    def sessions(self) -> async_sessionmaker[AsyncSession]:
        return self._session_factory

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """Open the explicit transaction boundary owned by an Application use case."""

        if self._current_session.get() is not None:
            raise RuntimeError("nested Application transactions are not supported")
        async with self._session_factory.begin() as session:
            token = self._current_session.set(session)
            try:
                yield
            finally:
                self._current_session.reset(token)

    async def record_audit(self, audit: AuditEvent) -> None:
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            await self._scope_tenant(session, audit.tenant_id)
            await self._add_audit_and_outbox(session, audit, now)

    async def _scope_tenant(self, session: AsyncSession, tenant_id: UUID) -> None:
        if self._uses_postgresql:
            await session.execute(select(func.set_config("app.tenant_id", str(tenant_id), True)))

    async def add_capability_pack(self, tenant_id: UUID, manifest: CapabilityPackManifest) -> None:
        now = datetime.now(UTC)
        record_id = uuid4()
        async with self._sessions.begin() as session:
            await self._scope_tenant(session, tenant_id)
            existing = await session.scalar(
                select(capability_packs.c.id).where(
                    capability_packs.c.tenant_id == str(tenant_id),
                    capability_packs.c.pack_id == manifest.pack_id,
                    capability_packs.c.version == manifest.version,
                )
            )
            if existing is None:
                await session.execute(
                    insert(capability_packs).values(
                        id=str(record_id),
                        tenant_id=str(tenant_id),
                        pack_id=manifest.pack_id,
                        version=manifest.version,
                        manifest=self._manifest_payload(manifest),
                        enabled=True,
                        optimistic_version=1,
                        created_at=now,
                    )
                )
                await self._record_fact(
                    session,
                    tenant_id,
                    "capability_pack.installed",
                    "capability_pack",
                    record_id,
                    1,
                    now,
                )

    async def list_capability_packs(self, tenant_id: UUID) -> tuple[CapabilityPackManifest, ...]:
        async with self._sessions() as session:
            await self._scope_tenant(session, tenant_id)
            rows = (
                await session.execute(
                    select(capability_packs).where(
                        capability_packs.c.tenant_id == str(tenant_id),
                        capability_packs.c.enabled.is_(True),
                    )
                )
            ).mappings()
            return tuple(parse_manifest(dict(row)["manifest"]) for row in rows)

    async def get_goal_type(self, tenant_id: UUID, goal_type: str) -> GoalTypeManifest:
        for manifest in await self.list_capability_packs(tenant_id):
            for item in manifest.goal_types:
                if item.goal_type == goal_type:
                    return item
        raise RecordNotFound(f"goal type {goal_type} was not found")

    async def add_agent(self, name: str, version: AgentVersion) -> None:
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            await self._scope_tenant(session, version.tenant_id)
            await session.execute(
                insert(agent_versions).values(
                    id=str(version.agent_version_id),
                    tenant_id=str(version.tenant_id),
                    agent_id=str(version.agent_id),
                    name=name,
                    version=version.version,
                    stage=version.stage.value,
                    definition=self._agent_payload(version),
                    optimistic_version=1,
                    created_at=now,
                )
            )
            await self._record_fact(
                session,
                version.tenant_id,
                "agent_version.created",
                "agent_version",
                version.agent_version_id,
                1,
                now,
            )

    async def list_agents(self, tenant_id: UUID) -> tuple[tuple[str, AgentVersion], ...]:
        async with self._sessions() as session:
            await self._scope_tenant(session, tenant_id)
            rows = (
                await session.execute(
                    select(agent_versions).where(agent_versions.c.tenant_id == str(tenant_id))
                )
            ).mappings()
            return tuple((row["name"], self._agent_from_row(dict(row))) for row in rows)

    async def get_stable_agent(self, tenant_id: UUID, agent_name: str) -> AgentVersion:
        async with self._sessions() as session:
            await self._scope_tenant(session, tenant_id)
            row = (
                (
                    await session.execute(
                        select(agent_versions).where(
                            agent_versions.c.tenant_id == str(tenant_id),
                            agent_versions.c.name == agent_name,
                            agent_versions.c.stage == AssetStage.STABLE.value,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise RecordNotFound(f"stable agent {agent_name} was not found")
        return self._agent_from_row(dict(row))

    async def add_skill(
        self, tenant_id: UUID, asset_id: str, definition: dict[str, Any]
    ) -> dict[str, object]:
        return await self._add_config_asset(
            skill_versions, "skill_id", tenant_id, asset_id, definition
        )

    async def list_skills(self, tenant_id: UUID) -> tuple[dict[str, object], ...]:
        return await self._list_config_assets(skill_versions, "skill_id", tenant_id)

    async def add_tool(
        self, tenant_id: UUID, asset_id: str, definition: dict[str, Any]
    ) -> dict[str, object]:
        return await self._add_config_asset(
            tool_versions, "tool_id", tenant_id, asset_id, definition
        )

    async def list_tools(self, tenant_id: UUID) -> tuple[dict[str, object], ...]:
        return await self._list_config_assets(tool_versions, "tool_id", tenant_id)

    async def add_policy(
        self, tenant_id: UUID, asset_id: str, definition: dict[str, Any]
    ) -> dict[str, object]:
        return await self._add_config_asset(
            policy_versions, "policy_id", tenant_id, asset_id, definition
        )

    async def list_policies(self, tenant_id: UUID) -> tuple[dict[str, object], ...]:
        return await self._list_config_assets(policy_versions, "policy_id", tenant_id)

    async def add_budget(
        self, tenant_id: UUID, asset_id: str, definition: dict[str, Any]
    ) -> dict[str, object]:
        return await self._add_config_asset(budgets, "budget_id", tenant_id, asset_id, definition)

    async def list_budgets(self, tenant_id: UUID) -> tuple[dict[str, object], ...]:
        return await self._list_config_assets(budgets, "budget_id", tenant_id)

    async def add_goal(self, goal: GoalContract, audit: AuditEvent) -> None:
        async with self._sessions.begin() as session:
            await self._scope_tenant(session, goal.tenant_id)
            await session.execute(
                insert(goals).values(
                    id=str(goal.goal_id),
                    tenant_id=str(goal.tenant_id),
                    goal_type=goal.goal_type,
                    owner_id=str(goal.owner_id),
                    status=goal.status.value,
                    contract=self._goal_payload(goal),
                    optimistic_version=goal.version,
                    created_at=goal.created_at,
                )
            )
            await self._add_audit_and_outbox(session, audit, goal.created_at)

    async def get_goal(self, tenant_id: UUID, goal_id: UUID) -> GoalContract:
        async with self._sessions() as session:
            await self._scope_tenant(session, tenant_id)
            row = (
                (
                    await session.execute(
                        select(goals).where(
                            goals.c.id == str(goal_id), goals.c.tenant_id == str(tenant_id)
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise RecordNotFound(f"goal {goal_id} was not found")
        return self._goal_from_row(dict(row))

    async def list_goals(self, tenant_id: UUID) -> tuple[GoalContract, ...]:
        async with self._sessions() as session:
            await self._scope_tenant(session, tenant_id)
            rows = (
                await session.execute(select(goals).where(goals.c.tenant_id == str(tenant_id)))
            ).mappings()
            return tuple(self._goal_from_row(dict(row)) for row in rows)

    async def save_goal(self, goal: GoalContract, expected_version: int, audit: AuditEvent) -> None:
        async with self._sessions.begin() as session:
            await self._scope_tenant(session, goal.tenant_id)
            result = cast(
                CursorResult[Any],
                await session.execute(
                    update(goals)
                    .where(
                        goals.c.id == str(goal.goal_id),
                        goals.c.tenant_id == str(goal.tenant_id),
                        goals.c.optimistic_version == expected_version,
                    )
                    .values(
                        status=goal.status.value,
                        contract=self._goal_payload(goal),
                        optimistic_version=goal.version,
                        updated_at=datetime.now(UTC),
                    )
                ),
            )
            if result.rowcount != 1:
                raise ConcurrencyConflict("goal optimistic version changed")
            now = datetime.now(UTC)
            await self._add_audit_and_outbox(session, audit, now)

    async def add_run(self, run: Run, audit: AuditEvent) -> None:
        async with self._sessions.begin() as session:
            await self._scope_tenant(session, run.tenant_id)
            await session.execute(
                insert(runs).values(
                    id=str(run.run_id),
                    tenant_id=str(run.tenant_id),
                    goal_id=str(run.goal_id),
                    agent_version_id=str(run.agent_version_id),
                    status=run.status.value,
                    temporal_workflow_id=TenantNamespaces(run.tenant_id).workflow_id(run.run_id),
                    definition=run_payload(run),
                    optimistic_version=run.optimistic_version,
                    created_at=run.created_at,
                )
            )
            await self._add_audit_and_outbox(session, audit, run.created_at)

    async def get_run(self, tenant_id: UUID, run_id: UUID) -> Run:
        async with self._sessions() as session:
            await self._scope_tenant(session, tenant_id)
            row = (
                (
                    await session.execute(
                        select(runs).where(
                            runs.c.id == str(run_id), runs.c.tenant_id == str(tenant_id)
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise RecordNotFound(f"run {run_id} was not found")
        return run_from_row(dict(row))

    async def save_run(
        self, run: Run, expected_version: int, audit: AuditEvent | None = None
    ) -> None:
        async with self._sessions.begin() as session:
            await self._scope_tenant(session, run.tenant_id)
            result = cast(
                CursorResult[Any],
                await session.execute(
                    update(runs)
                    .where(
                        runs.c.id == str(run.run_id),
                        runs.c.tenant_id == str(run.tenant_id),
                        runs.c.optimistic_version == expected_version,
                    )
                    .values(
                        status=run.status.value,
                        definition=run_payload(run),
                        optimistic_version=run.optimistic_version,
                        updated_at=datetime.now(UTC),
                    )
                ),
            )
            if result.rowcount != 1:
                raise ConcurrencyConflict("run optimistic version changed")
            now = datetime.now(UTC)
            if audit is None:
                await self._record_fact(
                    session,
                    run.tenant_id,
                    "run.updated",
                    "run",
                    run.run_id,
                    run.optimistic_version,
                    now,
                )
            else:
                await self._add_audit_and_outbox(session, audit, now)

    async def list_runs(self, tenant_id: UUID, goal_id: UUID | None = None) -> tuple[Run, ...]:
        async with self._sessions() as session:
            await self._scope_tenant(session, tenant_id)
            query = select(runs).where(runs.c.tenant_id == str(tenant_id))
            if goal_id is not None:
                query = query.where(runs.c.goal_id == str(goal_id))
            rows = (await session.execute(query)).mappings()
            return tuple(run_from_row(dict(row)) for row in rows)

    async def add_context_snapshot(self, snapshot: ContextSnapshot) -> None:
        payload = context_snapshot_payload(snapshot)
        async with self._sessions.begin() as session:
            await self._scope_tenant(session, snapshot.tenant_id)
            await session.execute(
                insert(context_snapshots).values(
                    id=str(snapshot.snapshot_id),
                    tenant_id=str(snapshot.tenant_id),
                    goal_id=str(snapshot.goal_id),
                    run_id=str(snapshot.run_id),
                    payload=payload,
                    content_digest=JsonObject.from_value(payload).digest,
                    optimistic_version=1,
                    created_at=snapshot.created_at,
                )
            )
            await self._record_fact(
                session,
                snapshot.tenant_id,
                "run.context_prepared",
                "context_snapshot",
                snapshot.snapshot_id,
                1,
                snapshot.created_at,
            )

    async def get_context_snapshot(self, tenant_id: UUID, run_id: UUID) -> ContextSnapshot:
        async with self._sessions() as session:
            await self._scope_tenant(session, tenant_id)
            row = (
                (
                    await session.execute(
                        select(context_snapshots).where(
                            context_snapshots.c.tenant_id == str(tenant_id),
                            context_snapshots.c.run_id == str(run_id),
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise RecordNotFound(f"context for run {run_id} was not found")
        return context_snapshot_from_row(dict(row))

    async def add_memory(self, item: MemoryRecord) -> None:
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            await self._scope_tenant(session, item.tenant_id)
            await session.execute(
                insert(memory_records).values(
                    id=str(item.memory_id),
                    tenant_id=str(item.tenant_id),
                    scope=item.scope,
                    content=item.content,
                    provenance=list(item.provenance),
                    confidence=item.confidence,
                    expires_at=item.expires_at,
                    approved_by=str(item.approved_by),
                    optimistic_version=1,
                    created_at=now,
                )
            )
            await self._record_fact(
                session, item.tenant_id, "memory.recorded", "memory", item.memory_id, 1, now
            )

    async def list_memory(self, tenant_id: UUID) -> tuple[MemoryRecord, ...]:
        rows = await self._list_rows(memory_records, tenant_id)
        return tuple(
            MemoryRecord(
                tenant_id=UUID(row["tenant_id"]),
                scope=row["scope"],
                content=row["content"],
                provenance=tuple(row["provenance"]),
                confidence=float(row["confidence"]),
                expires_at=row["expires_at"],
                approved_by=UUID(row["approved_by"]),
                memory_id=UUID(row["id"]),
            )
            for row in rows
        )

    async def add_telemetry(self, item: TenantTelemetryRecord) -> None:
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            await self._scope_tenant(session, item.tenant_id)
            await session.execute(
                insert(telemetry_records).values(
                    id=str(uuid4()),
                    tenant_id=str(item.tenant_id),
                    signal_type=item.signal_type,
                    trace_id=item.trace_id,
                    payload=item.payload,
                    occurred_at=now,
                    optimistic_version=1,
                    created_at=now,
                )
            )

    async def list_telemetry(self, tenant_id: UUID) -> tuple[TenantTelemetryRecord, ...]:
        rows = await self._list_rows(telemetry_records, tenant_id)
        return tuple(
            TenantTelemetryRecord(
                tenant_id=UUID(row["tenant_id"]),
                signal_type=row["signal_type"],
                trace_id=row["trace_id"],
                payload=row["payload"],
            )
            for row in rows
        )

    async def register_tenant_namespace(
        self, tenant_id: UUID, resource_kind: str, logical_name: str, physical_namespace: str
    ) -> dict[str, str]:
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            await self._scope_tenant(session, tenant_id)
            existing = (
                (
                    await session.execute(
                        select(tenant_resource_namespaces).where(
                            tenant_resource_namespaces.c.tenant_id == str(tenant_id),
                            tenant_resource_namespaces.c.resource_kind == resource_kind,
                            tenant_resource_namespaces.c.logical_name == logical_name,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                if existing["physical_namespace"] != physical_namespace:
                    raise ConcurrencyConflict("tenant resource namespace is already frozen")
            else:
                await session.execute(
                    insert(tenant_resource_namespaces).values(
                        id=str(uuid4()),
                        tenant_id=str(tenant_id),
                        resource_kind=resource_kind,
                        logical_name=logical_name,
                        physical_namespace=physical_namespace,
                        optimistic_version=1,
                        created_at=now,
                    )
                )
        return {
            "tenant_id": str(tenant_id),
            "resource_kind": resource_kind,
            "logical_name": logical_name,
            "physical_namespace": physical_namespace,
        }

    async def list_tenant_namespaces(self, tenant_id: UUID) -> tuple[dict[str, str], ...]:
        return tuple(
            {
                "tenant_id": row["tenant_id"],
                "resource_kind": row["resource_kind"],
                "logical_name": row["logical_name"],
                "physical_namespace": row["physical_namespace"],
            }
            for row in await self._list_rows(tenant_resource_namespaces, tenant_id)
        )

    async def add_plan(self, plan: Plan) -> None:
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            await self._scope_tenant(session, plan.tenant_id)
            await session.execute(
                insert(plans).values(
                    id=str(plan.plan_id),
                    tenant_id=str(plan.tenant_id),
                    goal_id=str(plan.goal_id),
                    run_id=str(plan.run_id),
                    version=plan.version,
                    definition={"task_ids": [str(item.task_id) for item in plan.tasks]},
                    optimistic_version=1,
                    created_at=now,
                )
            )
            for task in plan.tasks:
                await session.execute(
                    insert(tasks).values(
                        id=str(task.task_id),
                        tenant_id=str(task.tenant_id),
                        run_id=str(task.run_id),
                        plan_id=str(plan.plan_id),
                        status=task.status.value,
                        definition=task_payload(task),
                        optimistic_version=task.optimistic_version,
                        created_at=now,
                    )
                )
            await self._record_fact(
                session, plan.tenant_id, "plan.created", "plan", plan.plan_id, plan.version, now
            )

    async def get_plan(self, tenant_id: UUID, plan_id: UUID) -> Plan:
        async with self._sessions() as session:
            await self._scope_tenant(session, tenant_id)
            plan_row = (
                (
                    await session.execute(
                        select(plans).where(
                            plans.c.id == str(plan_id), plans.c.tenant_id == str(tenant_id)
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if plan_row is None:
                raise RecordNotFound(f"plan {plan_id} was not found")
            task_rows = list(
                (
                    await session.execute(
                        select(tasks).where(
                            tasks.c.plan_id == str(plan_id),
                            tasks.c.tenant_id == str(tenant_id),
                        )
                    )
                ).mappings()
            )
        return plan_from_rows(dict(plan_row), [dict(row) for row in task_rows])

    async def get_task(self, tenant_id: UUID, task_id: UUID) -> Task:
        from autonoesis_adapters.persistence_codec import task_from_row

        return task_from_row(await self._get_row(tasks, tenant_id, task_id))

    async def list_tasks(self, tenant_id: UUID, run_id: UUID) -> tuple[Task, ...]:
        from autonoesis_adapters.persistence_codec import task_from_row

        async with self._sessions() as session:
            await self._scope_tenant(session, tenant_id)
            rows = (
                await session.execute(
                    select(tasks).where(
                        tasks.c.tenant_id == str(tenant_id), tasks.c.run_id == str(run_id)
                    )
                )
            ).mappings()
            return tuple(task_from_row(dict(row)) for row in rows)

    async def save_task(self, task: Task, expected_version: int) -> None:
        async with self._sessions.begin() as session:
            await self._scope_tenant(session, task.tenant_id)
            result = cast(
                CursorResult[Any],
                await session.execute(
                    update(tasks)
                    .where(
                        tasks.c.id == str(task.task_id),
                        tasks.c.tenant_id == str(task.tenant_id),
                        tasks.c.optimistic_version == expected_version,
                    )
                    .values(
                        status=task.status.value,
                        definition=task_payload(task),
                        optimistic_version=task.optimistic_version,
                        updated_at=datetime.now(UTC),
                    )
                ),
            )
            if result.rowcount != 1:
                raise ConcurrencyConflict("task optimistic version changed")
            await self._record_fact(
                session,
                task.tenant_id,
                "task.updated",
                "task",
                task.task_id,
                task.optimistic_version,
                datetime.now(UTC),
            )

    async def add_action(self, action: Action) -> None:
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            await self._scope_tenant(session, action.tenant_id)
            await session.execute(
                insert(actions).values(
                    id=str(action.action_id),
                    tenant_id=str(action.tenant_id),
                    run_id=str(action.run_id),
                    task_id=str(action.task_id),
                    status=action.status.value,
                    idempotency_key=action.idempotency_key,
                    action_digest=action.canonical_digest,
                    definition=action_payload(action),
                    optimistic_version=action.optimistic_version,
                    created_at=now,
                )
            )
            await self._record_fact(
                session,
                action.tenant_id,
                "action.proposed",
                "action",
                action.action_id,
                action.optimistic_version,
                now,
            )

    async def get_action(self, tenant_id: UUID, action_id: UUID) -> Action:
        row = await self._get_row(actions, tenant_id, action_id)
        return action_from_row(row)

    async def save_action(self, action: Action, expected_version: int) -> None:
        await self._save_versioned(
            actions,
            action.tenant_id,
            action.action_id,
            expected_version,
            action.optimistic_version,
            {
                "status": action.status.value,
                "action_digest": action.canonical_digest,
                "definition": action_payload(action),
            },
            "action",
        )

    async def list_actions(self, tenant_id: UUID, run_id: UUID) -> tuple[Action, ...]:
        async with self._sessions() as session:
            await self._scope_tenant(session, tenant_id)
            rows = (
                await session.execute(
                    select(actions).where(
                        actions.c.tenant_id == str(tenant_id),
                        actions.c.run_id == str(run_id),
                    )
                )
            ).mappings()
            return tuple(action_from_row(dict(row)) for row in rows)

    async def add_action_attempt(self, attempt: ActionAttempt) -> None:
        async with self._sessions.begin() as session:
            await self._scope_tenant(session, attempt.tenant_id)
            await session.execute(
                insert(action_attempts).values(
                    id=str(attempt.attempt_id),
                    tenant_id=str(attempt.tenant_id),
                    run_id=str(attempt.run_id),
                    action_id=str(attempt.action_id),
                    invocation_id=str(attempt.invocation_id),
                    status=attempt.status.value,
                    idempotency_key=attempt.idempotency_key,
                    receipt_ref=attempt.receipt_ref,
                    definition=action_attempt_payload(attempt),
                    optimistic_version=1,
                    created_at=attempt.recorded_at,
                )
            )
            await self._record_fact(
                session,
                attempt.tenant_id,
                "action.attempt_recorded",
                "action_attempt",
                attempt.attempt_id,
                1,
                attempt.recorded_at,
            )

    async def list_action_attempts(
        self, tenant_id: UUID, action_id: UUID
    ) -> tuple[ActionAttempt, ...]:
        async with self._sessions() as session:
            await self._scope_tenant(session, tenant_id)
            rows = (
                await session.execute(
                    select(action_attempts).where(
                        action_attempts.c.tenant_id == str(tenant_id),
                        action_attempts.c.action_id == str(action_id),
                    )
                )
            ).mappings()
            return tuple(action_attempt_from_row(dict(row)) for row in rows)

    async def add_approval(self, approval: ApprovalRequest) -> None:
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            await self._scope_tenant(session, approval.tenant_id)
            authoritative_action = action_from_row(
                await self._get_row_in_session(
                    session, actions, approval.tenant_id, approval.action_id
                )
            )
            if (
                authoritative_action.run_id != approval.run_id
                or authoritative_action.canonical_digest != approval.action_digest
                or authoritative_action.tool_version != approval.tool_version
                or authoritative_action.operation != approval.operation
                or authoritative_action.resource_scope != approval.resource_scope
                or authoritative_action.parameter_digest != approval.argument_digest
            ):
                raise ValueError("approval must exactly bind the authoritative persisted Action")
            await session.execute(
                insert(approvals).values(
                    id=str(approval.approval_id),
                    tenant_id=str(approval.tenant_id),
                    run_id=str(approval.run_id),
                    action_id=str(approval.action_id),
                    status=approval.status.value,
                    action_digest=approval.action_digest,
                    expires_at=approval.expires_at,
                    definition=approval_payload(approval),
                    optimistic_version=approval.optimistic_version,
                    created_at=approval.created_at,
                )
            )
            await self._record_fact(
                session,
                approval.tenant_id,
                "approval.requested",
                "approval",
                approval.approval_id,
                approval.optimistic_version,
                now,
            )

    async def get_approval(self, tenant_id: UUID, approval_id: UUID) -> ApprovalRequest:
        return approval_from_row(await self._get_row(approvals, tenant_id, approval_id))

    async def list_approvals(self, tenant_id: UUID) -> tuple[ApprovalRequest, ...]:
        return tuple(approval_from_row(row) for row in await self._list_rows(approvals, tenant_id))

    async def save_approval(self, approval: ApprovalRequest, expected_version: int) -> None:
        await self._save_versioned(
            approvals,
            approval.tenant_id,
            approval.approval_id,
            expected_version,
            approval.optimistic_version,
            {
                "status": approval.status.value,
                "definition": approval_payload(approval),
                "expires_at": approval.expires_at,
            },
            "approval",
        )

    async def add_evidence(self, item: Evidence) -> None:
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            await self._scope_tenant(session, item.tenant_id)
            await session.execute(
                insert(evidence).values(
                    id=str(item.evidence_id),
                    tenant_id=str(item.tenant_id),
                    run_id=str(item.run_id),
                    action_id=str(item.action_id),
                    source=item.source,
                    source_identity=item.source_identity,
                    capture_method=item.capture_method.value,
                    artifact_uri=item.reference,
                    content_digest=item.content_digest,
                    classification=item.classification.value,
                    valid_from=item.valid_from,
                    valid_until=item.valid_until,
                    integrity=item.integrity.value,
                    definition=evidence_payload(item),
                    optimistic_version=1,
                    created_at=item.captured_at,
                )
            )
            await self._record_fact(
                session,
                item.tenant_id,
                "evidence.captured",
                "evidence",
                item.evidence_id,
                1,
                now,
            )

    async def get_evidence(self, tenant_id: UUID, evidence_id: UUID) -> Evidence:
        return evidence_from_row(await self._get_row(evidence, tenant_id, evidence_id))

    async def list_evidence(self, tenant_id: UUID) -> tuple[Evidence, ...]:
        return tuple(evidence_from_row(row) for row in await self._list_rows(evidence, tenant_id))

    async def start_evidence_capture(self, saga: EvidenceCaptureSaga) -> None:
        """Persist the recoverable intent before the external object write."""

        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            await self._scope_tenant(session, saga.tenant_id)
            existing = (
                (
                    await session.execute(
                        select(evidence_capture_sagas).where(
                            evidence_capture_sagas.c.tenant_id == str(saga.tenant_id),
                            evidence_capture_sagas.c.evidence_id == str(saga.evidence_id),
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                if any(
                    (
                        existing["run_id"] != str(saga.run_id),
                        existing["action_id"] != str(saga.action_id),
                        existing["artifact_uri"] != saga.artifact_uri,
                        existing["expected_digest"] != saga.expected_digest,
                        existing["definition"] != saga.definition,
                    )
                ):
                    raise ConcurrencyConflict(
                        "Evidence capture id was reused with different immutable content"
                    )
                return
            await session.execute(
                insert(evidence_capture_sagas).values(
                    id=str(saga.evidence_id),
                    tenant_id=str(saga.tenant_id),
                    evidence_id=str(saga.evidence_id),
                    run_id=str(saga.run_id),
                    action_id=str(saga.action_id),
                    criterion_id=saga.criterion_id,
                    source=saga.source,
                    artifact_uri=saga.artifact_uri,
                    expected_digest=saga.expected_digest,
                    status=saga.status.value,
                    definition=saga.definition,
                    failure_reason=saga.failure_reason,
                    optimistic_version=1,
                    created_at=now,
                )
            )
            await self._record_fact(
                session,
                saga.tenant_id,
                "evidence.capture_requested",
                "evidence",
                saga.evidence_id,
                1,
                now,
            )

    async def get_evidence_capture(self, tenant_id: UUID, evidence_id: UUID) -> EvidenceCaptureSaga:
        row = await self._get_row(evidence_capture_sagas, tenant_id, evidence_id)
        return EvidenceCaptureSaga(
            UUID(row["tenant_id"]),
            UUID(row["evidence_id"]),
            UUID(row["run_id"]),
            UUID(row["action_id"]),
            row["criterion_id"],
            row["source"],
            row["artifact_uri"],
            row["expected_digest"],
            row["definition"],
            EvidenceCaptureStatus(row["status"]),
            row["failure_reason"],
        )

    async def complete_evidence_capture(self, tenant_id: UUID, evidence_id: UUID) -> None:
        async with self._sessions.begin() as session:
            await self._scope_tenant(session, tenant_id)
            result = await session.execute(
                update(evidence_capture_sagas)
                .where(
                    evidence_capture_sagas.c.tenant_id == str(tenant_id),
                    evidence_capture_sagas.c.evidence_id == str(evidence_id),
                    evidence_capture_sagas.c.status == EvidenceCaptureStatus.PENDING.value,
                )
                .values(
                    status=EvidenceCaptureStatus.COMMITTED.value,
                    optimistic_version=evidence_capture_sagas.c.optimistic_version + 1,
                    updated_at=datetime.now(UTC),
                )
            )
            if cast(CursorResult[Any], result).rowcount != 1:
                status = await session.scalar(
                    select(evidence_capture_sagas.c.status).where(
                        evidence_capture_sagas.c.tenant_id == str(tenant_id),
                        evidence_capture_sagas.c.evidence_id == str(evidence_id),
                    )
                )
                if status != EvidenceCaptureStatus.COMMITTED.value:
                    raise ConcurrencyConflict("Evidence capture Saga is not pending")

    async def record_evidence_deletion(self, record: EvidenceDeletionRecord) -> None:
        async with self._sessions.begin() as session:
            await self._scope_tenant(session, record.tenant_id)
            existing = await session.scalar(
                select(evidence_deletions.c.id).where(
                    evidence_deletions.c.tenant_id == str(record.tenant_id),
                    evidence_deletions.c.evidence_id == str(record.evidence_id),
                )
            )
            values = {
                "artifact_uri": record.artifact_uri,
                "requested_by": str(record.requested_by),
                "reason": record.reason,
                "requested_at": record.requested_at,
                "status": record.status.value,
                "deleted_at": record.deleted_at,
                "provider_version_id": record.provider_version_id,
                "proof_digest": record.proof_digest,
                "failure_reason": record.failure_reason,
                "updated_at": datetime.now(UTC),
            }
            if existing is None:
                await session.execute(
                    insert(evidence_deletions).values(
                        id=str(record.evidence_id),
                        tenant_id=str(record.tenant_id),
                        evidence_id=str(record.evidence_id),
                        optimistic_version=1,
                        created_at=record.requested_at,
                        **values,
                    )
                )
            else:
                await session.execute(
                    update(evidence_deletions)
                    .where(
                        evidence_deletions.c.tenant_id == str(record.tenant_id),
                        evidence_deletions.c.evidence_id == str(record.evidence_id),
                    )
                    .values(
                        **values,
                        optimistic_version=evidence_deletions.c.optimistic_version + 1,
                    )
                )

    async def get_evidence_deletion(
        self, tenant_id: UUID, evidence_id: UUID
    ) -> EvidenceDeletionRecord:
        row = await self._get_row(evidence_deletions, tenant_id, evidence_id)
        return EvidenceDeletionRecord(
            UUID(row["tenant_id"]),
            UUID(row["evidence_id"]),
            row["artifact_uri"],
            UUID(row["requested_by"]),
            row["reason"],
            row["requested_at"],
            EvidenceDeletionStatus(row["status"]),
            row["deleted_at"],
            row["provider_version_id"],
            row["proof_digest"],
            row["failure_reason"],
        )

    async def add_outcome(self, item: Outcome) -> None:
        now = datetime.now(UTC)
        evidence_ids = {str(value) for value in item.evidence_ids}
        async with self._sessions.begin() as session:
            await self._scope_tenant(session, item.tenant_id)
            persisted_rows = (
                await session.execute(
                    select(evidence.c.id).where(
                        evidence.c.tenant_id == str(item.tenant_id),
                        evidence.c.run_id == str(item.run_id),
                        evidence.c.id.in_(evidence_ids),
                    )
                )
            ).mappings()
            persisted_ids = {row["id"] for row in persisted_rows}
            if persisted_ids != evidence_ids:
                raise ValueError(
                    "outcome evidence must be complete, integrity-verified, and persisted"
                )
            for evidence_item in item.evidence:
                persisted = evidence_from_row(
                    await self._get_row_in_session(
                        session, evidence, item.tenant_id, evidence_item.evidence_id
                    )
                )
                if persisted != evidence_item:
                    raise ValueError(
                        "outcome evidence must exactly match the authoritative persisted record"
                    )
            await session.execute(
                insert(outcomes).values(
                    id=str(item.outcome_id),
                    tenant_id=str(item.tenant_id),
                    goal_id=str(item.goal_id),
                    run_id=str(item.run_id),
                    criterion_id=item.criterion_id,
                    verifier_version=item.verifier_version,
                    status=item.status.value,
                    result=outcome_payload(item),
                    optimistic_version=1,
                    created_at=now,
                )
            )
            await self._record_fact(
                session,
                item.tenant_id,
                "outcome.recorded",
                "outcome",
                item.outcome_id,
                1,
                now,
            )

    async def get_outcome(self, tenant_id: UUID, outcome_id: UUID) -> Outcome:
        row = await self._get_row(outcomes, tenant_id, outcome_id)
        evidence_ids = [UUID(item) for item in row["result"].get("evidence_ids", ())]
        items = tuple([await self.get_evidence(tenant_id, item) for item in evidence_ids])
        return outcome_from_row(row, items)

    async def list_outcomes(self, tenant_id: UUID, run_id: UUID) -> tuple[Outcome, ...]:
        async with self._sessions() as session:
            await self._scope_tenant(session, tenant_id)
            rows = tuple(
                dict(row)
                for row in (
                    await session.execute(
                        select(outcomes).where(
                            outcomes.c.tenant_id == str(tenant_id),
                            outcomes.c.run_id == str(run_id),
                        )
                    )
                ).mappings()
            )
        result: list[Outcome] = []
        for row in rows:
            evidence_ids = [UUID(item) for item in row["result"].get("evidence_ids", ())]
            items = tuple([await self.get_evidence(tenant_id, item) for item in evidence_ids])
            result.append(outcome_from_row(row, items))
        return tuple(result)

    async def record_budget_entry(
        self,
        tenant_id: UUID,
        run_id: UUID,
        category: str,
        amount: BudgetAmount,
        reference: str,
    ) -> UUID:
        entry_id = uuid4()
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            await self._scope_tenant(session, tenant_id)
            await session.execute(
                insert(budget_ledger).values(
                    id=str(entry_id),
                    tenant_id=str(tenant_id),
                    run_id=str(run_id),
                    category=category,
                    amount=amount.amount,
                    unit=amount.unit.value,
                    reference=reference,
                    optimistic_version=1,
                    created_at=now,
                )
            )
            await self._record_fact(
                session, tenant_id, "budget.recorded", "budget_entry", entry_id, 1, now
            )
        return entry_id

    async def add_trial(self, trial: Trial) -> None:
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            await self._scope_tenant(session, trial.tenant_id)
            await session.execute(
                insert(evaluation_trials).values(
                    id=str(trial.trial_id),
                    tenant_id=str(trial.tenant_id),
                    suite_id=trial.suite_id,
                    suite_version=trial.suite_version,
                    subject_version_id=str(trial.subject_version_id),
                    harness_version=trial.harness_version,
                    status=trial.status.value,
                    result=trial_payload(trial),
                    optimistic_version=1,
                    created_at=now,
                )
            )
            await self._record_fact(
                session, trial.tenant_id, "trial.created", "trial", trial.trial_id, 1, now
            )

    async def list_trials(self, tenant_id: UUID) -> tuple[Trial, ...]:
        return tuple(
            trial_from_row(row) for row in await self._list_rows(evaluation_trials, tenant_id)
        )

    async def add_proposal(self, proposal: ImprovementProposal) -> None:
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            await self._scope_tenant(session, proposal.tenant_id)
            await session.execute(
                insert(improvement_proposals).values(
                    id=str(proposal.proposal_id),
                    tenant_id=str(proposal.tenant_id),
                    target_type=proposal.target.value,
                    target_version_id=str(proposal.target_version_id),
                    proposal=proposal_payload(proposal),
                    optimistic_version=1,
                    created_at=now,
                )
            )
            await self._record_fact(
                session,
                proposal.tenant_id,
                "improvement.proposed",
                "improvement_proposal",
                proposal.proposal_id,
                1,
                now,
            )

    async def get_proposal(self, tenant_id: UUID, proposal_id: UUID) -> ImprovementProposal:
        return proposal_from_row(await self._get_row(improvement_proposals, tenant_id, proposal_id))

    async def list_proposals(self, tenant_id: UUID) -> tuple[ImprovementProposal, ...]:
        return tuple(
            proposal_from_row(row)
            for row in await self._list_rows(improvement_proposals, tenant_id)
        )

    async def add_candidate(self, candidate: CandidateVersion) -> None:
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            await self._scope_tenant(session, candidate.tenant_id)
            await session.execute(
                insert(candidates).values(
                    id=str(candidate.candidate_id),
                    tenant_id=str(candidate.tenant_id),
                    proposal_id=str(candidate.proposal_id),
                    baseline_version_id=str(candidate.baseline_version_id),
                    status=candidate.status.value,
                    artifact_uri=candidate.artifact_ref,
                    generator_id=candidate.generator_id,
                    definition=candidate_payload(candidate),
                    optimistic_version=candidate.optimistic_version,
                    created_at=now,
                )
            )
            await self._record_fact(
                session,
                candidate.tenant_id,
                "candidate.created",
                "candidate",
                candidate.candidate_id,
                candidate.optimistic_version,
                now,
            )

    async def get_candidate(self, tenant_id: UUID, candidate_id: UUID) -> CandidateVersion:
        return candidate_from_row(await self._get_row(candidates, tenant_id, candidate_id))

    async def save_candidate(self, candidate: CandidateVersion) -> None:
        await self._save_versioned(
            candidates,
            candidate.tenant_id,
            candidate.candidate_id,
            candidate.optimistic_version - 1,
            candidate.optimistic_version,
            {"status": candidate.status.value, "definition": candidate_payload(candidate)},
            "candidate",
        )

    async def add_deployment(self, deployment: Deployment) -> None:
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            await self._scope_tenant(session, deployment.tenant_id)
            await session.execute(
                insert(deployments).values(
                    id=str(deployment.deployment_id),
                    tenant_id=str(deployment.tenant_id),
                    candidate_id=str(deployment.candidate_id),
                    status=deployment.status.value,
                    definition=deployment_payload(deployment),
                    optimistic_version=deployment.optimistic_version,
                    created_at=now,
                )
            )
            await self._record_fact(
                session,
                deployment.tenant_id,
                "deployment.started",
                "deployment",
                deployment.deployment_id,
                deployment.optimistic_version,
                now,
            )

    async def get_deployment(self, tenant_id: UUID, deployment_id: UUID) -> Deployment:
        return deployment_from_row(await self._get_row(deployments, tenant_id, deployment_id))

    async def save_deployment(self, deployment: Deployment) -> None:
        await self._save_versioned(
            deployments,
            deployment.tenant_id,
            deployment.deployment_id,
            deployment.optimistic_version - 1,
            deployment.optimistic_version,
            {
                "status": deployment.status.value,
                "definition": deployment_payload(deployment),
            },
            "deployment",
        )

    async def add_release(self, release: Release) -> None:
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            await self._scope_tenant(session, release.tenant_id)
            candidate_row = (
                await session.execute(
                    select(candidates.c.baseline_version_id).where(
                        candidates.c.id == str(release.candidate_id),
                        candidates.c.tenant_id == str(release.tenant_id),
                    )
                )
            ).one_or_none()
            if candidate_row is None:
                raise RecordNotFound("release candidate was not found")
            stable_slot = candidate_row[0]
            await session.execute(
                update(releases)
                .where(
                    releases.c.tenant_id == str(release.tenant_id),
                    releases.c.stable_slot == stable_slot,
                    releases.c.active.is_(True),
                )
                .values(active=False, updated_at=now)
            )
            await session.execute(
                insert(releases).values(
                    id=str(release.release_id),
                    tenant_id=str(release.tenant_id),
                    candidate_id=str(release.candidate_id),
                    deployment_id=str(release.deployment_id),
                    stable_slot=stable_slot,
                    stable_version_id=str(release.stable_version_id),
                    previous_stable_version_id=str(release.previous_stable_version_id),
                    approved_by=str(release.approved_by),
                    active=True,
                    definition=release_payload(release),
                    optimistic_version=1,
                    created_at=now,
                )
            )
            await self._record_fact(
                session,
                release.tenant_id,
                "release.activated",
                "release",
                release.release_id,
                1,
                now,
            )

    async def get_active_release(self, tenant_id: UUID, release_id: UUID) -> Release:
        async with self._sessions() as session:
            await self._scope_tenant(session, tenant_id)
            row = (
                (
                    await session.execute(
                        select(releases).where(
                            releases.c.id == str(release_id),
                            releases.c.tenant_id == str(tenant_id),
                            releases.c.active.is_(True),
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise RecordNotFound(f"active release {release_id} was not found")
        return release_from_row(dict(row))

    async def list_releases(self, tenant_id: UUID) -> tuple[Release, ...]:
        return tuple(release_from_row(row) for row in await self._list_rows(releases, tenant_id))

    async def list_audit_events(self, tenant_id: UUID) -> tuple[AuditEvent, ...]:
        async with self._sessions() as session:
            await self._scope_tenant(session, tenant_id)
            rows = tuple(
                dict(row)
                for row in (
                    await session.execute(
                        select(audit_events)
                        .where(audit_events.c.tenant_id == str(tenant_id))
                        .order_by(audit_events.c.sequence.asc().nulls_first())
                    )
                ).mappings()
            )
        return tuple(
            AuditEvent(
                tenant_id=UUID(row["tenant_id"]),
                actor_id=UUID(row["actor_id"]),
                principal_id=UUID(row["principal_id"]),
                event_type=row["event_type"],
                object_type=row["object_type"],
                object_id=row["object_id"],
                correlation_id=UUID(row["correlation_id"]),
                details=row["details"],
                event_id=UUID(row["id"]),
                sequence=row["sequence"],
                previous_digest=row["previous_digest"],
                event_digest=row["event_digest"],
                created_at=row["created_at"],
            )
            for row in rows
        )

    async def get_idempotency(
        self, tenant_id: UUID, key: str, request_digest: str | None = None
    ) -> UUID | None:
        async with self._sessions() as session:
            await self._scope_tenant(session, tenant_id)
            row = (
                await session.execute(
                    select(
                        idempotency_records.c.external_id,
                        idempotency_records.c.request_digest,
                    ).where(
                        idempotency_records.c.tenant_id == str(tenant_id),
                        idempotency_records.c.idempotency_key == key,
                        idempotency_records.c.status == "completed",
                    )
                )
            ).one_or_none()
        if row is None:
            return None
        if request_digest is not None and row.request_digest != request_digest:
            raise ConcurrencyConflict("idempotency key was reused with a different request")
        return UUID(row.external_id)

    async def put_idempotency(
        self,
        tenant_id: UUID,
        key: str,
        external_id: UUID,
        request_digest: str | None = None,
    ) -> None:
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            await self._scope_tenant(session, tenant_id)
            values = {
                "id": str(uuid4()),
                "tenant_id": str(tenant_id),
                "idempotency_key": key,
                "request_digest": request_digest or "0" * 64,
                "external_id": str(external_id),
                "status": "completed",
                "response": None,
                "optimistic_version": 1,
                "created_at": now,
            }
            statement = (
                postgresql_insert(idempotency_records)
                if self._uses_postgresql
                else sqlite_insert(idempotency_records)
            ).values(**values)
            result = cast(
                CursorResult[Any],
                await session.execute(
                    statement.on_conflict_do_nothing(
                        index_elements=["tenant_id", "idempotency_key"]
                    )
                ),
            )
            if result.rowcount == 0:
                accepted = (
                    await session.execute(
                        select(
                            idempotency_records.c.external_id,
                            idempotency_records.c.request_digest,
                        ).where(
                            idempotency_records.c.tenant_id == str(tenant_id),
                            idempotency_records.c.idempotency_key == key,
                        )
                    )
                ).one()
                if accepted.external_id != str(external_id) or (
                    request_digest is not None and accepted.request_digest != request_digest
                ):
                    raise ConcurrencyConflict(
                        "idempotency key is already bound to a different result"
                    )

    async def _get_row(self, table: Any, tenant_id: UUID, object_id: UUID) -> dict[str, Any]:
        async with self._sessions() as session:
            await self._scope_tenant(session, tenant_id)
            row = (
                (
                    await session.execute(
                        select(table).where(
                            table.c.id == str(object_id), table.c.tenant_id == str(tenant_id)
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise RecordNotFound(f"{table.name} {object_id} was not found")
        return dict(row)

    async def _get_row_in_session(
        self,
        session: AsyncSession,
        table: Any,
        tenant_id: UUID,
        object_id: UUID,
    ) -> dict[str, Any]:
        row = (
            (
                await session.execute(
                    select(table).where(
                        table.c.id == str(object_id), table.c.tenant_id == str(tenant_id)
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise RecordNotFound(f"{table.name} {object_id} was not found")
        return dict(row)

    async def _list_rows(self, table: Any, tenant_id: UUID) -> tuple[dict[str, Any], ...]:
        async with self._sessions() as session:
            await self._scope_tenant(session, tenant_id)
            rows = (
                await session.execute(select(table).where(table.c.tenant_id == str(tenant_id)))
            ).mappings()
            return tuple(dict(row) for row in rows)

    async def _save_versioned(
        self,
        table: Any,
        tenant_id: UUID,
        object_id: UUID,
        expected_version: int,
        new_version: int,
        values: dict[str, Any],
        object_type: str,
    ) -> None:
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            await self._scope_tenant(session, tenant_id)
            result = cast(
                CursorResult[Any],
                await session.execute(
                    update(table)
                    .where(
                        table.c.id == str(object_id),
                        table.c.tenant_id == str(tenant_id),
                        table.c.optimistic_version == expected_version,
                    )
                    .values(**values, optimistic_version=new_version, updated_at=now)
                ),
            )
            if result.rowcount != 1:
                raise ConcurrencyConflict(f"{object_type} optimistic version changed")
            await self._record_fact(
                session,
                tenant_id,
                f"{object_type}.updated",
                object_type,
                object_id,
                new_version,
                now,
            )

    async def _add_config_asset(
        self,
        table: Any,
        id_column: str,
        tenant_id: UUID,
        asset_id: str,
        definition: dict[str, Any],
    ) -> dict[str, object]:
        version = str(definition.get("version", "1"))
        value: dict[str, object] = {
            "asset_id": asset_id,
            "tenant_id": str(tenant_id),
            "version": version,
            "definition": definition,
        }
        record_id = uuid4()
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            await self._scope_tenant(session, tenant_id)
            await session.execute(
                insert(table).values(
                    id=str(record_id),
                    tenant_id=str(tenant_id),
                    **{id_column: asset_id},
                    version=version,
                    definition=definition,
                    optimistic_version=1,
                    created_at=now,
                )
            )
            await self._record_fact(
                session,
                tenant_id,
                f"{table.name}.created",
                table.name,
                record_id,
                1,
                now,
            )
        return value

    async def _list_config_assets(
        self, table: Any, id_column: str, tenant_id: UUID
    ) -> tuple[dict[str, object], ...]:
        return tuple(
            {
                "asset_id": row[id_column],
                "tenant_id": row["tenant_id"],
                "version": row["version"],
                "definition": row["definition"],
            }
            for row in await self._list_rows(table, tenant_id)
        )

    async def _record_fact(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        event_type: str,
        object_type: str,
        object_id: UUID,
        version: int,
        created_at: datetime,
    ) -> None:
        audit = AuditEvent(
            tenant_id=tenant_id,
            actor_id=UUID(int=0),
            principal_id=UUID(int=0),
            event_type=event_type,
            object_type=object_type,
            object_id=str(object_id),
            correlation_id=uuid4(),
            details={"version": version},
        )
        await self._add_audit_and_outbox(session, audit, created_at)

    async def _add_audit_and_outbox(
        self,
        session: AsyncSession,
        audit: AuditEvent,
        created_at: datetime,
    ) -> AuditEvent:
        chained = await self._add_audit(session, audit, created_at)
        await self._add_outbox(session, chained, created_at)
        return chained

    async def _add_audit(
        self, session: AsyncSession, audit: AuditEvent, created_at: datetime
    ) -> AuditEvent:
        if self._uses_postgresql:
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:tenant_id, 0))"),
                {"tenant_id": str(audit.tenant_id)},
            )
        previous = (
            await session.execute(
                select(audit_events.c.sequence, audit_events.c.event_digest)
                .where(
                    audit_events.c.tenant_id == str(audit.tenant_id),
                    audit_events.c.sequence.is_not(None),
                    audit_events.c.event_digest.is_not(None),
                )
                .order_by(audit_events.c.sequence.desc())
                .limit(1)
            )
        ).one_or_none()
        sequence = int(previous.sequence) + 1 if previous is not None else 1
        previous_digest = str(previous.event_digest) if previous is not None else "0" * 64
        chained = audit.chained(sequence, previous_digest, created_at)
        await session.execute(
            insert(audit_events).values(
                id=str(chained.event_id),
                tenant_id=str(chained.tenant_id),
                actor_id=str(chained.actor_id),
                principal_id=str(chained.principal_id),
                event_type=chained.event_type,
                object_type=chained.object_type,
                object_id=chained.object_id,
                correlation_id=str(chained.correlation_id),
                details=chained.details,
                sequence=chained.sequence,
                previous_digest=chained.previous_digest,
                event_digest=chained.event_digest,
                optimistic_version=1,
                created_at=created_at,
            )
        )
        return chained

    @staticmethod
    async def _add_outbox(session: AsyncSession, audit: AuditEvent, created_at: datetime) -> None:
        await session.execute(
            insert(outbox).values(
                id=str(uuid4()),
                tenant_id=str(audit.tenant_id),
                schema=f"autonoesis.{audit.event_type}.v1",
                payload={
                    "event_type": audit.event_type,
                    "object_type": audit.object_type,
                    "object_id": audit.object_id,
                    "correlation_id": str(audit.correlation_id),
                    "audit_ref": audit.audit_ref,
                    "audit_sequence": audit.sequence,
                    "audit_digest": audit.event_digest,
                    "details": audit.details,
                },
                optimistic_version=1,
                created_at=created_at,
            )
        )

    @staticmethod
    def _manifest_payload(manifest: CapabilityPackManifest) -> dict[str, Any]:
        return {
            "api_version": manifest.api_version,
            "pack_id": manifest.pack_id,
            "version": manifest.version,
            "python_entry_point": manifest.python_entry_point,
            "goal_types": [
                {
                    "goal_type": item.goal_type,
                    "input_schema": item.input_schema,
                    "agent": item.agent,
                    "evaluation_suite": item.evaluation_suite,
                    "default_policy": item.default_policy,
                    "default_budget": item.default_budget,
                }
                for item in manifest.goal_types
            ],
            "skills": list(manifest.skills),
            "tools": list(manifest.tools),
            "policies": list(manifest.policies),
            "evaluation_suites": list(manifest.evaluation_suites),
        }

    @staticmethod
    def _agent_payload(version: AgentVersion) -> dict[str, Any]:
        return {
            "instruction": version.instruction,
            "model_route": version.model_route,
            "skill_ids": version.skill_ids,
            "tool_ids": version.tool_ids,
            "loop_policy": {
                "max_rounds": version.loop_policy.max_rounds,
                "max_tokens": version.loop_policy.max_tokens,
                "max_cost_units": version.loop_policy.max_cost_units,
                "timeout_seconds": version.loop_policy.timeout_seconds,
            },
        }

    @staticmethod
    def _agent_from_row(row: dict[str, Any]) -> AgentVersion:
        definition = row["definition"]
        loop = definition["loop_policy"]
        return AgentVersion(
            tenant_id=UUID(row["tenant_id"]),
            agent_id=UUID(row["agent_id"]),
            version=row["version"],
            instruction=definition["instruction"],
            model_route=definition["model_route"],
            skill_ids=tuple(definition["skill_ids"]),
            tool_ids=tuple(definition["tool_ids"]),
            loop_policy=LoopPolicy(**loop),
            stage=AssetStage(row["stage"]),
            agent_version_id=UUID(row["id"]),
        )

    @staticmethod
    def _goal_payload(goal: GoalContract) -> dict[str, Any]:
        return {
            "statement": goal.statement,
            "desired_outcome": goal.desired_outcome,
            "subject_refs": [
                {
                    "system": ref.system,
                    "subject_type": ref.subject_type,
                    "subject_id": ref.subject_id,
                    "version": ref.version,
                }
                for ref in goal.subject_refs
            ],
            "success_criteria": [
                {
                    "criterion_id": item.criterion_id,
                    "description": item.description,
                    "evidence_type": item.evidence_type,
                }
                for item in goal.success_criteria
            ],
            "constraints": goal.constraints,
            "risk_tier": goal.risk_tier.value,
            "budget_limit": {
                "amount": goal.budget_limit.amount,
                "unit": goal.budget_limit.unit.value,
            },
            "deadline": goal.deadline.isoformat(),
            "input_payload": goal.input_payload.to_value(),
            "delegation_id": str(goal.delegation_id) if goal.delegation_id else None,
            "data_policy": {
                "maximum_classification": goal.data_policy.maximum_classification.value,
                "allowed_regions": goal.data_policy.allowed_regions,
                "retention_days": goal.data_policy.retention_days,
            },
            "execution_mode": goal.execution_mode.value,
            "max_concurrent_runs": goal.max_concurrent_runs,
            "transitions": [transition_payload(item) for item in goal.transitions],
        }

    @staticmethod
    def _goal_from_row(row: dict[str, Any]) -> GoalContract:
        payload = row["contract"]
        return GoalContract(
            tenant_id=UUID(row["tenant_id"]),
            goal_type=row["goal_type"],
            statement=payload["statement"],
            desired_outcome=payload["desired_outcome"],
            subject_refs=tuple(SubjectRef(**item) for item in payload["subject_refs"]),
            success_criteria=tuple(
                SuccessCriterion(**item) for item in payload["success_criteria"]
            ),
            constraints=tuple(payload["constraints"]),
            owner_id=UUID(row["owner_id"]),
            risk_tier=RiskTier(payload["risk_tier"]),
            budget_limit=BudgetAmount(
                payload["budget_limit"]["amount"],
                BudgetUnit(payload["budget_limit"]["unit"]),
            ),
            deadline=datetime.fromisoformat(payload["deadline"]),
            input_payload=JsonObject.from_value(payload["input_payload"]),
            delegation_id=(
                UUID(payload["delegation_id"]) if payload.get("delegation_id") else None
            ),
            data_policy=DataPolicy(
                maximum_classification=DataClassification(
                    payload.get("data_policy", {}).get(
                        "maximum_classification", DataClassification.INTERNAL.value
                    )
                ),
                allowed_regions=tuple(payload.get("data_policy", {}).get("allowed_regions", ())),
                retention_days=payload.get("data_policy", {}).get("retention_days", 30),
            ),
            execution_mode=ExecutionMode(
                payload.get("execution_mode", ExecutionMode.SUPERVISED.value)
            ),
            max_concurrent_runs=payload.get("max_concurrent_runs", 1),
            goal_id=UUID(row["id"]),
            version=row["optimistic_version"],
            status=GoalStatus(row["status"]),
            created_at=row["created_at"],
            transitions=transitions_from(payload.get("transitions")),
        )


def create_repository(
    database_url: str,
) -> tuple[AsyncEngine, SqlAlchemyPlatformRepository]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    return engine, SqlAlchemyPlatformRepository(sessions)
