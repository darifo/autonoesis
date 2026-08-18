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
        self.trials: dict[UUID, list[Any]] = {}
        self.evaluations: dict[UUID, list[Any]] = {}
        self.observations: dict[tuple[UUID, str, str], Any] = {}

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

    async def add_trial(self, trial: Any) -> None:
        self.trials.setdefault(trial.candidate_id, []).append(trial)

    async def list_trials_for_candidate(self, tenant_id: UUID, candidate_id: UUID) -> Any:
        return tuple(self.trials.get(candidate_id, ()))

    async def add_evaluation_record(self, record: Any) -> None:
        self.evaluations.setdefault(record.candidate_id, []).append(record)

    async def list_evaluation_records(self, tenant_id: UUID, candidate_id: UUID) -> Any:
        return tuple(self.evaluations.get(candidate_id, ()))

    async def get_observation(
        self, tenant_id: UUID, deployment_id: UUID, stage: Any, metric: str
    ) -> Any:
        return self.observations.get((deployment_id, stage.value, metric))

    async def save_observation(self, observation: Any) -> None:
        self.observations[
            (observation.deployment_id, observation.stage.value, observation.metric)
        ] = observation


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


def _executed_case() -> Any:
    from autonoesis_domain import TrialCaseResult

    return TrialCaseResult(
        case_id="c1",
        input_payload={},
        output_payload={"answer": 42},
        subject_executed=True,
        executor_id="subject-runtime",
        evidence_refs=("evidence://execution/1",),
        environment_ref="environment://fixture/1",
    )


def _trial(
    candidate_id: UUID,
    *,
    status: str = "passed",
    suite: str = "delivery-suite",
    subject: UUID | None = None,
) -> Any:
    from autonoesis_domain import Trial, TrialStatus

    return Trial(
        tenant_id=UUID(int=1),
        suite_id=suite,
        suite_version="1",
        subject_version_id=subject or candidate_id,
        harness_version="2",
        status=TrialStatus(status),
        case_results=(_executed_case(),) if status in {"passed", "failed"} else (),
        failure_reason="infrastructure failed" if status == "invalid" else None,
        candidate_id=candidate_id,
    )


async def _candidate_in_evaluation(
    service: CandidateLifecycleService, repository: FakeEvolutionRepository
) -> UUID:
    from autonoesis_application import RegisterCandidate

    context = IdentityContext(UUID(int=1), uuid4(), uuid4(), frozenset({"candidate_generator"}))
    proposal = await service.propose_improvement(
        context,
        ProposeImprovement(
            target="agent_instruction",
            target_version_id=uuid4(),
            evidence_refs=("evidence://observation/1",),
            diagnosis="diagnosis",
            proposed_change="change",
            validation_suite_id="delivery-suite",
            rollback_plan="restore",
        ),
    )
    candidate = await service.register_candidate(
        context,
        RegisterCandidate(
            proposal_id=proposal.proposal_id,
            baseline_version_id=uuid4(),
            artifact_ref="artifact://agent/v2",
            artifact_digest=DIGEST,
            suite_id="delivery-suite",
            suite_version="1",
        ),
    )
    await service.submit_for_evaluation(candidate.tenant_id, candidate.candidate_id)
    return candidate.candidate_id


def _grader() -> IdentityContext:
    return IdentityContext(UUID(int=1), uuid4(), uuid4(), frozenset({"grader"}))


@pytest.mark.asyncio
async def test_candidate_without_complete_evidence_stays_evaluating() -> None:
    from autonoesis_evaluation import RepeatedTrialPolicy

    repository = FakeEvolutionRepository()
    service = CandidateLifecycleService(repository)
    candidate_id = await _candidate_in_evaluation(service, repository)
    for _ in range(5):
        await repository.add_trial(_trial(candidate_id))
    with pytest.raises(ValueError, match="incomplete"):
        await service.complete_evaluation(
            _grader(), candidate_id, RepeatedTrialPolicy(pass_threshold=0.8)
        )
    records = await repository.list_evaluation_records(UUID(int=1), candidate_id)
    assert [record.decision for record in records] == ["insufficient_sample"]
    assert repository.candidates[candidate_id].status.value == "evaluating"


