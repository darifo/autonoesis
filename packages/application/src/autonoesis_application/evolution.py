"""Governed candidate evaluation, approval, promotion, and rollback services."""

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from autonoesis_domain import (
    CandidateEvaluation,
    CandidateStatus,
    CandidateVersion,
    Deployment,
    DeploymentStatus,
    ImprovementProposal,
    ImprovementTarget,
    Release,
    Trial,
    require_improvement_target_allowed,
)
from autonoesis_evaluation import (
    RepeatedTrialPolicy,
    TrialConfidenceAssessment,
    TrialConfidenceGate,
)

from autonoesis_application.platform import IdentityContext, RecordNotFound


class EvolutionRepository(Protocol):
    async def add_proposal(self, proposal: ImprovementProposal) -> None: ...

    async def get_proposal(self, tenant_id: UUID, proposal_id: UUID) -> ImprovementProposal: ...

    async def add_candidate(self, candidate: CandidateVersion) -> None: ...

    async def get_candidate(self, tenant_id: UUID, candidate_id: UUID) -> CandidateVersion: ...

    async def save_candidate(self, candidate: CandidateVersion) -> None: ...

    async def add_deployment(self, deployment: Deployment) -> None: ...

    async def get_deployment(self, tenant_id: UUID, deployment_id: UUID) -> Deployment: ...

    async def save_deployment(self, deployment: Deployment) -> None: ...

    async def add_release(self, release: Release) -> None: ...

    async def get_active_release(self, tenant_id: UUID, candidate_id: UUID) -> Release: ...

    async def add_trial(self, trial: Trial) -> None: ...

    async def list_trials_for_candidate(
        self, tenant_id: UUID, candidate_id: UUID
    ) -> tuple[Trial, ...]: ...

    async def add_evaluation_record(self, record: CandidateEvaluation) -> None: ...

    async def list_evaluation_records(
        self, tenant_id: UUID, candidate_id: UUID
    ) -> tuple[CandidateEvaluation, ...]: ...


class ImprovementTargetPolicy(Protocol):
    """External policy decision point consulted before any improvement proposal."""

    async def assert_target_allowed(self, raw_target: str) -> None: ...


@dataclass(frozen=True, slots=True)
class ProposeImprovement:
    """Raw proposal input; the use case owns validation before enum coercion."""

    target: str
    target_version_id: UUID
    evidence_refs: tuple[str, ...]
    diagnosis: str
    proposed_change: str
    validation_suite_id: str
    rollback_plan: str


@dataclass(frozen=True, slots=True)
class RegisterCandidate:
    proposal_id: UUID
    baseline_version_id: UUID
    artifact_ref: str
    artifact_digest: str
    suite_id: str
    suite_version: str


def assessment_payload(assessment: TrialConfidenceAssessment) -> dict[str, Any]:
    return {
        "decision": assessment.decision.value,
        "passed_trials": assessment.passed_trials,
        "failed_trials": assessment.failed_trials,
        "invalid_trials": assessment.invalid_trials,
        "valid_trials": assessment.valid_trials,
        "pass_rate": assessment.pass_rate,
        "lower_bound": assessment.lower_bound,
        "upper_bound": assessment.upper_bound,
        "confidence_level": assessment.policy.confidence_level,
        "pass_threshold": assessment.policy.pass_threshold,
        "min_valid_trials": assessment.policy.min_valid_trials,
        "rationale": assessment.rationale,
    }


