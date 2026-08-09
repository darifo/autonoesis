from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from autonoesis_adapters import (
    DevelopmentPolicy,
    FakeModelAdapter,
    InMemoryBudgetLedger,
    InMemoryIdempotencyStore,
    InMemoryPlatformStore,
)
from autonoesis_application import CandidateLifecycleService, EvaluationDecision, IdentityContext
from autonoesis_domain import (
    Action,
    ActionStatus,
    ApprovalRequest,
    CandidateStatus,
    CandidateVersion,
    RiskLevel,
)
from autonoesis_runtime import (
    AuthorizationContext,
    GovernedToolGateway,
    ModelGateway,
    ModelRequest,
    ModelRoute,
    ToolReceipt,
)


class FakeExecutor:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, action: Action) -> ToolReceipt:
        self.calls += 1
        return ToolReceipt("EXT-1", True, (("state", "created"),))

    async def verify(self, action: Action, receipt: ToolReceipt) -> bool:
        return receipt.external_id == "EXT-1"


@pytest.mark.asyncio
async def test_model_gateway_filters_routes_and_supports_offline_fake() -> None:
    gateway = ModelGateway(
        (
            ModelRoute(
                "fake",
                "fake-1",
                frozenset({"reasoning"}),
                frozenset({"cn"}),
                "medium",
                1,
            ),
        ),
        {"fake": FakeModelAdapter("verified")},
    )
    response = await gateway.generate(
        ModelRequest("system", "input", ("reasoning",), "cn", "low", 100)
    )
    assert response.output_text == "verified"
    assert "capabilities" in response.route_reason

    with pytest.raises(LookupError, match="hard constraints"):
        await gateway.generate(ModelRequest("system", "input", ("reasoning",), "cn", "high", 100))


@pytest.mark.asyncio
async def test_tool_gateway_requires_exact_approval_and_deduplicates_write() -> None:
    tenant_id, run_id, task_id = uuid4(), uuid4(), uuid4()
    action = Action(
        tenant_id,
        run_id,
        task_id,
        "record.create",
        "create",
        "subject-1",
        (("value", "approved"),),
        RiskLevel.L2_REVERSIBLE_WRITE,
        "stable-key",
        "one record exists",
    ).transition_to(ActionStatus.AWAITING_APPROVAL)
    approval = ApprovalRequest(
        tenant_id,
        run_id,
        action.action_id,
        action.parameter_digest,
        "create one reversible record",
        "approver",
        datetime.now(UTC) + timedelta(minutes=5),
    ).decide(uuid4(), True, "scope verified")
    executor = FakeExecutor()
    gateway = GovernedToolGateway(
        DevelopmentPolicy(),
        InMemoryBudgetLedger(),
        InMemoryIdempotencyStore(),
        {"record.create": executor},
    )
    context = AuthorizationContext(
        str(tenant_id),
        str(uuid4()),
        str(uuid4()),
        "agent",
        ("operator",),
        "v1",
    )
    first, _ = await gateway.execute(context, action, approval, 1)
    duplicate, _ = await gateway.execute(context, action, approval, 1)
    assert first.status is ActionStatus.SUCCEEDED
    assert duplicate.status is ActionStatus.SUCCEEDED
    assert executor.calls == 1


@pytest.mark.asyncio
async def test_candidate_generator_cannot_grade_its_own_candidate() -> None:
    store = InMemoryPlatformStore()
    candidate = CandidateVersion(uuid4(), uuid4(), uuid4(), "artifact://candidate", "generator")
    await store.add_candidate(candidate)
    service = CandidateLifecycleService(store)
    await service.submit_for_evaluation(candidate.tenant_id, candidate.candidate_id)
    with pytest.raises(PermissionError, match="grade"):
        await service.record_evaluation(
            candidate.tenant_id,
            candidate.candidate_id,
            EvaluationDecision(True, 1, "generator", 0.8),
        )
    evaluated = await service.record_evaluation(
        candidate.tenant_id,
        candidate.candidate_id,
        EvaluationDecision(True, 0.9, "independent-grader", 0.8),
    )
    assert evaluated.status is CandidateStatus.AWAITING_APPROVAL
    identity = IdentityContext(candidate.tenant_id, uuid4(), uuid4(), frozenset({"approver"}))
    approved = await service.decide(identity, candidate.candidate_id, True)
    assert approved.status is CandidateStatus.APPROVED