@pytest.mark.asyncio
async def test_confident_sample_advances_candidate_and_persists_evidence() -> None:
    from autonoesis_evaluation import RepeatedTrialPolicy

    repository = FakeEvolutionRepository()
    service = CandidateLifecycleService(repository)
    candidate_id = await _candidate_in_evaluation(service, repository)
    for _ in range(16):
        await repository.add_trial(_trial(candidate_id))
    candidate, record = await service.complete_evaluation(
        _grader(), candidate_id, RepeatedTrialPolicy(pass_threshold=0.8)
    )
    assert candidate.status.value == "awaiting_approval"
    assert record.decision == "met"
    assert len(record.trial_ids) == 16
    assert record.assessment["lower_bound"] >= 0.8


@pytest.mark.asyncio
async def test_confident_failure_rejects_candidate() -> None:
    from autonoesis_evaluation import RepeatedTrialPolicy

    repository = FakeEvolutionRepository()
    service = CandidateLifecycleService(repository)
    candidate_id = await _candidate_in_evaluation(service, repository)
    for _ in range(30):
        await repository.add_trial(_trial(candidate_id, status="failed"))
    candidate, record = await service.complete_evaluation(
        _grader(), candidate_id, RepeatedTrialPolicy(pass_threshold=0.8)
    )
    assert candidate.status.value == "rejected"
    assert record.decision == "not_met"


@pytest.mark.asyncio
async def test_trials_from_another_suite_are_rejected() -> None:
    from autonoesis_evaluation import RepeatedTrialPolicy

    repository = FakeEvolutionRepository()
    service = CandidateLifecycleService(repository)
    candidate_id = await _candidate_in_evaluation(service, repository)
    await repository.add_trial(_trial(candidate_id, suite="easier-suite"))
    with pytest.raises(ValueError, match="fixed suite"):
        await service.complete_evaluation(
            _grader(), candidate_id, RepeatedTrialPolicy(pass_threshold=0.8)
        )


@pytest.mark.asyncio
async def test_trials_executing_another_subject_are_rejected() -> None:
    from autonoesis_evaluation import RepeatedTrialPolicy

    repository = FakeEvolutionRepository()
    service = CandidateLifecycleService(repository)
    candidate_id = await _candidate_in_evaluation(service, repository)
    await repository.add_trial(_trial(candidate_id, subject=uuid4()))
    with pytest.raises(ValueError, match="execute the candidate itself"):
        await service.complete_evaluation(
            _grader(), candidate_id, RepeatedTrialPolicy(pass_threshold=0.8)
        )


@pytest.mark.asyncio
async def test_approval_without_rationale_is_rejected() -> None:
    repository = FakeEvolutionRepository()
    service = CandidateLifecycleService(repository)
    candidate_id = await _candidate_in_evaluation(service, repository)
    with pytest.raises(ValueError, match="rationale"):
        await service.decide(_grader(), candidate_id, True, "  ")


async def _approved_candidate(
    service: CandidateLifecycleService, repository: FakeEvolutionRepository
) -> UUID:
    from autonoesis_evaluation import RepeatedTrialPolicy

    candidate_id = await _candidate_in_evaluation(service, repository)
    for _ in range(16):
        await repository.add_trial(_trial(candidate_id))
    candidate, _ = await service.complete_evaluation(
        _grader(), candidate_id, RepeatedTrialPolicy(pass_threshold=0.8)
    )
    assert candidate.status.value == "awaiting_approval"
    approved = await service.decide(
        IdentityContext(UUID(int=1), uuid4(), uuid4(), frozenset({"approver"})),
        candidate_id,
        True,
        "approve for promotion",
    )
    assert approved.status.value == "approved"
    return candidate_id


