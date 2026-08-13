"""Governed candidate evaluation, approval, promotion, and rollback services."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from autonoesis_domain import (
    CandidateStatus,
    CandidateVersion,
    Deployment,
    DeploymentStatus,
    Release,
)

from autonoesis_application.platform import IdentityContext, RecordNotFound


class EvolutionRepository(Protocol):
    async def add_candidate(self, candidate: CandidateVersion) -> None: ...

    async def get_candidate(self, tenant_id: UUID, candidate_id: UUID) -> CandidateVersion: ...

    async def save_candidate(self, candidate: CandidateVersion) -> None: ...

    async def add_deployment(self, deployment: Deployment) -> None: ...

    async def get_deployment(self, tenant_id: UUID, deployment_id: UUID) -> Deployment: ...

    async def save_deployment(self, deployment: Deployment) -> None: ...

    async def add_release(self, release: Release) -> None: ...

    async def get_active_release(self, tenant_id: UUID, candidate_id: UUID) -> Release: ...


@dataclass(frozen=True, slots=True)
class EvaluationDecision:
    passed: bool
    score: float
    threshold: float


class CandidateLifecycleService:
    def __init__(self, repository: EvolutionRepository) -> None:
        self._repository = repository

    async def submit_for_evaluation(self, tenant_id: UUID, candidate_id: UUID) -> CandidateVersion:
        candidate = await self._repository.get_candidate(tenant_id, candidate_id)
        candidate = candidate.transition_to(CandidateStatus.EVALUATING)
        await self._repository.save_candidate(candidate)
        return candidate

    async def record_evaluation(
        self,
        identity: IdentityContext,
        candidate_id: UUID,
        decision: EvaluationDecision,
    ) -> CandidateVersion:
        candidate = await self._repository.get_candidate(identity.tenant_id, candidate_id)
        passed = decision.passed and decision.score >= decision.threshold
        target = CandidateStatus.AWAITING_APPROVAL if passed else CandidateStatus.REJECTED
        candidate = candidate.record_evaluation(target, grader_principal_id=identity.principal_id)
        await self._repository.save_candidate(candidate)
        return candidate

    async def decide(
        self,
        identity: IdentityContext,
        candidate_id: UUID,
        approved: bool,
    ) -> CandidateVersion:
        candidate = await self._repository.get_candidate(identity.tenant_id, candidate_id)
        target = CandidateStatus.APPROVED if approved else CandidateStatus.REJECTED
        candidate = candidate.record_approval(target, approver_principal_id=identity.principal_id)
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
