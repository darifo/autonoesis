"""Governed improvement proposal, candidate, release, and rollback objects."""

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from autonoesis_domain.transitions import (
    SYSTEM_ACTOR_ID,
    StateTransition,
    require_transition,
    transition_record,
)


class ImprovementTarget(StrEnum):
    AGENT_INSTRUCTION = "agent_instruction"
    SKILL = "skill"
    PROMPT_ASSET = "prompt_asset"
    MODEL_ROUTE = "model_route"


class CandidateStatus(StrEnum):
    DRAFT = "draft"
    EVALUATING = "evaluating"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"


class DeploymentStatus(StrEnum):
    SHADOW = "shadow"
    CANARY = "canary"
    STABLE = "stable"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


_CANDIDATE_TRANSITIONS: dict[CandidateStatus, frozenset[CandidateStatus]] = {
    CandidateStatus.DRAFT: frozenset({CandidateStatus.EVALUATING, CandidateStatus.REJECTED}),
    CandidateStatus.EVALUATING: frozenset(
        {CandidateStatus.AWAITING_APPROVAL, CandidateStatus.REJECTED}
    ),
    CandidateStatus.AWAITING_APPROVAL: frozenset(
        {CandidateStatus.APPROVED, CandidateStatus.REJECTED}
    ),
}

_DEPLOYMENT_TRANSITIONS: dict[DeploymentStatus, frozenset[DeploymentStatus]] = {
    DeploymentStatus.SHADOW: frozenset(
        {DeploymentStatus.CANARY, DeploymentStatus.FAILED, DeploymentStatus.ROLLED_BACK}
    ),
    DeploymentStatus.CANARY: frozenset(
        {DeploymentStatus.STABLE, DeploymentStatus.FAILED, DeploymentStatus.ROLLED_BACK}
    ),
    DeploymentStatus.STABLE: frozenset({DeploymentStatus.ROLLED_BACK}),
}


@dataclass(frozen=True, slots=True)
class ImprovementProposal:
    tenant_id: UUID
    target: ImprovementTarget
    target_version_id: UUID
    evidence_refs: tuple[str, ...]
    diagnosis: str
    proposed_change: str
    validation_suite_id: str
    rollback_plan: str
    proposer_id: str
    proposal_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if not self.evidence_refs:
            raise ValueError("improvement proposal requires evidence")
        if any(
            not item.strip()
            for item in (
                self.diagnosis,
                self.proposed_change,
                self.validation_suite_id,
                self.rollback_plan,
                self.proposer_id,
            )
        ):
            raise ValueError("improvement proposal fields must not be empty")


@dataclass(frozen=True, slots=True)
class CandidateVersion:
    tenant_id: UUID
    proposal_id: UUID
    baseline_version_id: UUID
    artifact_ref: str
    generator_id: str
    candidate_id: UUID = field(default_factory=uuid4)
    status: CandidateStatus = CandidateStatus.DRAFT
    optimistic_version: int = 1
    transitions: tuple[StateTransition, ...] = ()
    grader_principal_id: str | None = None
    approver_principal_id: str | None = None

    def __post_init__(self) -> None:
        if not self.artifact_ref.strip() or not self.generator_id.strip():
            raise ValueError("candidate artifact and generator are required")
        if self.optimistic_version < 1:
            raise ValueError("candidate optimistic version must be positive")

    def transition_to(
        self,
        target: CandidateStatus,
        *,
        actor_id: UUID = SYSTEM_ACTOR_ID,
        reason: str = "system transition",
        occurred_at: datetime | None = None,
    ) -> "CandidateVersion":
        require_transition(self.status, target, _CANDIDATE_TRANSITIONS)
        transition = transition_record(
            self.status,
            target,
            actor_id=actor_id,
            reason=reason,
            occurred_at=occurred_at,
        )
        return replace(
            self,
            status=target,
            optimistic_version=self.optimistic_version + 1,
            transitions=(*self.transitions, transition),
        )

    def begin_deployment(self, *, actor_id: UUID, reason: str) -> "Deployment":
        if self.status is not CandidateStatus.APPROVED:
            raise ValueError("only an approved candidate can begin deployment")
        return Deployment(
            tenant_id=self.tenant_id,
            candidate_id=self.candidate_id,
            status=DeploymentStatus.SHADOW,
            transitions=(
                StateTransition(
                    from_status="approved",
                    to_status=DeploymentStatus.SHADOW.value,
                    occurred_at=datetime.now(UTC),
                    reason=reason,
                    actor_id=actor_id,
                ),
            ),
        )

    def record_evaluation(
        self, target: CandidateStatus, *, grader_principal_id: UUID
    ) -> "CandidateVersion":
        if str(grader_principal_id) == self.generator_id:
            raise PermissionError("candidate generator cannot grade its own candidate")
        return replace(
            self.transition_to(target, actor_id=grader_principal_id, reason="evaluation recorded"),
            grader_principal_id=str(grader_principal_id),
        )

    def record_approval(
        self, target: CandidateStatus, *, approver_principal_id: UUID
    ) -> "CandidateVersion":
        if str(approver_principal_id) in {self.generator_id, self.grader_principal_id}:
            raise PermissionError("candidate approval requires an independent principal")
        return replace(
            self.transition_to(target, actor_id=approver_principal_id, reason="approval recorded"),
            approver_principal_id=str(approver_principal_id),
        )


@dataclass(frozen=True, slots=True)
class Deployment:
    tenant_id: UUID
    candidate_id: UUID
    status: DeploymentStatus
    deployment_id: UUID = field(default_factory=uuid4)
    optimistic_version: int = 1
    transitions: tuple[StateTransition, ...] = ()

    def __post_init__(self) -> None:
        if self.optimistic_version < 1:
            raise ValueError("deployment optimistic version must be positive")

    def transition_to(
        self,
        target: DeploymentStatus,
        *,
        actor_id: UUID,
        reason: str,
        occurred_at: datetime | None = None,
    ) -> "Deployment":
        require_transition(self.status, target, _DEPLOYMENT_TRANSITIONS)
        transition = transition_record(
            self.status,
            target,
            actor_id=actor_id,
            reason=reason,
            occurred_at=occurred_at,
        )
        return replace(
            self,
            status=target,
            optimistic_version=self.optimistic_version + 1,
            transitions=(*self.transitions, transition),
        )


@dataclass(frozen=True, slots=True)
class Release:
    tenant_id: UUID
    candidate_id: UUID
    deployment_id: UUID
    stable_version_id: UUID
    previous_stable_version_id: UUID
    approved_by: UUID
    release_id: UUID = field(default_factory=uuid4)

    @classmethod
    def from_stable_deployment(
        cls,
        deployment: Deployment,
        *,
        stable_version_id: UUID,
        previous_stable_version_id: UUID,
        approved_by: UUID,
    ) -> "Release":
        if deployment.status is not DeploymentStatus.STABLE:
            raise ValueError("release requires a stable deployment")
        return cls(
            tenant_id=deployment.tenant_id,
            candidate_id=deployment.candidate_id,
            deployment_id=deployment.deployment_id,
            stable_version_id=stable_version_id,
            previous_stable_version_id=previous_stable_version_id,
            approved_by=approved_by,
        )
