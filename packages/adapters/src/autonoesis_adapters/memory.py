"""Deterministic in-memory platform adapters for tests and offline development."""

from collections import defaultdict
from uuid import UUID

from autonoesis_application import (
    AuditEvent,
    ConcurrencyConflict,
    RecordNotFound,
    TenantBoundaryViolation,
)
from autonoesis_capability import CapabilityPackManifest, GoalTypeManifest
from autonoesis_domain import (
    AgentVersion,
    CandidateVersion,
    Deployment,
    GoalContract,
    ImprovementProposal,
    Release,
    Run,
)
from autonoesis_runtime import ToolReceipt


class InMemoryPlatformStore:
    def __init__(self) -> None:
        self.goals: dict[UUID, GoalContract] = {}
        self.runs: dict[UUID, Run] = {}
        self.goal_types: dict[str, GoalTypeManifest] = {}
        self.packs: dict[str, CapabilityPackManifest] = {}
        self.agents: dict[tuple[UUID, str], AgentVersion] = {}
        self.skills: dict[str, dict[str, object]] = {}
        self.tools: dict[str, dict[str, object]] = {}
        self.policies: dict[str, dict[str, object]] = {}
        self.budgets: dict[str, dict[str, object]] = {}
        self.approvals: dict[UUID, dict[str, object]] = {}
        self.evidence: dict[UUID, dict[str, object]] = {}
        self.audits: list[AuditEvent] = []
        self.proposals: dict[UUID, ImprovementProposal] = {}
        self.candidates: dict[UUID, CandidateVersion] = {}
        self.deployments: dict[UUID, Deployment] = {}
        self.releases: dict[UUID, Release] = {}

    @staticmethod
    def _assert_tenant(expected: UUID, actual: UUID) -> None:
        if expected != actual:
            raise TenantBoundaryViolation("record belongs to a different tenant")

    def register_pack(self, manifest: CapabilityPackManifest) -> None:
        self.packs[manifest.pack_id] = manifest
        for goal_type in manifest.goal_types:
            self.goal_types[goal_type.goal_type] = goal_type

    def register_agent(self, name: str, version: AgentVersion) -> None:
        self.agents[(version.tenant_id, name)] = version

    async def get_goal_type(self, goal_type: str) -> GoalTypeManifest:
        try:
            return self.goal_types[goal_type]
        except KeyError as exc:
            raise RecordNotFound(f"goal type {goal_type} was not found") from exc

    async def get_stable_agent(self, tenant_id: UUID, agent_name: str) -> AgentVersion:
        try:
            version = self.agents[(tenant_id, agent_name)]
        except KeyError as exc:
            raise RecordNotFound(f"stable agent {agent_name} was not found") from exc
        return version

    async def add_goal(self, goal: GoalContract, audit: AuditEvent) -> None:
        self.goals[goal.goal_id] = goal
        self.audits.append(audit)

    async def get_goal(self, tenant_id: UUID, goal_id: UUID) -> GoalContract:
        try:
            goal = self.goals[goal_id]
        except KeyError as exc:
            raise RecordNotFound(f"goal {goal_id} was not found") from exc
        self._assert_tenant(tenant_id, goal.tenant_id)
        return goal

    async def list_goals(self, tenant_id: UUID) -> tuple[GoalContract, ...]:
        return tuple(goal for goal in self.goals.values() if goal.tenant_id == tenant_id)

    async def add_run(self, run: Run, audit: AuditEvent) -> None:
        self.runs[run.run_id] = run
        self.audits.append(audit)

    async def get_run(self, tenant_id: UUID, run_id: UUID) -> Run:
        try:
            run = self.runs[run_id]
        except KeyError as exc:
            raise RecordNotFound(f"run {run_id} was not found") from exc
        self._assert_tenant(tenant_id, run.tenant_id)
        return run

    async def save_run(self, run: Run, expected_version: int) -> None:
        current = await self.get_run(run.tenant_id, run.run_id)
        if current.optimistic_version != expected_version:
            raise ConcurrencyConflict("run optimistic version changed")
        self.runs[run.run_id] = run

    async def list_runs(self, tenant_id: UUID, goal_id: UUID | None = None) -> tuple[Run, ...]:
        return tuple(
            run
            for run in self.runs.values()
            if run.tenant_id == tenant_id and (goal_id is None or run.goal_id == goal_id)
        )

    async def add_candidate(self, candidate: CandidateVersion) -> None:
        self.candidates[candidate.candidate_id] = candidate

    async def get_candidate(self, tenant_id: UUID, candidate_id: UUID) -> CandidateVersion:
        try:
            candidate = self.candidates[candidate_id]
        except KeyError as exc:
            raise RecordNotFound(f"candidate {candidate_id} was not found") from exc
        self._assert_tenant(tenant_id, candidate.tenant_id)
        return candidate

    async def save_candidate(self, candidate: CandidateVersion) -> None:
        self.candidates[candidate.candidate_id] = candidate

    async def add_deployment(self, deployment: Deployment) -> None:
        self.deployments[deployment.deployment_id] = deployment

    async def get_deployment(self, tenant_id: UUID, deployment_id: UUID) -> Deployment:
        try:
            deployment = self.deployments[deployment_id]
        except KeyError as exc:
            raise RecordNotFound(f"deployment {deployment_id} was not found") from exc
        self._assert_tenant(tenant_id, deployment.tenant_id)
        return deployment

    async def save_deployment(self, deployment: Deployment) -> None:
        self.deployments[deployment.deployment_id] = deployment

    async def add_release(self, release: Release) -> None:
        self.releases[release.release_id] = release

    async def get_active_release(self, tenant_id: UUID, release_id: UUID) -> Release:
        try:
            release = self.releases[release_id]
        except KeyError as exc:
            raise RecordNotFound(f"release {release_id} was not found") from exc
        self._assert_tenant(tenant_id, release.tenant_id)
        return release


class InMemoryIdempotencyStore:
    def __init__(self) -> None:
        self.receipts: dict[str, ToolReceipt] = {}

    async def get(self, key: str) -> ToolReceipt | None:
        return self.receipts.get(key)

    async def put(self, key: str, receipt: ToolReceipt) -> None:
        self.receipts[key] = receipt


class InMemoryBudgetLedger:
    def __init__(self, limit: int = 10_000) -> None:
        self.limit = limit
        self.used: dict[tuple[str, str], int] = defaultdict(int)

    async def reserve(self, tenant_id: str, run_id: str, units: int) -> bool:
        key = (tenant_id, run_id)
        if units <= 0 or self.used[key] + units > self.limit:
            return False
        self.used[key] += units
        return True
