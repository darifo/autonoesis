"""Governed improvement proposal, candidate, release, and rollback objects."""

from dataclasses import dataclass, field, replace
from enum import StrEnum
from uuid import UUID, uuid4

from autonoesis_domain.transitions import require_transition


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
    STABLE = "stable"
    ROLLED_BACK = "rolled_back"


_CANDIDATE_TRANSITIONS: dict[CandidateStatus, frozenset[CandidateStatus]] = {
    CandidateStatus.DRAFT: frozenset({CandidateStatus.EVALUATING, CandidateStatus.REJECTED}),
    CandidateStatus.EVALUATING: frozenset(
        {CandidateStatus.AWAITING_APPROVAL, CandidateStatus.REJECTED}
    ),
    CandidateStatus.AWAITING_APPROVAL: frozenset(
        {CandidateStatus.APPROVED, CandidateStatus.REJECTED}
    ),
    CandidateStatus.APPROVED: frozenset({CandidateStatus.STABLE}),
    CandidateStatus.STABLE: frozenset({CandidateStatus.ROLLED_BACK}),
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

    def transition_to(self, target: CandidateStatus) -> "CandidateVersion":
        require_transition(self.status, target, _CANDIDATE_TRANSITIONS)
        return replace(self, status=target)


@dataclass(frozen=True, slots=True)
class Release:
    tenant_id: UUID
    candidate_id: UUID
    stable_version_id: UUID
    previous_stable_version_id: UUID
    approved_by: UUID
    release_id: UUID = field(default_factory=uuid4)
