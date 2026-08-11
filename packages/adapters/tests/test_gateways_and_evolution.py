from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from autonoesis_adapters import (
    DevelopmentPolicy,
    EphemeralCredentialBroker,
    FakeModelAdapter,
    InMemoryAtomicExecutionReservations,
    InMemoryDelegationStore,
    InMemoryGatewayAudit,
    InMemoryPlatformStore,
    JsonSchemaValidator,
    StaticToolCatalog,
)
from autonoesis_application import CandidateLifecycleService, EvaluationDecision, IdentityContext
from autonoesis_domain import (
    Action,
    ActionStatus,
    ApprovalRequest,
    CandidateStatus,
    CandidateVersion,
    JsonObject,
    RiskLevel,
)
from autonoesis_governance import InMemoryKillSwitchStore
from autonoesis_runtime import (
    AuthorizationContext,
    GovernedToolGateway,
    ModelGateway,
    ModelRequest,
    ModelRoute,
    ResolvedToolVersion,
    ToolReceipt,
    ToolResultStatus,
)


class FakeExecutor:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, action: Action, tool: object, credential: object) -> ToolReceipt:
        del action, tool, credential
        self.calls += 1
        return ToolReceipt("EXT-1", ToolResultStatus.SUCCEEDED, (("state", "created"),))

    async def verify(self, action: Action, tool: object, receipt: ToolReceipt) -> bool:
        del action, tool
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
        tenant_id=tenant_id,
        run_id=run_id,
        task_id=task_id,
        tool_name="record.create",
        tool_version="1.0.0",
        operation="create",
        resource_scope="subjects/subject-1",
        parameters=JsonObject.from_value({"value": "approved"}),
        risk_level=RiskLevel.L2_REVERSIBLE_WRITE,
        idempotency_key="stable-key",
        expected_effect="one record exists",
    ).transition_to(ActionStatus.AWAITING_APPROVAL)
    approval = ApprovalRequest(
        tenant_id=tenant_id,
        run_id=run_id,
        action_id=action.action_id,
        action_digest=action.canonical_digest,
        tool_version=action.tool_version,
        operation=action.operation,
        resource_scope=action.resource_scope,
        argument_digest=action.parameter_digest,
        policy_version="v1",
        impact_summary="create one reversible record",
        required_role="approver",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    ).decide(uuid4(), True, "scope verified")
    executor = FakeExecutor()
    delegation = InMemoryDelegationStore()
    delegation.grant("delegation-1", "record.create", "subjects/")
    gateway = GovernedToolGateway(
        catalog=StaticToolCatalog(
            (
                ResolvedToolVersion(
                    "record.create",
                    "1.0.0",
                    "test-provider",
                    frozenset({"create"}),
                    ("subjects/",),
                    {"type": "object", "required": ["value"]},
                    RiskLevel.L2_REVERSIBLE_WRITE,
                    "records.write",
                ),
            )
        ),
        delegation=delegation,
        schema_validator=JsonSchemaValidator(),
        policy=DevelopmentPolicy(),
        kill_switch=InMemoryKillSwitchStore(),
        reservations=InMemoryAtomicExecutionReservations(),
        credentials=EphemeralCredentialBroker(),
        egress=executor,
        audit=InMemoryGatewayAudit(),
    )
    context = AuthorizationContext(
        str(tenant_id),
        str(uuid4()),
        str(uuid4()),
        "agent",
        ("operator",),
        "v1",
        "delegation-1",
    )
    first = await gateway.execute(context, action, approval, 1)
    duplicate = await gateway.execute(context, action, approval, 1)
    assert first.action.status is ActionStatus.SUCCEEDED
    assert duplicate.action.status is ActionStatus.SUCCEEDED
    assert duplicate.cached is True
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
