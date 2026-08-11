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
    ApprovalRequest,
    CandidateVersion,
    Deployment,
    Evidence,
    GoalContract,
    ImprovementProposal,
    Release,
    Run,
    Trial,
)
from autonoesis_runtime import ToolReceipt


class InMemoryPlatformStore:
    def __init__(self) -> None:
        self.goals: dict[UUID, GoalContract] = {}
        self.runs: dict[UUID, Run] = {}
        self.goal_types: dict[str, GoalTypeManifest] = {}
        self.packs: dict[str, CapabilityPackManifest] = {}
        self.tenant_goal_types: dict[tuple[UUID, str], GoalTypeManifest] = {}
        self.tenant_packs: dict[tuple[UUID, str, str], CapabilityPackManifest] = {}
        self.agents: dict[tuple[UUID, str], AgentVersion] = {}
        self.skills: dict[str, dict[str, object]] = {}
        self.tools: dict[str, dict[str, object]] = {}
        self.policies: dict[str, dict[str, object]] = {}
        self.budgets: dict[str, dict[str, object]] = {}
        self.approvals: dict[UUID, ApprovalRequest | dict[str, object]] = {}
        self.evidence: dict[UUID, Evidence | dict[str, object]] = {}
        self.audits: list[AuditEvent] = []
        self.proposals: dict[UUID, ImprovementProposal] = {}
        self.candidates: dict[UUID, CandidateVersion] = {}
        self.deployments: dict[UUID, Deployment] = {}
        self.releases: dict[UUID, Release] = {}
        self.trials: dict[UUID, Trial] = {}
        self.idempotency: dict[tuple[UUID, str], UUID] = {}

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

    async def add_capability_pack(self, tenant_id: UUID, manifest: CapabilityPackManifest) -> None:
        self.tenant_packs[(tenant_id, manifest.pack_id, manifest.version)] = manifest
        for goal_type in manifest.goal_types:
            self.tenant_goal_types[(tenant_id, goal_type.goal_type)] = goal_type

    async def list_capability_packs(self, tenant_id: UUID) -> tuple[CapabilityPackManifest, ...]:
        tenant_items = tuple(
            item
            for (item_tenant, _, _), item in self.tenant_packs.items()
            if item_tenant == tenant_id
        )
        return tenant_items or tuple(self.packs.values())

    async def get_goal_type(self, tenant_id: UUID, goal_type: str) -> GoalTypeManifest:
        tenant_item = self.tenant_goal_types.get((tenant_id, goal_type))
        if tenant_item is not None:
            return tenant_item
        try:
            return self.goal_types[goal_type]
        except KeyError as exc:
            raise RecordNotFound(f"goal type {goal_type} was not found") from exc

    async def add_agent(self, name: str, version: AgentVersion) -> None:
        self.register_agent(name, version)

    async def list_agents(self, tenant_id: UUID) -> tuple[tuple[str, AgentVersion], ...]:
        return tuple(
            (name, version)
            for (item_tenant, name), version in self.agents.items()
            if item_tenant == tenant_id
        )

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

    async def add_skill(
        self, tenant_id: UUID, asset_id: str, definition: dict[str, object]
    ) -> dict[str, object]:
        return self._add_config(self.skills, tenant_id, asset_id, definition)

    async def list_skills(self, tenant_id: UUID) -> tuple[dict[str, object], ...]:
        return self._list_config(self.skills, tenant_id)

    async def add_tool(
        self, tenant_id: UUID, asset_id: str, definition: dict[str, object]
    ) -> dict[str, object]:
        return self._add_config(self.tools, tenant_id, asset_id, definition)

    async def list_tools(self, tenant_id: UUID) -> tuple[dict[str, object], ...]:
        return self._list_config(self.tools, tenant_id)

    async def add_policy(
        self, tenant_id: UUID, asset_id: str, definition: dict[str, object]
    ) -> dict[str, object]:
        return self._add_config(self.policies, tenant_id, asset_id, definition)

    async def list_policies(self, tenant_id: UUID) -> tuple[dict[str, object], ...]:
        return self._list_config(self.policies, tenant_id)

    async def add_budget(
        self, tenant_id: UUID, asset_id: str, definition: dict[str, object]
    ) -> dict[str, object]:
        return self._add_config(self.budgets, tenant_id, asset_id, definition)

    async def list_budgets(self, tenant_id: UUID) -> tuple[dict[str, object], ...]:
        return self._list_config(self.budgets, tenant_id)

    @staticmethod
    def _add_config(
        collection: dict[str, dict[str, object]],
        tenant_id: UUID,
        asset_id: str,
        definition: dict[str, object],
    ) -> dict[str, object]:
        value: dict[str, object] = {
            "asset_id": asset_id,
            "tenant_id": str(tenant_id),
            "version": str(definition.get("version", "1")),
            "definition": definition,
        }
        collection[f"{tenant_id}:{asset_id}"] = value
        return value

    @staticmethod
    def _list_config(
        collection: dict[str, dict[str, object]], tenant_id: UUID
    ) -> tuple[dict[str, object], ...]:
        return tuple(item for item in collection.values() if item["tenant_id"] == str(tenant_id))

    async def list_audit_events(self, tenant_id: UUID) -> tuple[AuditEvent, ...]:
        return tuple(item for item in self.audits if item.tenant_id == tenant_id)

    async def list_approvals(
        self, tenant_id: UUID
    ) -> tuple[ApprovalRequest | dict[str, object], ...]:
        return tuple(
            item
            for item in self.approvals.values()
            if (
                item.tenant_id == tenant_id
                if isinstance(item, ApprovalRequest)
                else item.get("tenant_id") == str(tenant_id)
            )
        )

    async def get_approval(
        self, tenant_id: UUID, approval_id: UUID
    ) -> ApprovalRequest | dict[str, object]:
        try:
            item = self.approvals[approval_id]
        except KeyError as exc:
            raise RecordNotFound("approval was not found") from exc
        actual_tenant = (
            item.tenant_id
            if isinstance(item, ApprovalRequest)
            else UUID(str(item.get("tenant_id")))
        )
        if actual_tenant != tenant_id:
            raise RecordNotFound("approval was not found")
        return item

    async def add_approval(self, approval: ApprovalRequest) -> None:
        self.approvals[approval.approval_id] = approval

    async def save_approval(self, approval: ApprovalRequest, expected_version: int) -> None:
        current = await self.get_approval(approval.tenant_id, approval.approval_id)
        if not isinstance(current, ApprovalRequest):
            raise TypeError("domain approval expected")
        if current.optimistic_version != expected_version:
            raise ConcurrencyConflict("approval optimistic version changed")
        self.approvals[approval.approval_id] = approval

    async def save_approval_record(
        self, tenant_id: UUID, approval_id: UUID, value: dict[str, object]
    ) -> None:
        current = await self.get_approval(tenant_id, approval_id)
        if not isinstance(current, dict):
            raise TypeError("legacy approval record expected")
        current.update(value)

    async def list_evidence(self, tenant_id: UUID) -> tuple[Evidence | dict[str, object], ...]:
        return tuple(
            item
            for item in self.evidence.values()
            if (
                item.tenant_id == tenant_id
                if isinstance(item, Evidence)
                else item.get("tenant_id") == str(tenant_id)
            )
        )

    async def add_trial(self, trial: Trial) -> None:
        self.trials[trial.trial_id] = trial

    async def list_trials(self, tenant_id: UUID) -> tuple[Trial, ...]:
        return tuple(item for item in self.trials.values() if item.tenant_id == tenant_id)

    async def add_proposal(self, proposal: ImprovementProposal) -> None:
        self.proposals[proposal.proposal_id] = proposal

    async def get_proposal(self, tenant_id: UUID, proposal_id: UUID) -> ImprovementProposal:
        try:
            proposal = self.proposals[proposal_id]
        except KeyError as exc:
            raise RecordNotFound("proposal was not found") from exc
        self._assert_tenant(tenant_id, proposal.tenant_id)
        return proposal

    async def list_proposals(self, tenant_id: UUID) -> tuple[ImprovementProposal, ...]:
        return tuple(item for item in self.proposals.values() if item.tenant_id == tenant_id)

    async def list_releases(self, tenant_id: UUID) -> tuple[Release, ...]:
        return tuple(item for item in self.releases.values() if item.tenant_id == tenant_id)

    async def get_idempotency(self, tenant_id: UUID, key: str) -> UUID | None:
        return self.idempotency.get((tenant_id, key))

    async def put_idempotency(self, tenant_id: UUID, key: str, external_id: UUID) -> None:
        self.idempotency[(tenant_id, key)] = external_id

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
