"""Executable acceptance tests for the P0-05 governed tool boundary."""

import asyncio
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from autonoesis_adapters import (
    DevelopmentPolicy,
    EphemeralCredentialBroker,
    InMemoryAtomicExecutionReservations,
    InMemoryDelegationStore,
    InMemoryGatewayAudit,
    JsonSchemaValidator,
    OPAPolicyAdapter,
    StaticToolCatalog,
)
from autonoesis_domain import (
    Action,
    ActionStatus,
    ApprovalRequest,
    JsonObject,
    RiskLevel,
)
from autonoesis_governance import InMemoryKillSwitchStore
from autonoesis_runtime import (
    AuthorizationContext,
    GovernedToolGateway,
    KillSwitchDimension,
    ResolvedToolVersion,
    ToolReceipt,
    ToolResultStatus,
)


class FakeEgress:
    def __init__(self, status: ToolResultStatus = ToolResultStatus.SUCCEEDED) -> None:
        self.status = status
        self.calls = 0
        self.verify_calls = 0
        self.delay = 0.0
        self.timeout = False

    async def execute(self, action: Action, tool: object, credential: object) -> ToolReceipt:
        del action, tool, credential
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.timeout:
            raise TimeoutError
        return ToolReceipt("external-1", self.status, (("state", "recorded"),))

    async def verify(self, action: Action, tool: object, receipt: ToolReceipt) -> bool:
        del action, tool, receipt
        self.verify_calls += 1
        return True


def make_action(risk: RiskLevel = RiskLevel.L2_REVERSIBLE_WRITE) -> Action:
    return Action(
        tenant_id=uuid4(),
        run_id=uuid4(),
        task_id=uuid4(),
        tool_name="records",
        tool_version="2.1.0",
        operation="create",
        resource_scope="subjects/subject-1",
        parameters=JsonObject.from_value({"value": "approved"}),
        risk_level=risk,
        idempotency_key="stable-key",
        expected_effect="one external record exists",
    ).transition_to(ActionStatus.AWAITING_APPROVAL)


def make_context(action: Action, policy_version: str = "v1") -> AuthorizationContext:
    return AuthorizationContext(
        tenant_id=str(action.tenant_id),
        actor_id=str(uuid4()),
        principal_id=str(uuid4()),
        agent_id="agent-1",
        roles=("operator",),
        policy_version=policy_version,
        delegation_id="delegation-1",
        correlation_id=str(uuid4()),
    )


def make_approval(action: Action, policy_version: str = "v1") -> ApprovalRequest:
    return ApprovalRequest(
        tenant_id=action.tenant_id,
        run_id=action.run_id,
        action_id=action.action_id,
        action_digest=action.canonical_digest,
        tool_version=action.tool_version,
        operation=action.operation,
        resource_scope=action.resource_scope,
        argument_digest=action.parameter_digest,
        policy_version=policy_version,
        impact_summary="create exactly one record",
        required_role="approver",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    ).decide(uuid4(), True, "approved exact effect")


def build_gateway(
    action: Action,
    egress: FakeEgress,
    *,
    reservations: InMemoryAtomicExecutionReservations | None = None,
    risk: RiskLevel | None = None,
    allow_l4: bool = False,
) -> tuple[
    GovernedToolGateway,
    InMemoryDelegationStore,
    InMemoryGatewayAudit,
    InMemoryKillSwitchStore,
]:
    delegation = InMemoryDelegationStore()
    delegation.grant("delegation-1", action.tool_name, "subjects/")
    audit = InMemoryGatewayAudit()
    kill_switch = InMemoryKillSwitchStore()
    gateway = GovernedToolGateway(
        catalog=StaticToolCatalog(
            (
                ResolvedToolVersion(
                    action.tool_name,
                    action.tool_version,
                    "records-provider",
                    frozenset({"create"}),
                    ("subjects/",),
                    {
                        "type": "object",
                        "required": ["value"],
                        "properties": {"value": {"type": "string"}},
                        "additionalProperties": False,
                    },
                    risk or action.risk_level,
                    "records.write",
                ),
            )
        ),
        delegation=delegation,
        schema_validator=JsonSchemaValidator(),
        policy=DevelopmentPolicy(),
        kill_switch=kill_switch,
        reservations=reservations or InMemoryAtomicExecutionReservations(),
        credentials=EphemeralCredentialBroker(),
        egress=egress,
        audit=audit,
        allow_l4=allow_l4,
    )
    return gateway, delegation, audit, kill_switch


@pytest.mark.asyncio
async def test_action_mutation_after_approval_is_rejected_before_egress() -> None:
    action = make_action()
    approval = make_approval(action)
    mutated = replace(action, parameters=JsonObject.from_value({"value": "mutated"}))
    egress = FakeEgress()
    gateway, _, audit, _ = build_gateway(action, egress)

    result = await gateway.execute(make_context(action), mutated, approval, 1)

    assert result.action.status is ActionStatus.DENIED
    assert result.receipt.status is ToolResultStatus.REJECTED
    assert egress.calls == 0
    assert audit.records[-1].reason == "approval_invalid_expired_or_stale"


