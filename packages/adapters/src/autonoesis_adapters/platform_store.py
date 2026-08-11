"""Process-scoped PostgreSQL platform store with no in-memory business state."""

from typing import Any
from uuid import UUID

from autonoesis_application import AuditEvent
from autonoesis_capability import CapabilityPackManifest, GoalTypeManifest
from autonoesis_domain import (
    AgentVersion,
    ApprovalRequest,
    CandidateVersion,
    Deployment,
    Evidence,
    GoalContract,
    ImprovementProposal,
    MemoryRecord,
    Release,
    Run,
    Trial,
)
from autonoesis_runtime import TenantTelemetryRecord
from sqlalchemy.ext.asyncio import AsyncEngine

from autonoesis_adapters.persistence import SqlAlchemyPlatformRepository, create_repository


class PostgreSQLPlatformStore:
    """Aggregate-oriented façade over a shared process-level engine and pool."""

    def __init__(self, engine: AsyncEngine, repository: SqlAlchemyPlatformRepository) -> None:
        self.engine = engine
        self.repository = repository

    @classmethod
    def from_url(cls, database_url: str) -> "PostgreSQLPlatformStore":
        engine, repository = create_repository(database_url)
        return cls(engine, repository)

    async def close(self) -> None:
        await self.engine.dispose()

    async def add_capability_pack(self, tenant_id: UUID, manifest: CapabilityPackManifest) -> None:
        await self.repository.add_capability_pack(tenant_id, manifest)

    async def list_capability_packs(self, tenant_id: UUID) -> tuple[CapabilityPackManifest, ...]:
        return await self.repository.list_capability_packs(tenant_id)

    async def get_goal_type(self, tenant_id: UUID, goal_type: str) -> GoalTypeManifest:
        return await self.repository.get_goal_type(tenant_id, goal_type)

    async def add_agent(self, name: str, version: AgentVersion) -> None:
        await self.repository.add_agent(name, version)

    async def list_agents(self, tenant_id: UUID) -> tuple[tuple[str, AgentVersion], ...]:
        return await self.repository.list_agents(tenant_id)

    async def get_stable_agent(self, tenant_id: UUID, agent_name: str) -> AgentVersion:
        return await self.repository.get_stable_agent(tenant_id, agent_name)

    async def add_skill(
        self, tenant_id: UUID, asset_id: str, definition: dict[str, Any]
    ) -> dict[str, object]:
        return await self.repository.add_skill(tenant_id, asset_id, definition)

    async def list_skills(self, tenant_id: UUID) -> tuple[dict[str, object], ...]:
        return await self.repository.list_skills(tenant_id)

    async def add_tool(
        self, tenant_id: UUID, asset_id: str, definition: dict[str, Any]
    ) -> dict[str, object]:
        return await self.repository.add_tool(tenant_id, asset_id, definition)

    async def list_tools(self, tenant_id: UUID) -> tuple[dict[str, object], ...]:
        return await self.repository.list_tools(tenant_id)

    async def add_policy(
        self, tenant_id: UUID, asset_id: str, definition: dict[str, Any]
    ) -> dict[str, object]:
        return await self.repository.add_policy(tenant_id, asset_id, definition)

    async def list_policies(self, tenant_id: UUID) -> tuple[dict[str, object], ...]:
        return await self.repository.list_policies(tenant_id)

    async def add_budget(
        self, tenant_id: UUID, asset_id: str, definition: dict[str, Any]
    ) -> dict[str, object]:
        return await self.repository.add_budget(tenant_id, asset_id, definition)

    async def list_budgets(self, tenant_id: UUID) -> tuple[dict[str, object], ...]:
        return await self.repository.list_budgets(tenant_id)

    async def add_goal(self, goal: GoalContract, audit: AuditEvent) -> None:
        await self.repository.add_goal(goal, audit)

    async def get_goal(self, tenant_id: UUID, goal_id: UUID) -> GoalContract:
        return await self.repository.get_goal(tenant_id, goal_id)

    async def list_goals(self, tenant_id: UUID) -> tuple[GoalContract, ...]:
        return await self.repository.list_goals(tenant_id)

    async def add_run(self, run: Run, audit: AuditEvent) -> None:
        await self.repository.add_run(run, audit)

    async def get_run(self, tenant_id: UUID, run_id: UUID) -> Run:
        return await self.repository.get_run(tenant_id, run_id)

    async def save_run(self, run: Run, expected_version: int) -> None:
        await self.repository.save_run(run, expected_version)

    async def list_runs(self, tenant_id: UUID, goal_id: UUID | None = None) -> tuple[Run, ...]:
        return await self.repository.list_runs(tenant_id, goal_id)

    async def list_audit_events(self, tenant_id: UUID) -> tuple[AuditEvent, ...]:
        return await self.repository.list_audit_events(tenant_id)

    async def list_approvals(self, tenant_id: UUID) -> tuple[ApprovalRequest, ...]:
        return await self.repository.list_approvals(tenant_id)

    async def get_approval(self, tenant_id: UUID, approval_id: UUID) -> ApprovalRequest:
        return await self.repository.get_approval(tenant_id, approval_id)

    async def save_approval(self, approval: ApprovalRequest, expected_version: int) -> None:
        await self.repository.save_approval(approval, expected_version)

    async def save_approval_record(
        self, tenant_id: UUID, approval_id: UUID, value: dict[str, object]
    ) -> None:
        raise TypeError("PostgreSQL approvals must use the domain ApprovalRequest contract")

    async def list_evidence(self, tenant_id: UUID) -> tuple[Evidence, ...]:
        return await self.repository.list_evidence(tenant_id)

    async def add_memory(self, item: MemoryRecord) -> None:
        await self.repository.add_memory(item)

    async def list_memory(self, tenant_id: UUID) -> tuple[MemoryRecord, ...]:
        return await self.repository.list_memory(tenant_id)

    async def add_telemetry(self, item: TenantTelemetryRecord) -> None:
        await self.repository.add_telemetry(item)

    async def list_telemetry(self, tenant_id: UUID) -> tuple[TenantTelemetryRecord, ...]:
        return await self.repository.list_telemetry(tenant_id)

    async def register_tenant_namespace(
        self, tenant_id: UUID, resource_kind: str, logical_name: str, physical_namespace: str
    ) -> dict[str, str]:
        return await self.repository.register_tenant_namespace(
            tenant_id, resource_kind, logical_name, physical_namespace
        )

    async def list_tenant_namespaces(self, tenant_id: UUID) -> tuple[dict[str, str], ...]:
        return await self.repository.list_tenant_namespaces(tenant_id)

    async def add_trial(self, trial: Trial) -> None:
        await self.repository.add_trial(trial)

    async def list_trials(self, tenant_id: UUID) -> tuple[Trial, ...]:
        return await self.repository.list_trials(tenant_id)

    async def add_proposal(self, proposal: ImprovementProposal) -> None:
        await self.repository.add_proposal(proposal)

    async def get_proposal(self, tenant_id: UUID, proposal_id: UUID) -> ImprovementProposal:
        return await self.repository.get_proposal(tenant_id, proposal_id)

    async def list_proposals(self, tenant_id: UUID) -> tuple[ImprovementProposal, ...]:
        return await self.repository.list_proposals(tenant_id)

    async def add_candidate(self, candidate: CandidateVersion) -> None:
        await self.repository.add_candidate(candidate)

    async def get_candidate(self, tenant_id: UUID, candidate_id: UUID) -> CandidateVersion:
        return await self.repository.get_candidate(tenant_id, candidate_id)

    async def save_candidate(self, candidate: CandidateVersion) -> None:
        await self.repository.save_candidate(candidate)

    async def add_deployment(self, deployment: Deployment) -> None:
        await self.repository.add_deployment(deployment)

    async def get_deployment(self, tenant_id: UUID, deployment_id: UUID) -> Deployment:
        return await self.repository.get_deployment(tenant_id, deployment_id)

    async def save_deployment(self, deployment: Deployment) -> None:
        await self.repository.save_deployment(deployment)

    async def add_release(self, release: Release) -> None:
        await self.repository.add_release(release)

    async def get_active_release(self, tenant_id: UUID, release_id: UUID) -> Release:
        return await self.repository.get_active_release(tenant_id, release_id)

    async def list_releases(self, tenant_id: UUID) -> tuple[Release, ...]:
        return await self.repository.list_releases(tenant_id)

    async def get_idempotency(
        self, tenant_id: UUID, key: str, request_digest: str | None = None
    ) -> UUID | None:
        return await self.repository.get_idempotency(tenant_id, key, request_digest)

    async def put_idempotency(
        self,
        tenant_id: UUID,
        key: str,
        external_id: UUID,
        request_digest: str | None = None,
    ) -> None:
        await self.repository.put_idempotency(tenant_id, key, external_id, request_digest)