async def _shadow_deployment(
    service: CandidateLifecycleService, repository: FakeEvolutionRepository
) -> Any:
    candidate_id = await _approved_candidate(service, repository)
    return await service.begin_shadow(
        IdentityContext(UUID(int=1), uuid4(), uuid4(), frozenset({"release_executor"})),
        candidate_id,
    )


@pytest.mark.asyncio
async def test_release_stable_requires_canary_observations() -> None:
    from autonoesis_application import PromotionPolicy

    repository = FakeEvolutionRepository()
    service = CandidateLifecycleService(repository)
    deployment = await _shadow_deployment(service, repository)
    canary = await service.promote_to_canary(
        IdentityContext(UUID(int=1), uuid4(), uuid4(), frozenset({"release_executor"})),
        deployment.deployment_id,
    )
    with pytest.raises(ValueError, match="missing evidence"):
        await service.release_stable(
            IdentityContext(UUID(int=1), uuid4(), uuid4(), frozenset({"release_executor"})),
            canary.deployment_id,
            uuid4(),
            PromotionPolicy(min_samples=2, required_metrics=("outcome_rate",)),
        )


@pytest.mark.asyncio
async def test_release_stable_promotes_once_observations_satisfy_gate() -> None:
    from autonoesis_application import PromotionPolicy, RecordObservation
    from autonoesis_domain import DeploymentStatus

    repository = FakeEvolutionRepository()
    service = CandidateLifecycleService(repository)
    deployment = await _shadow_deployment(service, repository)
    executor = IdentityContext(UUID(int=1), uuid4(), uuid4(), frozenset({"release_executor"}))
    canary = await service.promote_to_canary(executor, deployment.deployment_id)
    for _ in range(3):
        await service.record_observation(
            executor,
            RecordObservation(canary.deployment_id, DeploymentStatus.CANARY, "outcome_rate", 0.99),
        )
    release = await service.release_stable(
        executor,
        canary.deployment_id,
        uuid4(),
        PromotionPolicy(min_samples=2, required_metrics=("outcome_rate",)),
    )
    assert release.stable_version_id is not None
    assert repository.deployments[canary.deployment_id].status.value == "stable"


@pytest.mark.asyncio
async def test_guardrail_breach_rolls_back_only_target_deployment() -> None:
    from autonoesis_application import RecordObservation
    from autonoesis_domain import DeploymentStatus, GuardrailOperator

    repository = FakeEvolutionRepository()
    service = CandidateLifecycleService(repository)
    executor = IdentityContext(UUID(int=1), uuid4(), uuid4(), frozenset({"release_executor"}))
    first = await _shadow_deployment(service, repository)
    second = await _shadow_deployment(service, repository)
    canary_first = await service.promote_to_canary(executor, first.deployment_id)
    for _ in range(3):
        await service.record_observation(
            executor,
            RecordObservation(
                canary_first.deployment_id,
                DeploymentStatus.CANARY,
                "error_rate",
                0.5,
                GuardrailOperator.GTE,
                0.1,
            ),
        )
    rolled_back = await service.rollback_if_breached(
        executor, canary_first.deployment_id, DeploymentStatus.CANARY, "error_rate", 2
    )
    assert rolled_back is not None
    assert rolled_back.status.value == "rolled_back"
    assert second.status.value == "shadow"


@pytest.mark.asyncio
async def test_observation_stage_must_match_deployment() -> None:
    from autonoesis_application import RecordObservation
    from autonoesis_domain import DeploymentStatus

    repository = FakeEvolutionRepository()
    service = CandidateLifecycleService(repository)
    deployment = await _shadow_deployment(service, repository)
    executor = IdentityContext(UUID(int=1), uuid4(), uuid4(), frozenset({"release_executor"}))
    with pytest.raises(ValueError, match="does not match deployment"):
        await service.record_observation(
            executor,
            RecordObservation(deployment.deployment_id, DeploymentStatus.CANARY, "m", 1.0),
        )