@pytest.mark.asyncio
async def test_expired_approval_policy_change_and_delegation_revocation_block() -> None:
    action = make_action()
    approval = make_approval(action)
    egress = FakeEgress()
    gateway, delegation, _, _ = build_gateway(action, egress)
    expired = replace(
        approval,
        created_at=datetime.now(UTC) - timedelta(minutes=10),
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    assert (await gateway.execute(make_context(action), action, expired, 1)).action.status is (
        ActionStatus.DENIED
    )
    assert (
        await gateway.execute(make_context(action, "v2"), action, approval, 1)
    ).action.status is ActionStatus.DENIED
    delegation.revoke("delegation-1")
    assert (await gateway.execute(make_context(action), action, approval, 1)).action.status is (
        ActionStatus.DENIED
    )
    assert egress.calls == 0


@pytest.mark.asyncio
async def test_concurrent_same_key_performs_one_side_effect_and_one_charge() -> None:
    action = make_action()
    approval = make_approval(action)
    reservations = InMemoryAtomicExecutionReservations()
    egress = FakeEgress()
    egress.delay = 0.02
    gateway, _, _, _ = build_gateway(action, egress, reservations=reservations)

    first, second = await asyncio.gather(
        gateway.execute(make_context(action), action, approval, 7),
        gateway.execute(make_context(action), action, approval, 7),
    )

    assert egress.calls == 1
    assert reservations.used[(str(action.tenant_id), str(action.run_id))] == 7
    assert {first.action.status, second.action.status} == {
        ActionStatus.SUCCEEDED,
        ActionStatus.UNKNOWN,
    }


@pytest.mark.asyncio
async def test_same_key_different_digest_conflicts() -> None:
    action = make_action()
    approval = make_approval(action)
    egress = FakeEgress()
    gateway, _, _, _ = build_gateway(action, egress)
    await gateway.execute(make_context(action), action, approval, 1)
    changed = replace(action, parameters=JsonObject.from_value({"value": "different"}))
    changed_approval = make_approval(changed)

    with pytest.raises(ValueError, match="different request digest"):
        await gateway.execute(make_context(action), changed, changed_approval, 1)
    assert egress.calls == 1


@pytest.mark.asyncio
async def test_timeout_is_unknown_and_is_never_blindly_retried() -> None:
    action = make_action()
    approval = make_approval(action)
    egress = FakeEgress()
    egress.timeout = True
    gateway, _, _, _ = build_gateway(action, egress)

    first = await gateway.execute(make_context(action), action, approval, 1)
    second = await gateway.execute(make_context(action), action, approval, 1)

    assert first.action.status is ActionStatus.UNKNOWN
    assert second.action.status is ActionStatus.UNKNOWN
    assert egress.calls == 1


@pytest.mark.asyncio
async def test_accepted_receipt_cannot_become_verified_success() -> None:
    action = make_action()
    approval = make_approval(action)
    egress = FakeEgress(ToolResultStatus.ACCEPTED)
    gateway, _, _, _ = build_gateway(action, egress)

    result = await gateway.execute(make_context(action), action, approval, 1)

    assert result.receipt.status is ToolResultStatus.ACCEPTED
    assert result.action.status is ActionStatus.UNKNOWN
    assert egress.verify_calls == 0


@pytest.mark.asyncio
async def test_server_risk_and_l4_are_not_caller_controlled() -> None:
    action = make_action(RiskLevel.L3_HIGH_IMPACT_WRITE)
    egress = FakeEgress()
    mismatch_gateway, _, _, _ = build_gateway(action, egress, risk=RiskLevel.L4_PRIVILEGED)
    mismatch = await mismatch_gateway.execute(
        make_context(action), action, make_approval(action), 1
    )
    assert mismatch.action.status is ActionStatus.DENIED

    l4_action = make_action(RiskLevel.L4_PRIVILEGED)
    l4_gateway, _, _, _ = build_gateway(l4_action, egress)
    denied = await l4_gateway.execute(
        make_context(l4_action), l4_action, make_approval(l4_action), 1
    )
    assert denied.action.status is ActionStatus.DENIED
    assert egress.calls == 0


@pytest.mark.asyncio
async def test_kill_switch_blocks_before_egress_and_records_audit() -> None:
    action = make_action()
    egress = FakeEgress()
    gateway, _, audit, kill_switch = build_gateway(action, egress)
    await kill_switch.activate(
        KillSwitchDimension.PROVIDER,
        "records-provider",
        "provider incident",
        "security-operator",
    )

    result = await gateway.execute(make_context(action), action, make_approval(action), 1)

    assert result.action.status is ActionStatus.DENIED
    assert egress.calls == 0
    assert audit.records[-1].reason == "kill_switch_active"
    assert audit.records[-1].status is ToolResultStatus.REJECTED


@pytest.mark.skipif(
    not os.getenv("AUTONOESIS_TEST_OPA_URL"),
    reason="requires an explicitly configured OPA component endpoint",
)
@pytest.mark.asyncio
async def test_real_opa_denies_l4_by_default_and_requires_write_approval() -> None:
    read = make_action(RiskLevel.L1_READ)
    write = make_action(RiskLevel.L2_REVERSIBLE_WRITE)
    privileged = make_action(RiskLevel.L4_PRIVILEGED)
    policy = OPAPolicyAdapter(os.environ["AUTONOESIS_TEST_OPA_URL"], "opa-action@1")

    read_decision = await policy.authorize(make_context(read), read)
    write_decision = await policy.authorize(make_context(write), write)
    privileged_decision = await policy.authorize(make_context(privileged), privileged)

    assert read_decision.allowed is True
    assert read_decision.requires_approval is False
    assert write_decision.allowed is True
    assert write_decision.requires_approval is True
    assert privileged_decision.allowed is False
    assert read_decision.policy_version == "opa-action@1"
