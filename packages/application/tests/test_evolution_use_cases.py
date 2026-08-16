"""Tests for governed improvement proposal and candidate registration use cases."""

from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

import pytest
from autonoesis_application import (
    CandidateLifecycleService,
    IdentityContext,
    ProposeImprovement,
    RegisterCandidate,
)
from autonoesis_domain import (
    CandidateStatus,
    ImprovementProposal,
    ImprovementTarget,
)

DIGEST = "a" * 64


class FakeEvolutionRepository:
    def __init__(self) -> None:
        self.proposals: dict[UUID, ImprovementProposal] = {}
        self.candidates: dict[UUID, Any] = {}
        self.deployments: dict[UUID, Any] = {}
        self.releases: dict[UUID, Any] = {}

    async def add_proposal(self, proposal: ImprovementProposal) -> None:
        self.proposals[proposal.proposal_id] = proposal

    async def get_proposal(self, tenant_id: UUID, proposal_id: UUID) -> ImprovementProposal:
        proposal = self.proposals.get(proposal_id)
        if proposal is None or proposal.tenant_id != tenant_id:
            raise KeyError("proposal not found")
        return proposal

    async def add_candidate(self, candidate: Any) -> None:
        self.candidates[candidate.candidate_id] = candidate

    async def get_candidate(self, tenant_id: UUID, candidate_id: UUID) -> Any:
        return self.candidates[candidate_id]

    async def save_candidate(self, candidate: Any) -> None:
        self.candidates[candidate.candidate_id] = candidate

    async def add_deployment(self, deployment: Any) -> None:
        self.deployments[deployment.deployment_id] = deployment

    async def get_deployment(self, tenant_id: UUID, deployment_id: UUID) -> Any:
        return self.deployments[deployment_id]

    async def save_deployment(self, deployment: Any) -> None:
        self.deployments[deployment.deployment_id] = deployment

    async def add_release(self, release: Any) -> None:
        self.releases[release.release_id] = release

    async def get_active_release(self, tenant_id: UUID, candidate_id: UUID) -> Any:
        return next(
            release for release in self.releases.values() if release.candidate_id == candidate_id
        )


class DenyingPolicy:
    async def assert_target_allowed(self, raw_target: str) -> None:
        raise PermissionError(f"improvement target denied by policy: {raw_target}")


def identity() -> IdentityContext:
    return IdentityContext(uuid4(), uuid4(), uuid4(), frozenset({"candidate_generator"}))


def propose_command() -> ProposeImprovement:
    return ProposeImprovement(
        target="agent_instruction",
        target_version_id=uuid4(),
        evidence_refs=("evidence://observation/1",),
        diagnosis="instruction misses a recovery condition",
        proposed_change="add recovery condition",
        validation_suite_id="delivery-suite",
        rollback_plan="restore previous stable version",
    )


@pytest.mark.asyncio
async def test_proposal_is_registered_with_generator_identity() -> None:
    repository = FakeEvolutionRepository()
    context = identity()
    service = CandidateLifecycleService(repository)
    proposal = await service.propose_improvement(context, propose_command())
    assert proposal.target is ImprovementTarget.AGENT_INSTRUCTION
    assert proposal.proposer_id == str(context.principal_id)
    assert repository.proposals[proposal.proposal_id] is proposal


@pytest.mark.asyncio
async def test_candidate_carries_fixed_references_and_suite_binding() -> None:
    repository = FakeEvolutionRepository()
    context = identity()
    service = CandidateLifecycleService(repository)
    proposal = await service.propose_improvement(context, propose_command())
    candidate = await service.register_candidate(
        context,
        RegisterCandidate(
            proposal_id=proposal.proposal_id,
            baseline_version_id=uuid4(),
            artifact_ref="artifact://agent/v2",
            artifact_digest=DIGEST,
            suite_id="delivery-suite",
            suite_version="3",
        ),
    )
    assert candidate.status is CandidateStatus.DRAFT
    assert candidate.artifact_digest == DIGEST
    assert (candidate.suite_id, candidate.suite_version) == ("delivery-suite", "3")
    assert candidate.generator_id == str(context.principal_id)


@pytest.mark.asyncio
async def test_candidate_cannot_swap_the_validation_suite() -> None:
    repository = FakeEvolutionRepository()
    context = identity()
    service = CandidateLifecycleService(repository)
    proposal = await service.propose_improvement(context, propose_command())
    with pytest.raises(ValueError, match="fixed validation suite"):
        await service.register_candidate(
            context,
            RegisterCandidate(
                proposal_id=proposal.proposal_id,
                baseline_version_id=uuid4(),
                artifact_ref="artifact://agent/v2",
                artifact_digest=DIGEST,
                suite_id="easier-suite",
                suite_version="1",
            ),
        )
    assert not repository.candidates


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["identity", "kill_switch", "Tenant_Isolation"])
async def test_forbidden_targets_are_rejected_by_the_application_layer(
    target: str,
) -> None:
    repository = FakeEvolutionRepository()
    service = CandidateLifecycleService(repository)
    command = propose_command()
    with pytest.raises(PermissionError, match="forbidden"):
        await service.propose_improvement(identity(), replace(command, target=target))
    assert not repository.proposals


@pytest.mark.asyncio
async def test_policy_layer_denies_independently_of_the_application_guard() -> None:
    repository = FakeEvolutionRepository()
    service = CandidateLifecycleService(repository, DenyingPolicy())
    with pytest.raises(PermissionError, match="denied by policy"):
        await service.propose_improvement(identity(), propose_command())
    assert not repository.proposals


@pytest.mark.asyncio
async def test_candidate_registration_rechecks_the_persisted_proposal_target() -> None:
    repository = FakeEvolutionRepository()
    context = identity()
    service = CandidateLifecycleService(repository, DenyingPolicy())
    # A proposal smuggled past creation (for example by a legacy writer) still
    # cannot spawn a candidate once the policy layer denies its target.
    smuggled = ImprovementProposal(
        tenant_id=context.tenant_id,
        target=ImprovementTarget.AGENT_INSTRUCTION,
        target_version_id=uuid4(),
        evidence_refs=("evidence://observation/1",),
        diagnosis="diagnosis",
        proposed_change="change",
        validation_suite_id="delivery-suite",
        rollback_plan="restore",
        proposer_id="legacy-writer",
    )
    repository.proposals[smuggled.proposal_id] = smuggled
    with pytest.raises(PermissionError, match="denied by policy"):
        await service.register_candidate(
            context,
            RegisterCandidate(
                proposal_id=smuggled.proposal_id,
                baseline_version_id=uuid4(),
                artifact_ref="artifact://agent/v2",
                artifact_digest=DIGEST,
                suite_id="delivery-suite",
                suite_version="1",
            ),
        )
    assert not repository.candidates


@pytest.mark.asyncio
async def test_candidate_without_a_real_digest_is_rejected() -> None:
    repository = FakeEvolutionRepository()
    context = identity()
    service = CandidateLifecycleService(repository)
    proposal = await service.propose_improvement(context, propose_command())
    with pytest.raises(ValueError, match="digest"):
        await service.register_candidate(
            context,
            RegisterCandidate(
                proposal_id=proposal.proposal_id,
                baseline_version_id=uuid4(),
                artifact_ref="artifact://agent/v2",
                artifact_digest="not-a-digest",
                suite_id="delivery-suite",
                suite_version="1",
            ),
        )
