"""Deterministic in-memory platform adapters for tests and offline development."""

from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID, uuid4

from autonoesis_application import (
    AuditEvent,
    ConcurrencyConflict,
    EvidenceCaptureSaga,
    EvidenceCaptureStatus,
    EvidenceDeletionRecord,
    RecordNotFound,
    TenantBoundaryViolation,
)
from autonoesis_capability import CapabilityPackManifest, GoalTypeManifest
from autonoesis_domain import (
    Action,
    ActionAttempt,
    AgentVersion,
    ApprovalRequest,
    BudgetAmount,
    CandidateVersion,
    ContextSnapshot,
    Deployment,
    Evidence,
    GoalContract,
    ImprovementProposal,
    Outcome,
    Plan,
    Release,
    Run,
    Task,
    Trial,
)
from autonoesis_runtime import ToolReceipt


class InMemoryPlatformStore:
    def __init__(self) -> None:
        self.goals: dict[UUID, GoalContract] = {}
        self.runs: dict[UUID, Run] = {}
        self.context_snapshots: dict[UUID, ContextSnapshot] = {}
        self.plans: dict[UUID, Plan] = {}
        self.tasks: dict[UUID, Task] = {}
        self.actions: dict[UUID, Action] = {}
        self.action_attempts: dict[UUID, ActionAttempt] = {}
        self.goal_types: dict[str, GoalTypeManifest] = {}
        self.packs: dict[str, CapabilityPackManifest] = {}
        self.tenant_goal_types: dict[tuple[UUID, str], GoalTypeManifest] = {}
        self.tenant_packs: dict[tuple[UUID, str, str], CapabilityPackManifest] = {}
        self.agents: dict[tuple[UUID, str], AgentVersion] = {}
        self.skills: dict[str, dict[str, object]] = {}
        self.tools: dict[str, dict[str, object]] = {}
        self.policies: dict[str, dict[str, object]] = {}
        self.budgets: dict[str, dict[str, object]] = {}
        self.approvals: dict[UUID, ApprovalRequest] = {}
        self.evidence: dict[UUID, Evidence] = {}
        self.evidence_capture_sagas: dict[UUID, EvidenceCaptureSaga] = {}
        self.evidence_deletions: dict[UUID, EvidenceDeletionRecord] = {}
        self.outcomes: dict[UUID, Outcome] = {}
        self.audits: list[AuditEvent] = []
        self.proposals: dict[UUID, ImprovementProposal] = {}
        self.candidates: dict[UUID, CandidateVersion] = {}
        self.deployments: dict[UUID, Deployment] = {}
        self.releases: dict[UUID, Release] = {}
        self.trials: dict[UUID, Trial] = {}
        self.idempotency: dict[tuple[UUID, str], UUID] = {}
        self.idempotency_digests: dict[tuple[UUID, str], str] = {}

    @property
    def repository(self) -> "InMemoryPlatformStore":
        return self

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        snapshot = deepcopy(self.__dict__)
        try:
            yield
        except BaseException:
            self.__dict__.clear()
            self.__dict__.update(snapshot)
            raise

    async def record_audit(self, audit: AuditEvent) -> None:
        previous = next(
            (item for item in reversed(self.audits) if item.tenant_id == audit.tenant_id),
            None,
        )
        self.audits.append(
            audit.chained(
                (previous.sequence or 0) + 1 if previous is not None else 1,
                previous.event_digest
                if previous is not None and previous.event_digest
                else "0" * 64,
                datetime.now(UTC),
            )
        )

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
        await self.record_audit(audit)

    async def get_goal(self, tenant_id: UUID, goal_id: UUID) -> GoalContract:
        try:
            goal = self.goals[goal_id]
        except KeyError as exc:
            raise RecordNotFound(f"goal {goal_id} was not found") from exc
        self._assert_tenant(tenant_id, goal.tenant_id)
        return goal

    async def list_goals(self, tenant_id: UUID) -> tuple[GoalContract, ...]:
        return tuple(goal for goal in self.goals.values() if goal.tenant_id == tenant_id)

    async def save_goal(self, goal: GoalContract, expected_version: int, audit: AuditEvent) -> None:
        current = await self.get_goal(goal.tenant_id, goal.goal_id)
        if current.version != expected_version:
            raise ConcurrencyConflict("goal optimistic version changed")
        self.goals[goal.goal_id] = goal
        await self.record_audit(audit)

    async def add_run(self, run: Run, audit: AuditEvent) -> None:
        self.runs[run.run_id] = run
        await self.record_audit(audit)

    async def get_run(self, tenant_id: UUID, run_id: UUID) -> Run:
        try:
            run = self.runs[run_id]
        except KeyError as exc:
            raise RecordNotFound(f"run {run_id} was not found") from exc
        self._assert_tenant(tenant_id, run.tenant_id)
        return run

    async def save_run(
        self, run: Run, expected_version: int, audit: AuditEvent | None = None
    ) -> None:
        current = await self.get_run(run.tenant_id, run.run_id)
        if current.optimistic_version != expected_version:
            raise ConcurrencyConflict("run optimistic version changed")
        self.runs[run.run_id] = run
        if audit is not None:
            await self.record_audit(audit)

    async def list_runs(self, tenant_id: UUID, goal_id: UUID | None = None) -> tuple[Run, ...]:
        return tuple(
            run
            for run in self.runs.values()
            if run.tenant_id == tenant_id and (goal_id is None or run.goal_id == goal_id)
        )

    async def add_context_snapshot(self, snapshot: ContextSnapshot) -> None:
        if any(
            item.tenant_id == snapshot.tenant_id and item.run_id == snapshot.run_id
            for item in self.context_snapshots.values()
        ):
            raise ConcurrencyConflict("run context snapshot already exists")
        self.context_snapshots[snapshot.snapshot_id] = snapshot

    async def get_context_snapshot(self, tenant_id: UUID, run_id: UUID) -> ContextSnapshot:
        for item in self.context_snapshots.values():
            if item.tenant_id == tenant_id and item.run_id == run_id:
                return item
        raise RecordNotFound(f"context for run {run_id} was not found")

    async def add_plan(self, plan: Plan) -> None:
        self.plans[plan.plan_id] = plan
        for task in plan.tasks:
            self.tasks[task.task_id] = task

    async def get_plan(self, tenant_id: UUID, plan_id: UUID) -> Plan:
        try:
            plan = self.plans[plan_id]
        except KeyError as exc:
            raise RecordNotFound(f"plan {plan_id} was not found") from exc
        self._assert_tenant(tenant_id, plan.tenant_id)
        return Plan(
            plan.tenant_id,
            plan.goal_id,
            plan.run_id,
            tuple(self.tasks[task.task_id] for task in plan.tasks),
            plan.version,
            plan.plan_id,
        )

    async def get_task(self, tenant_id: UUID, task_id: UUID) -> Task:
        try:
            task = self.tasks[task_id]
        except KeyError as exc:
            raise RecordNotFound(f"task {task_id} was not found") from exc
        self._assert_tenant(tenant_id, task.tenant_id)
        return task

    async def list_tasks(self, tenant_id: UUID, run_id: UUID) -> tuple[Task, ...]:
        return tuple(
            task
            for task in self.tasks.values()
            if task.tenant_id == tenant_id and task.run_id == run_id
        )

    async def save_task(self, task: Task, expected_version: int) -> None:
        current = await self.get_task(task.tenant_id, task.task_id)
        if current.optimistic_version != expected_version:
            raise ConcurrencyConflict("task optimistic version changed")
        self.tasks[task.task_id] = task

    async def add_action(self, action: Action) -> None:
        if any(
            item.tenant_id == action.tenant_id and item.idempotency_key == action.idempotency_key
            for item in self.actions.values()
        ):
            raise ConcurrencyConflict("action idempotency key already exists")
        self.actions[action.action_id] = action

    async def get_action(self, tenant_id: UUID, action_id: UUID) -> Action:
        try:
            action = self.actions[action_id]
        except KeyError as exc:
            raise RecordNotFound(f"action {action_id} was not found") from exc
        self._assert_tenant(tenant_id, action.tenant_id)
        return action

    async def save_action(self, action: Action, expected_version: int) -> None:
        current = await self.get_action(action.tenant_id, action.action_id)
        if current.optimistic_version != expected_version:
            raise ConcurrencyConflict("action optimistic version changed")
        self.actions[action.action_id] = action

    async def list_actions(self, tenant_id: UUID, run_id: UUID) -> tuple[Action, ...]:
        return tuple(
            action
            for action in self.actions.values()
            if action.tenant_id == tenant_id and action.run_id == run_id
        )

    async def add_action_attempt(self, attempt: ActionAttempt) -> None:
        if any(
            item.tenant_id == attempt.tenant_id
            and (
                (item.invocation_id == attempt.invocation_id and item.status is attempt.status)
                or item.idempotency_key == attempt.idempotency_key
            )
            for item in self.action_attempts.values()
        ):
            raise ConcurrencyConflict("action attempt already recorded")
        self.action_attempts[attempt.attempt_id] = attempt

    async def list_action_attempts(
        self, tenant_id: UUID, action_id: UUID
    ) -> tuple[ActionAttempt, ...]:
        return tuple(
            item
            for item in self.action_attempts.values()
            if item.tenant_id == tenant_id and item.action_id == action_id
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

    async def list_approvals(self, tenant_id: UUID) -> tuple[ApprovalRequest, ...]:
        return tuple(item for item in self.approvals.values() if item.tenant_id == tenant_id)

    async def get_approval(self, tenant_id: UUID, approval_id: UUID) -> ApprovalRequest:
        try:
            item = self.approvals[approval_id]
        except KeyError as exc:
            raise RecordNotFound("approval was not found") from exc
        if item.tenant_id != tenant_id:
            raise RecordNotFound("approval was not found")
        return item

    async def add_approval(self, approval: ApprovalRequest) -> None:
        self.approvals[approval.approval_id] = approval

    async def save_approval(self, approval: ApprovalRequest, expected_version: int) -> None:
        current = await self.get_approval(approval.tenant_id, approval.approval_id)
        if current.optimistic_version != expected_version:
            raise ConcurrencyConflict("approval optimistic version changed")
        self.approvals[approval.approval_id] = approval

    async def add_evidence(self, item: Evidence) -> None:
        action = await self.get_action(item.tenant_id, item.action_id)
        if action.run_id != item.run_id:
            raise ValueError("evidence must bind the authoritative Action and Run")
        self.evidence[item.evidence_id] = item

    async def get_evidence(self, tenant_id: UUID, evidence_id: UUID) -> Evidence:
        try:
            item = self.evidence[evidence_id]
        except KeyError as exc:
            raise RecordNotFound(f"evidence {evidence_id} was not found") from exc
        self._assert_tenant(tenant_id, item.tenant_id)
        return item

    async def list_evidence(self, tenant_id: UUID) -> tuple[Evidence, ...]:
        return tuple(item for item in self.evidence.values() if item.tenant_id == tenant_id)

    async def start_evidence_capture(self, saga: EvidenceCaptureSaga) -> None:
        existing = self.evidence_capture_sagas.get(saga.evidence_id)
        if existing is not None and existing != saga:
            raise ConcurrencyConflict(
                "Evidence capture id was reused with different immutable content"
            )
        if existing is None:
            self.evidence_capture_sagas[saga.evidence_id] = saga

    async def get_evidence_capture(self, tenant_id: UUID, evidence_id: UUID) -> EvidenceCaptureSaga:
        try:
            item = self.evidence_capture_sagas[evidence_id]
        except KeyError as exc:
            raise RecordNotFound("Evidence capture Saga was not found") from exc
        self._assert_tenant(tenant_id, item.tenant_id)
        return item

    async def complete_evidence_capture(self, tenant_id: UUID, evidence_id: UUID) -> None:
        item = await self.get_evidence_capture(tenant_id, evidence_id)
        if item.status not in {
            EvidenceCaptureStatus.PENDING,
            EvidenceCaptureStatus.COMMITTED,
        }:
            raise ConcurrencyConflict("Evidence capture Saga is not pending")
        from dataclasses import replace

        self.evidence_capture_sagas[evidence_id] = replace(
            item, status=EvidenceCaptureStatus.COMMITTED
        )

    async def record_evidence_deletion(self, record: EvidenceDeletionRecord) -> None:
        self.evidence_deletions[record.evidence_id] = record

    async def get_evidence_deletion(
        self, tenant_id: UUID, evidence_id: UUID
    ) -> EvidenceDeletionRecord:
        try:
            item = self.evidence_deletions[evidence_id]
        except KeyError as exc:
            raise RecordNotFound("Evidence deletion record was not found") from exc
        self._assert_tenant(tenant_id, item.tenant_id)
        return item

    async def add_outcome(self, item: Outcome) -> None:
        for submitted in item.evidence:
            persisted = await self.get_evidence(item.tenant_id, submitted.evidence_id)
            if persisted != submitted:
                raise ValueError(
                    "outcome evidence must exactly match the authoritative persisted record"
                )
        self.outcomes[item.outcome_id] = item

    async def get_outcome(self, tenant_id: UUID, outcome_id: UUID) -> Outcome:
        try:
            item = self.outcomes[outcome_id]
        except KeyError as exc:
            raise RecordNotFound(f"outcome {outcome_id} was not found") from exc
        self._assert_tenant(tenant_id, item.tenant_id)
        return item

    async def list_outcomes(self, tenant_id: UUID, run_id: UUID) -> tuple[Outcome, ...]:
        return tuple(
            item
            for item in self.outcomes.values()
            if item.tenant_id == tenant_id and item.run_id == run_id
        )

    async def record_budget_entry(
        self,
        tenant_id: UUID,
        run_id: UUID,
        category: str,
        amount: BudgetAmount,
        reference: str,
    ) -> UUID:
        _ = (tenant_id, run_id, category, amount, reference)
        return uuid4()

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

    async def get_idempotency(
        self, tenant_id: UUID, key: str, request_digest: str | None = None
    ) -> UUID | None:
        if (
            request_digest is not None
            and (accepted := self.idempotency_digests.get((tenant_id, key))) is not None
            and accepted != request_digest
        ):
            raise ConcurrencyConflict("idempotency key was reused with a different request")
        return self.idempotency.get((tenant_id, key))

    async def put_idempotency(
        self,
        tenant_id: UUID,
        key: str,
        external_id: UUID,
        request_digest: str | None = None,
    ) -> None:
        current = self.idempotency.get((tenant_id, key))
        if current is not None and (
            current != external_id
            or (
                request_digest is not None
                and self.idempotency_digests.get((tenant_id, key)) != request_digest
            )
        ):
            raise ConcurrencyConflict("idempotency key is already bound to a different result")
        self.idempotency[(tenant_id, key)] = external_id
        self.idempotency_digests[(tenant_id, key)] = request_digest or "0" * 64

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
