"""PostgreSQL metadata and authoritative Goal/Run repository."""

from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4

from autonoesis_application import AuditEvent, ConcurrencyConflict, RecordNotFound
from autonoesis_domain import (
    BudgetAmount,
    BudgetUnit,
    DataClassification,
    DataPolicy,
    ExecutionMode,
    GoalContract,
    GoalStatus,
    JsonObject,
    RiskTier,
    Run,
    RunStatus,
    SubjectRef,
    SuccessCriterion,
)
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

metadata = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)


def tenant_table(name: str, *columns: Column[Any]) -> Table:
    return Table(
        name,
        metadata,
        Column("id", String(36), primary_key=True),
        Column("tenant_id", String(36), nullable=False, index=True),
        *columns,
        Column("optimistic_version", Integer, nullable=False, default=1),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=True),
    )


tenants = Table(
    "tenants",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("name", String(200), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
capability_packs = tenant_table(
    "capability_packs",
    Column("pack_id", String(200), nullable=False),
    Column("version", String(64), nullable=False),
    Column("manifest", JSON, nullable=False),
    Column("enabled", Boolean, nullable=False, default=True),
)
agent_versions = tenant_table(
    "agent_versions",
    Column("agent_id", String(36), nullable=False),
    Column("version", Integer, nullable=False),
    Column("stage", String(32), nullable=False),
    Column("definition", JSON, nullable=False),
)
skill_versions = tenant_table(
    "skill_versions",
    Column("skill_id", String(200), nullable=False),
    Column("version", String(64), nullable=False),
    Column("definition", JSON, nullable=False),
)
tool_versions = tenant_table(
    "tool_versions",
    Column("tool_id", String(200), nullable=False),
    Column("version", String(64), nullable=False),
    Column("definition", JSON, nullable=False),
)
goals = tenant_table(
    "goals",
    Column("goal_type", String(200), nullable=False),
    Column("owner_id", String(36), nullable=False),
    Column("status", String(32), nullable=False),
    Column("contract", JSON, nullable=False),
)
runs = tenant_table(
    "runs",
    Column("goal_id", String(36), ForeignKey("goals.id"), nullable=False),
    Column("agent_version_id", String(36), nullable=False),
    Column("status", String(32), nullable=False),
    Column("temporal_workflow_id", String(200), nullable=True),
)
plans = tenant_table(
    "plans",
    Column("run_id", String(36), ForeignKey("runs.id"), nullable=False),
    Column("version", Integer, nullable=False),
    Column("definition", JSON, nullable=False),
)
tasks = tenant_table(
    "tasks",
    Column("run_id", String(36), ForeignKey("runs.id"), nullable=False),
    Column("plan_id", String(36), ForeignKey("plans.id"), nullable=False),
    Column("status", String(32), nullable=False),
    Column("definition", JSON, nullable=False),
)
actions = tenant_table(
    "actions",
    Column("run_id", String(36), ForeignKey("runs.id"), nullable=False),
    Column("task_id", String(36), ForeignKey("tasks.id"), nullable=False),
    Column("status", String(32), nullable=False),
    Column("idempotency_key", String(300), nullable=False),
    Column("definition", JSON, nullable=False),
)
approvals = tenant_table(
    "approvals",
    Column("action_id", String(36), ForeignKey("actions.id"), nullable=False),
    Column("status", String(32), nullable=False),
    Column("action_digest", String(64), nullable=False),
    Column("decision", JSON, nullable=True),
)
context_snapshots = tenant_table(
    "context_snapshots",
    Column("goal_id", String(36), ForeignKey("goals.id"), nullable=False),
    Column("run_id", String(36), ForeignKey("runs.id"), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("content_digest", String(64), nullable=False),
)
evidence = tenant_table(
    "evidence",
    Column("run_id", String(36), ForeignKey("runs.id"), nullable=False),
    Column("source", String(300), nullable=False),
    Column("artifact_uri", String(1000), nullable=False),
    Column("content_digest", String(64), nullable=False),
)
outcomes = tenant_table(
    "outcomes",
    Column("goal_id", String(36), ForeignKey("goals.id"), nullable=False),
    Column("run_id", String(36), ForeignKey("runs.id"), nullable=False),
    Column("status", String(32), nullable=False),
    Column("result", JSON, nullable=False),
)
budget_ledger = tenant_table(
    "budget_ledger",
    Column("run_id", String(36), ForeignKey("runs.id"), nullable=False),
    Column("category", String(64), nullable=False),
    Column("units", BigInteger, nullable=False),
    Column("reference", String(300), nullable=False),
)
evaluation_trials = tenant_table(
    "evaluation_trials",
    Column("suite_id", String(200), nullable=False),
    Column("subject_version_id", String(36), nullable=False),
    Column("status", String(32), nullable=False),
    Column("result", JSON, nullable=True),
)
improvement_proposals = tenant_table(
    "improvement_proposals",
    Column("target_type", String(64), nullable=False),
    Column("target_version_id", String(36), nullable=False),
    Column("proposal", JSON, nullable=False),
)
candidates = tenant_table(
    "candidates",
    Column("proposal_id", String(36), ForeignKey("improvement_proposals.id"), nullable=False),
    Column("status", String(32), nullable=False),
    Column("artifact_uri", String(1000), nullable=False),
)
releases = tenant_table(
    "releases",
    Column("candidate_id", String(36), ForeignKey("candidates.id"), nullable=False),
    Column("stable_version_id", String(36), nullable=False),
    Column("previous_stable_version_id", String(36), nullable=False),
    Column("status", String(32), nullable=False),
)
audit_events = tenant_table(
    "audit_events",
    Column("actor_id", String(36), nullable=False),
    Column("principal_id", String(36), nullable=False),
    Column("event_type", String(200), nullable=False),
    Column("object_type", String(100), nullable=False),
    Column("object_id", String(200), nullable=False),
    Column("correlation_id", String(36), nullable=False),
    Column("details", JSON, nullable=False),
)
kill_switches = tenant_table(
    "kill_switches",
    Column("dimension", String(32), nullable=False),
    Column("target", String(300), nullable=False),
    Column("reason", String(1000), nullable=False),
    Column("activated_by", String(300), nullable=False),
    Column("deactivated_at", DateTime(timezone=True), nullable=True),
)
outbox = tenant_table(
    "outbox",
    Column("schema", String(200), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=True),
)
inbox = tenant_table(
    "inbox",
    Column("message_id", String(36), nullable=False, unique=True),
    Column("processed_at", DateTime(timezone=True), nullable=False),
)
idempotency_records = tenant_table(
    "idempotency_records",
    Column("idempotency_key", String(300), nullable=False),
    Column("request_digest", String(64), nullable=False),
    Column("external_id", String(300), nullable=True),
    Column("status", String(32), nullable=False),
    Column("response", JSON, nullable=True),
)
UniqueConstraint(
    actions.c.tenant_id,
    actions.c.idempotency_key,
    name="uq_actions_tenant_idempotency_key",
)
UniqueConstraint(
    idempotency_records.c.tenant_id,
    idempotency_records.c.idempotency_key,
    name="uq_idempotency_records_tenant_key",
)


class SqlAlchemyPlatformRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions
        bind = sessions.kw.get("bind")
        self._uses_postgresql = bind is not None and bind.dialect.name == "postgresql"

    async def _scope_tenant(self, session: AsyncSession, tenant_id: UUID) -> None:
        if self._uses_postgresql:
            await session.execute(select(func.set_config("app.tenant_id", str(tenant_id), True)))

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
            await self._add_audit(session, audit, goal.created_at)

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
                    temporal_workflow_id=f"goal-run-{run.run_id}",
                    optimistic_version=run.optimistic_version,
                    created_at=run.created_at,
                )
            )
            await self._add_audit(session, audit, run.created_at)

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
        return Run(
            tenant_id=UUID(row["tenant_id"]),
            goal_id=UUID(row["goal_id"]),
            agent_version_id=UUID(row["agent_version_id"]),
            run_id=UUID(row["id"]),
            status=RunStatus(row["status"]),
            optimistic_version=row["optimistic_version"],
            created_at=row["created_at"],
        )

    async def save_run(self, run: Run, expected_version: int) -> None:
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
                    .values(status=run.status.value, optimistic_version=run.optimistic_version)
                ),
            )
            if result.rowcount != 1:
                raise ConcurrencyConflict("run optimistic version changed")

    async def list_runs(self, tenant_id: UUID, goal_id: UUID | None = None) -> tuple[Run, ...]:
        async with self._sessions() as session:
            await self._scope_tenant(session, tenant_id)
            query = select(runs).where(runs.c.tenant_id == str(tenant_id))
            if goal_id is not None:
                query = query.where(runs.c.goal_id == str(goal_id))
            rows = (await session.execute(query)).mappings()
            return tuple(
                Run(
                    tenant_id=UUID(row["tenant_id"]),
                    goal_id=UUID(row["goal_id"]),
                    agent_version_id=UUID(row["agent_version_id"]),
                    run_id=UUID(row["id"]),
                    status=RunStatus(row["status"]),
                    optimistic_version=row["optimistic_version"],
                    created_at=row["created_at"],
                )
                for row in rows
            )

    @staticmethod
    async def _add_audit(session: AsyncSession, audit: AuditEvent, created_at: datetime) -> None:
        await session.execute(
            insert(audit_events).values(
                id=str(uuid4()),
                tenant_id=str(audit.tenant_id),
                actor_id=str(audit.actor_id),
                principal_id=str(audit.principal_id),
                event_type=audit.event_type,
                object_type=audit.object_type,
                object_id=audit.object_id,
                correlation_id=str(audit.correlation_id),
                details=audit.details,
                optimistic_version=1,
                created_at=created_at,
            )
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
        )


def create_repository(
    database_url: str,
) -> tuple[AsyncEngine, SqlAlchemyPlatformRepository]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    return engine, SqlAlchemyPlatformRepository(sessions)