class CandidateLifecycleService:
    def __init__(
        self,
        repository: EvolutionRepository,
        improvement_policy: ImprovementTargetPolicy | None = None,
    ) -> None:
        self._repository = repository
        self._improvement_policy = improvement_policy

    async def _forbid_disallowed_target(self, raw_target: str) -> ImprovementTarget:
        require_improvement_target_allowed(raw_target)
        if self._improvement_policy is not None:
            await self._improvement_policy.assert_target_allowed(raw_target)
        return ImprovementTarget(raw_target)

    async def propose_improvement(
        self,
        identity: IdentityContext,
        command: ProposeImprovement,
    ) -> ImprovementProposal:
        target = await self._forbid_disallowed_target(command.target)
        proposal = ImprovementProposal(
            tenant_id=identity.tenant_id,
            target=target,
            target_version_id=command.target_version_id,
            evidence_refs=command.evidence_refs,
            diagnosis=command.diagnosis,
            proposed_change=command.proposed_change,
            validation_suite_id=command.validation_suite_id,
            rollback_plan=command.rollback_plan,
            proposer_id=str(identity.principal_id),
        )
        await self._repository.add_proposal(proposal)
        return proposal

    async def register_candidate(
        self,
        identity: IdentityContext,
        command: RegisterCandidate,
    ) -> CandidateVersion:
        proposal = await self._repository.get_proposal(identity.tenant_id, command.proposal_id)
        await self._forbid_disallowed_target(proposal.target.value)
        if command.suite_id != proposal.validation_suite_id:
            raise ValueError(
                "candidate must be graded against the proposal's fixed validation suite: "
                f"{command.suite_id} != {proposal.validation_suite_id}"
            )
        candidate = CandidateVersion(
            tenant_id=identity.tenant_id,
            proposal_id=command.proposal_id,
            baseline_version_id=command.baseline_version_id,
            artifact_ref=command.artifact_ref,
            artifact_digest=command.artifact_digest,
            suite_id=command.suite_id,
            suite_version=command.suite_version,
            generator_id=str(identity.principal_id),
        )
        await self._repository.add_candidate(candidate)
        return candidate

    async def submit_for_evaluation(self, tenant_id: UUID, candidate_id: UUID) -> CandidateVersion:
        candidate = await self._repository.get_candidate(tenant_id, candidate_id)
        candidate = candidate.transition_to(CandidateStatus.EVALUATING)
        await self._repository.save_candidate(candidate)
        return candidate

    async def complete_evaluation(
        self,
        identity: IdentityContext,
        candidate_id: UUID,
        policy: RepeatedTrialPolicy,
    ) -> tuple[CandidateVersion, CandidateEvaluation]:
        """Gate promotion on persisted Trials; caller-supplied outcomes are not accepted."""
        candidate = await self._repository.get_candidate(identity.tenant_id, candidate_id)
        trials = await self._repository.list_trials_for_candidate(identity.tenant_id, candidate_id)
        for trial in trials:
            if trial.subject_version_id != candidate_id:
                raise ValueError(
                    "candidate evaluation trials must execute the candidate itself: "
                    f"trial {trial.trial_id} executed {trial.subject_version_id}"
                )
            if (trial.suite_id, trial.suite_version) != (
                candidate.suite_id,
                candidate.suite_version,
            ):
                raise ValueError(
                    "candidate evaluation trials must use the candidate's fixed suite: "
                    f"trial {trial.trial_id} used {trial.suite_id}@{trial.suite_version}"
                )
        assessment = TrialConfidenceGate(policy).assess(trials)
        record = CandidateEvaluation(
            tenant_id=identity.tenant_id,
            candidate_id=candidate_id,
            decision=assessment.decision.value,
            trial_ids=tuple(trial.trial_id for trial in trials),
            assessment=assessment_payload(assessment),
            grader_principal_id=str(identity.principal_id),
            decided_at=None,
        )
        await self._repository.add_evaluation_record(record)
        if assessment.met:
            target = CandidateStatus.AWAITING_APPROVAL
        elif assessment.policy.min_valid_trials > assessment.valid_trials:
            raise ValueError(f"candidate evaluation evidence is incomplete: {assessment.rationale}")
        else:
            target = CandidateStatus.REJECTED
        candidate = candidate.record_evaluation(target, grader_principal_id=identity.principal_id)
        await self._repository.save_candidate(candidate)
        return candidate, record

    async def decide(
        self,
        identity: IdentityContext,
        candidate_id: UUID,
        approved: bool,
        reason: str,
    ) -> CandidateVersion:
        candidate = await self._repository.get_candidate(identity.tenant_id, candidate_id)
        target = CandidateStatus.APPROVED if approved else CandidateStatus.REJECTED
        candidate = candidate.record_approval(
            target, approver_principal_id=identity.principal_id, reason=reason
        )
        await self._repository.save_candidate(candidate)
        return candidate

    async def begin_shadow(
        self,
        identity: IdentityContext,
        candidate_id: UUID,
    ) -> Deployment:
        candidate = await self._repository.get_candidate(identity.tenant_id, candidate_id)
        if str(identity.principal_id) in {
            candidate.generator_id,
            candidate.grader_principal_id,
            candidate.approver_principal_id,
        }:
            raise PermissionError("release execution requires an independent principal")
        deployment = candidate.begin_deployment(
            actor_id=identity.actor_id,
            reason="approved candidate entered shadow",
        )
        await self._repository.add_deployment(deployment)
        return deployment

    async def promote_to_canary(
        self,
        identity: IdentityContext,
        deployment_id: UUID,
    ) -> Deployment:
        deployment = await self._repository.get_deployment(identity.tenant_id, deployment_id)
        deployment = deployment.transition_to(
            DeploymentStatus.CANARY,
            actor_id=identity.actor_id,
            reason="shadow gate passed",
        )
        await self._repository.save_deployment(deployment)
        return deployment

    async def release_stable(
        self,
        identity: IdentityContext,
        deployment_id: UUID,
        stable_version_id: UUID,
    ) -> Release:
        deployment = await self._repository.get_deployment(identity.tenant_id, deployment_id)
        candidate = await self._repository.get_candidate(
            identity.tenant_id, deployment.candidate_id
        )
        deployment = deployment.transition_to(
            DeploymentStatus.STABLE,
            actor_id=identity.actor_id,
            reason="canary gate passed",
        )
        release = Release.from_stable_deployment(
            deployment,
            stable_version_id=stable_version_id,
            previous_stable_version_id=candidate.baseline_version_id,
            approved_by=identity.actor_id,
        )
        await self._repository.save_deployment(deployment)
        await self._repository.add_release(release)
        return release

    async def rollback(self, identity: IdentityContext, release_id: UUID) -> Release:
        try:
            release = await self._repository.get_active_release(identity.tenant_id, release_id)
        except RecordNotFound:
            raise
        deployment = await self._repository.get_deployment(
            identity.tenant_id, release.deployment_id
        )
        await self._repository.save_deployment(
            deployment.transition_to(
                DeploymentStatus.ROLLED_BACK,
                actor_id=identity.actor_id,
                reason="release rollback requested",
            )
        )
        rollback_release = Release(
            tenant_id=identity.tenant_id,
            candidate_id=release.candidate_id,
            deployment_id=release.deployment_id,
            stable_version_id=release.previous_stable_version_id,
            previous_stable_version_id=release.stable_version_id,
            approved_by=identity.actor_id,
        )
        await self._repository.add_release(rollback_release)
        return rollback_release
