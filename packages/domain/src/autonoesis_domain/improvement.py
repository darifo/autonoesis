"""Governed improvement proposal, candidate, release, and rollback objects."""

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from math import isfinite
from typing import Any
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


# ADR-0011: the evolution pipeline must never touch governance roots. These
# targets stay outside Improvable state even if a future enum widens the
# allowed set, so the prohibition survives schema and API drift.
FORBIDDEN_IMPROVEMENT_TARGETS: frozenset[str] = frozenset(
    {
        "identity",
        "delegation",
        "tenant_isolation",
        "policy_root",
        "audit_retention",
        "kill_switch",
        "production_code",
        "infrastructure",
    }
)


def require_improvement_target_allowed(raw_target: str) -> None:
    """Reject forbidden improvement targets before any enum coercion."""
    if raw_target.strip().lower() in FORBIDDEN_IMPROVEMENT_TARGETS:
        raise PermissionError(f"improvement target is forbidden: {raw_target.strip().lower()}")


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


class GuardrailOperator(StrEnum):
    LT = "lt"
    GT = "gt"
    LTE = "lte"
    GTE = "gte"


# Decisions a persisted evaluation record may carry. Mirrors the confidence
# gate outcomes without coupling the domain package to the evaluation package.
CANDIDATE_EVALUATION_DECISIONS: frozenset[str] = frozenset(
    {"met", "not_met", "insufficient_sample"}
)


@dataclass(frozen=True, slots=True)
class CandidateEvaluation:
    """Immutable evidence record binding a Candidate to its complete evaluation."""

    tenant_id: UUID
    candidate_id: UUID
    decision: str
    trial_ids: tuple[UUID, ...]
    assessment: dict[str, Any]
    grader_principal_id: str
    evaluation_id: UUID = field(default_factory=uuid4)
    decided_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.decision not in CANDIDATE_EVALUATION_DECISIONS:
            raise ValueError("candidate evaluation decision is not a known gate outcome")
        if not self.trial_ids:
            raise ValueError("candidate evaluation must reference at least one Trial")
        if not self.assessment:
            raise ValueError("candidate evaluation requires the assessment payload")
        if not self.grader_principal_id.strip():
            raise ValueError("candidate evaluation requires the grading principal")


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
    artifact_digest: str
    suite_id: str
    suite_version: str
    generator_id: str
    candidate_id: UUID = field(default_factory=uuid4)
    status: CandidateStatus = CandidateStatus.DRAFT
    optimistic_version: int = 1
    transitions: tuple[StateTransition, ...] = ()
    grader_principal_id: str | None = None
    approver_principal_id: str | None = None
    approval_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.artifact_ref.strip() or not self.generator_id.strip():
            raise ValueError("candidate artifact and generator are required")
        if len(self.artifact_digest) != 64 or any(
            char not in "0123456789abcdef" for char in self.artifact_digest
        ):
            raise ValueError("candidate artifact digest must be a lowercase sha256 hex digest")
        if not self.suite_id.strip() or not self.suite_version.strip():
            raise ValueError("candidate suite id and version are required")
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
        self,
        target: CandidateStatus,
        *,
        approver_principal_id: UUID,
        reason: str,
    ) -> "CandidateVersion":
        if not reason.strip():
            raise ValueError("candidate approval requires a recorded rationale")
        if str(approver_principal_id) in {self.generator_id, self.grader_principal_id}:
            raise PermissionError("candidate approval requires an independent principal")
        return replace(
            self.transition_to(
                target,
                actor_id=approver_principal_id,
                reason=f"approval recorded: {reason.strip()}",
            ),
            approver_principal_id=str(approver_principal_id),
            approval_reason=reason.strip(),
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

    def entered_at(self, status: DeploymentStatus) -> datetime | None:
        for transition in self.transitions:
            if transition.to_status == status.value:
                return transition.occurred_at
        return None


@dataclass(frozen=True, slots=True)
class DeploymentObservation:
    """A per-deployment, per-stage, per-metric observation counter.

    Isolated by tenant, deployment, stage, and metric (P1-05). Breach count
    tracks consecutive breaches of the governing rule, resetting on a pass.
    """

    tenant_id: UUID
    deployment_id: UUID
    stage: DeploymentStatus
    metric: str
    sample_count: int = 0
    breach_count: int = 0
    last_value: float | None = None
    first_sample_at: datetime | None = None
    last_sample_at: datetime | None = None
    observation_id: UUID = field(default_factory=uuid4)
    optimistic_version: int = 1

    def __post_init__(self) -> None:
        if not self.metric.strip():
            raise ValueError("observation metric is required")
        if self.sample_count < 0 or self.breach_count < 0:
            raise ValueError("observation counts cannot be negative")
        if self.breach_count > self.sample_count:
            raise ValueError("breach count cannot exceed sample count")


@dataclass(frozen=True, slots=True)
class ShadowMeasurements:
    """Comparable measurements emitted by one side of a Shadow pair."""

    outcome_score: float
    cost_microunits: int
    latency_ms: float
    security_violations: int = 0
    human_corrections: int = 0
    external_write_attempts: int = 0

    def __post_init__(self) -> None:
        if not isfinite(self.outcome_score) or not 0 <= self.outcome_score <= 1:
            raise ValueError("shadow outcome score must be finite and between zero and one")
        if not isfinite(self.latency_ms) or self.latency_ms < 0:
            raise ValueError("shadow latency must be finite and non-negative")
        for value, label in (
            (self.cost_microunits, "cost"),
            (self.security_violations, "security violations"),
            (self.human_corrections, "human corrections"),
            (self.external_write_attempts, "external write attempts"),
        ):
            if value < 0:
                raise ValueError(f"shadow {label} cannot be negative")


@dataclass(frozen=True, slots=True)
class ShadowComparison:
    """Immutable paired evidence from Stable and Candidate execution."""

    tenant_id: UUID
    deployment_id: UUID
    request_ref: str
    stable_version_id: UUID
    candidate_version_id: UUID
    stable: ShadowMeasurements
    candidate: ShadowMeasurements
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    comparison_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if not self.request_ref.strip():
            raise ValueError("shadow comparison request reference is required")
        if self.observed_at.tzinfo is None:
            raise ValueError("shadow comparison timestamp must be timezone-aware")


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
