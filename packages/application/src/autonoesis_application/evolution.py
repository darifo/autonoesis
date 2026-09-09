"""Governed candidate evaluation, approval, promotion, and rollback services."""

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from autonoesis_domain import (
    CandidateEvaluation,
    CandidateStatus,
    CandidateVersion,
    Deployment,
    DeploymentObservation,
    DeploymentStatus,
    GuardrailOperator,
    ImprovementProposal,
    ImprovementTarget,
    Release,
    ShadowComparison,
    ShadowMeasurements,
    TrafficAllocation,
    TrafficRoute,
    Trial,
    require_improvement_target_allowed,
)
from autonoesis_evaluation import (
    ConfidenceDecision,
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

    async def get_observation(
        self, tenant_id: UUID, deployment_id: UUID, stage: DeploymentStatus, metric: str
    ) -> DeploymentObservation | None: ...

    async def save_observation(self, observation: DeploymentObservation) -> None: ...

    async def add_shadow_comparison(self, comparison: ShadowComparison) -> None: ...

    async def list_shadow_comparisons(
        self, tenant_id: UUID, deployment_id: UUID
    ) -> tuple[ShadowComparison, ...]: ...


class ImprovementTargetPolicy(Protocol):
    """External policy decision point consulted before any improvement proposal."""

    async def assert_target_allowed(self, raw_target: str) -> None: ...


class ShadowSubjectRuntime(Protocol):
    """Execute a pinned version with an explicit external-effect contract."""

    async def execute_shadow_subject(
        self,
        *,
        tenant_id: UUID,
        deployment_id: UUID,
        version_id: UUID,
        request_ref: str,
        input_payload: dict[str, Any],
        external_effects_enabled: bool,
    ) -> ShadowMeasurements: ...


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


@dataclass(frozen=True, slots=True)
class PromotionPolicy:
    """Governed promotion gate: real-time observation and minimum samples."""

    min_samples: int = 1
    observation_seconds: int = 0
    required_metrics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.min_samples < 1:
            raise ValueError("promotion policy requires a positive minimum sample")
        if self.observation_seconds < 0:
            raise ValueError("promotion policy observation window cannot be negative")


@dataclass(frozen=True, slots=True)
class RecordObservation:
    deployment_id: UUID
    stage: DeploymentStatus
    metric: str
    value: float
    operator: GuardrailOperator | None = None
    threshold: float | None = None

    def __post_init__(self) -> None:
        if (self.operator is None) != (self.threshold is None):
            raise ValueError("guardrail operator and threshold must be provided together")


@dataclass(frozen=True, slots=True)
class ExecuteShadowPair:
    deployment_id: UUID
    request_ref: str
    input_payload: dict[str, Any]

    def __post_init__(self) -> None:
        if not self.request_ref.strip():
            raise ValueError("shadow request reference is required")


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


def _guardrail_breached(
    operator: GuardrailOperator | None, threshold: float | None, value: float
) -> bool:
    if operator is None or threshold is None:
        return False
    match operator:
        case GuardrailOperator.LT:
            return value < threshold
        case GuardrailOperator.GT:
            return value > threshold
        case GuardrailOperator.LTE:
            return value <= threshold
        case GuardrailOperator.GTE:
            return value >= threshold


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
        elif assessment.decision is ConfidenceDecision.NOT_MET:
            target = CandidateStatus.REJECTED
        else:
            # Straddling or short samples stay evaluating; callers may add Trials.
            raise ValueError(f"candidate evaluation evidence is incomplete: {assessment.rationale}")
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

    async def execute_shadow_pair(
        self,
        identity: IdentityContext,
        command: ExecuteShadowPair,
        runtime: ShadowSubjectRuntime,
    ) -> ShadowComparison:
        """Mirror one input through Stable and Candidate and persist paired evidence."""

        deployment = await self._repository.get_deployment(
            identity.tenant_id, command.deployment_id
        )
        if deployment.status is not DeploymentStatus.SHADOW:
            raise ValueError("shadow pair execution requires a shadow deployment")
        candidate = await self._repository.get_candidate(
            identity.tenant_id, deployment.candidate_id
        )
        stable_result, candidate_result = await asyncio.gather(
            runtime.execute_shadow_subject(
                tenant_id=identity.tenant_id,
                deployment_id=deployment.deployment_id,
                version_id=candidate.baseline_version_id,
                request_ref=command.request_ref,
                input_payload=command.input_payload,
                external_effects_enabled=True,
            ),
            runtime.execute_shadow_subject(
                tenant_id=identity.tenant_id,
                deployment_id=deployment.deployment_id,
                version_id=candidate.candidate_id,
                request_ref=command.request_ref,
                input_payload=command.input_payload,
                external_effects_enabled=False,
            ),
        )
        comparison = ShadowComparison(
            tenant_id=identity.tenant_id,
            deployment_id=deployment.deployment_id,
            request_ref=command.request_ref,
            stable_version_id=candidate.baseline_version_id,
            candidate_version_id=candidate.candidate_id,
            stable=stable_result,
            candidate=candidate_result,
        )
        await self._repository.add_shadow_comparison(comparison)
        metrics = {
            "outcome_score_delta": candidate_result.outcome_score - stable_result.outcome_score,
            "cost_microunits_delta": float(
                candidate_result.cost_microunits - stable_result.cost_microunits
            ),
            "latency_ms_delta": candidate_result.latency_ms - stable_result.latency_ms,
            "security_violations": float(candidate_result.security_violations),
            "human_corrections_delta": float(
                candidate_result.human_corrections - stable_result.human_corrections
            ),
        }
        for metric, value in metrics.items():
            await self.record_observation(
                identity,
                RecordObservation(
                    deployment_id=deployment.deployment_id,
                    stage=DeploymentStatus.SHADOW,
                    metric=metric,
                    value=value,
                ),
            )
        return comparison

    async def promote_to_canary(
        self,
        identity: IdentityContext,
        deployment_id: UUID,
        allocation: TrafficAllocation,
    ) -> Deployment:
        """Bind the auditable traffic rule that governs all live Canary assignment."""

        deployment = await self._repository.get_deployment(identity.tenant_id, deployment_id)
        candidate = await self._repository.get_candidate(
            identity.tenant_id, deployment.candidate_id
        )
        if str(identity.principal_id) in {
            candidate.generator_id,
            candidate.grader_principal_id,
            candidate.approver_principal_id,
        }:
            raise PermissionError("release execution requires an independent principal")
        deployment = deployment.enter_canary(
            allocation,
            actor_id=identity.actor_id,
            reason=(
                "canary entered with "
                f"{allocation.candidate_percent}% deterministic candidate traffic"
            ),
        )
        await self._repository.save_deployment(deployment)
        return deployment

    async def resolve_request_route(
        self,
        identity: IdentityContext,
        deployment_id: UUID,
        request_id: UUID,
    ) -> tuple[TrafficRoute, TrafficAllocation]:
        """Replay the persisted rule to explain which version serves a request."""

        deployment = await self._repository.get_deployment(identity.tenant_id, deployment_id)
        allocation = deployment.traffic_allocation
        route = deployment.assign_request(request_id)
        if allocation is None:  # pragma: no cover - assign_request already guards this
            raise ValueError("canary deployment carries no traffic allocation rule")
        return route, allocation

    async def release_stable(
        self,
        identity: IdentityContext,
        deployment_id: UUID,
        stable_version_id: UUID,
        policy: PromotionPolicy | None = None,
    ) -> Release:
        deployment = await self._repository.get_deployment(identity.tenant_id, deployment_id)
        if deployment.status is not DeploymentStatus.CANARY:
            raise ValueError("only a canary deployment can promote to stable")
        policy = policy or PromotionPolicy()
        await self._assert_promotion_gate(deployment, policy)
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

    async def _assert_promotion_gate(self, deployment: Deployment, policy: PromotionPolicy) -> None:
        entered_at = deployment.entered_at(DeploymentStatus.CANARY)
        if entered_at is None:
            raise ValueError("canary observation window has not started")
        elapsed = datetime.now(UTC) - entered_at
        if elapsed.total_seconds() < policy.observation_seconds:
            raise ValueError(
                "canary observation window not elapsed: "
                f"{elapsed.total_seconds():.1f}s < {policy.observation_seconds}s"
            )
        for metric in policy.required_metrics:
            observation = await self._repository.get_observation(
                deployment.tenant_id, deployment.deployment_id, DeploymentStatus.CANARY, metric
            )
            if observation is None or observation.sample_count < policy.min_samples:
                count = observation.sample_count if observation else 0
                raise ValueError(
                    f"missing evidence for required metric {metric!r}: "
                    f"{count} < {policy.min_samples} samples"
                )
            if observation.last_value is None:
                raise ValueError(
                    f"missing evidence for required metric {metric!r}: no sample value"
                )

    async def record_observation(
        self,
        identity: IdentityContext,
        command: RecordObservation,
    ) -> DeploymentObservation:
        deployment = await self._repository.get_deployment(
            identity.tenant_id, command.deployment_id
        )
        if deployment.status is not command.stage:
            raise ValueError(
                f"observation stage {command.stage.value} does not match deployment "
                f"status {deployment.status.value}"
            )
        now = datetime.now(UTC)
        existing = await self._repository.get_observation(
            identity.tenant_id, command.deployment_id, command.stage, command.metric
        )
        breached = (
            _guardrail_breached(command.operator, command.threshold, command.value)
            if command.operator is not None
            else False
        )
        if existing is None:
            observation = DeploymentObservation(
                tenant_id=identity.tenant_id,
                deployment_id=command.deployment_id,
                stage=command.stage,
                metric=command.metric,
                sample_count=1,
                breach_count=1 if breached else 0,
                last_value=command.value,
                first_sample_at=now,
                last_sample_at=now,
            )
        else:
            observation = replace(
                existing,
                sample_count=existing.sample_count + 1,
                breach_count=(existing.breach_count + 1) if breached else 0,
                last_value=command.value,
                last_sample_at=now,
            )
        await self._repository.save_observation(observation)
        return observation

    async def rollback_if_breached(
        self,
        identity: IdentityContext,
        deployment_id: UUID,
        stage: DeploymentStatus,
        metric: str,
        min_consecutive: int,
    ) -> Deployment | None:
        """Roll back a deployment when a guardrail counter reaches its breach threshold."""
        observation = await self._repository.get_observation(
            identity.tenant_id, deployment_id, stage, metric
        )
        if observation is None or observation.breach_count < min_consecutive:
            return None
        return await self.rollback_deployment(
            identity,
            deployment_id,
            f"guardrail breach: {metric} breached {observation.breach_count} consecutive samples",
        )

    async def rollback_deployment(
        self,
        identity: IdentityContext,
        deployment_id: UUID,
        reason: str,
    ) -> Deployment:
        if not reason.strip():
            raise ValueError("rollback requires a recorded reason")
        deployment = await self._repository.get_deployment(identity.tenant_id, deployment_id)
        deployment = deployment.transition_to(
            DeploymentStatus.ROLLED_BACK,
            actor_id=identity.actor_id,
            reason=reason.strip(),
        )
        await self._repository.save_deployment(deployment)
        return deployment

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
