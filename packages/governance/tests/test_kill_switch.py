# mypy: disable_error_code = no-untyped-def
"""Tests for Kill Switch mechanism."""

from typing import Any
from uuid import uuid4

import pytest
from autonoesis_governance import InMemoryKillSwitchStore, KillSwitchDimension
from autonoesis_runtime import KillSwitchQuery


@pytest.fixture
def store() -> InMemoryKillSwitchStore:
    return InMemoryKillSwitchStore()


class TestInMemoryKillSwitchStore:
    @pytest.mark.asyncio
    async def test_activate_and_block(self, store) -> None:
        await store.activate(KillSwitchDimension.TENANT, "tenant-1", "security breach", "admin-1")

        blocked = await store.is_blocked(KillSwitchQuery(tenant_id="tenant-1"))
        assert blocked is True

    @pytest.mark.asyncio
    async def test_not_blocked_when_no_match(self, store) -> None:
        await store.activate(KillSwitchDimension.TENANT, "tenant-1", "reason", "admin-1")

        blocked = await store.is_blocked(KillSwitchQuery(tenant_id="tenant-2"))
        assert blocked is False

    @pytest.mark.asyncio
    async def test_deactivate_removes_block(self, store) -> None:
        await store.activate(KillSwitchDimension.TOOL, "dangerous-tool", "reason", "admin-1")
        assert await store.is_blocked(KillSwitchQuery(tool_name="dangerous-tool")) is True

        record = await store.deactivate(KillSwitchDimension.TOOL, "dangerous-tool")
        assert record is not None
        assert record.deactivated_at is not None

        assert await store.is_blocked(KillSwitchQuery(tool_name="dangerous-tool")) is False

    @pytest.mark.asyncio
    async def test_deactivate_nonexistent_returns_none(self, store) -> None:
        record = await store.deactivate(KillSwitchDimension.AGENT, "nonexistent")
        assert record is None

    @pytest.mark.asyncio
    async def test_list_active(self, store) -> None:
        await store.activate(KillSwitchDimension.AGENT, "agent-1", "reason", "admin")
        await store.activate(KillSwitchDimension.TOOL, "tool-1", "reason", "admin")

        active = await store.list_active()
        assert len(active) == 2

    @pytest.mark.asyncio
    async def test_deactivated_not_in_list(self, store) -> None:
        await store.activate(KillSwitchDimension.TOOL, "tool-x", "reason", "admin")
        await store.deactivate(KillSwitchDimension.TOOL, "tool-x")

        active = await store.list_active()
        assert len(active) == 0

    @pytest.mark.asyncio
    async def test_multiple_dimensions_in_query(self, store) -> None:
        await store.activate(KillSwitchDimension.AGENT, "blocked-agent", "reason", "admin")

        # Query matches on agent dimension
        blocked = await store.is_blocked(
            KillSwitchQuery(tenant_id="t1", agent_id="blocked-agent", tool_name="safe-tool")
        )
        assert blocked is True

    @pytest.mark.asyncio
    async def test_all_dimensions_supported(self, store) -> None:
        cases = [
            (KillSwitchDimension.TENANT, "t1", KillSwitchQuery(tenant_id="t1")),
            (KillSwitchDimension.AGENT, "a1", KillSwitchQuery(agent_id="a1")),
            (KillSwitchDimension.TOOL, "tool1", KillSwitchQuery(tool_name="tool1")),
            (KillSwitchDimension.OPERATION, "op1", KillSwitchQuery(operation="op1")),
            (KillSwitchDimension.PROVIDER, "p1", KillSwitchQuery(provider="p1")),
            (KillSwitchDimension.CAPABILITY_PACK, "cp1", KillSwitchQuery(capability_pack_id="cp1")),
        ]

        for dim, target, query in cases:
            store2 = InMemoryKillSwitchStore()
            await store2.activate(dim, target, "test", "admin")
            assert await store2.is_blocked(query) is True, f"failed for {dim.value}"
            await store2.deactivate(dim, target)
            assert await store2.is_blocked(query) is False, f"failed for {dim.value}"


class TestKillSwitchInGateway:
    @staticmethod
    def gateway(store: Any, action: Any, egress: Any) -> Any:
        from autonoesis_adapters import (
            DevelopmentPolicy,
            EphemeralCredentialBroker,
            InMemoryAtomicExecutionReservations,
            InMemoryDelegationStore,
            InMemoryGatewayAudit,
            JsonSchemaValidator,
            StaticToolCatalog,
        )
        from autonoesis_runtime import GovernedToolGateway, ResolvedToolVersion

        delegation = InMemoryDelegationStore()
        delegation.grant("delegation-1", action.tool_name, "resources/")
        return GovernedToolGateway(
            catalog=StaticToolCatalog(
                (
                    ResolvedToolVersion(
                        action.tool_name,
                        action.tool_version,
                        "provider",
                        frozenset({action.operation}),
                        ("resources/",),
                        {"type": "object"},
                        action.risk_level,
                        "tool.execute",
                    ),
                )
            ),
            delegation=delegation,
            schema_validator=JsonSchemaValidator(),
            policy=DevelopmentPolicy(),
            kill_switch=store,
            reservations=InMemoryAtomicExecutionReservations(),
            credentials=EphemeralCredentialBroker(),
            egress=egress,
            audit=InMemoryGatewayAudit(),
        )

    @pytest.mark.asyncio
    async def test_gateway_blocks_execution_when_kill_switch_active(self) -> None:
        from autonoesis_domain import (
            Action,
            JsonObject,
            RiskLevel,
        )
        from autonoesis_runtime import AuthorizationContext

        store = InMemoryKillSwitchStore()
        await store.activate(KillSwitchDimension.TOOL, "dangerous-tool", "blocked", "admin")

        action = Action(
            tenant_id=uuid4(),
            run_id=uuid4(),
            task_id=uuid4(),
            tool_name="dangerous-tool",
            tool_version="1.0.0",
            operation="execute",
            resource_scope="resources/res-1",
            idempotency_key="key-1",
            expected_effect="do something",
            risk_level=RiskLevel.L2_REVERSIBLE_WRITE,
            parameters=JsonObject.from_value({}),
        )
        gateway = self.gateway(store, action, object())
        context = AuthorizationContext(
            tenant_id=str(action.tenant_id),
            actor_id="actor-1",
            principal_id="principal-1",
            agent_id="agent-1",
            roles=("operator",),
            policy_version="v1",
            delegation_id="delegation-1",
        )

        result = await gateway.execute(context, action, None, 1)
        assert result.action.status.value == "denied"
        assert result.receipt.accepted is False
        assert ("reason", "kill_switch_active") in result.receipt.output

    @pytest.mark.asyncio
    async def test_gateway_proceeds_when_kill_switch_inactive(self) -> None:
        from autonoesis_domain import Action, JsonObject, RiskLevel
        from autonoesis_runtime import (
            AuthorizationContext,
            ToolReceipt,
            ToolResultStatus,
        )

        store = InMemoryKillSwitchStore()

        class FakeExecutor:
            calls = 0

            async def execute(
                self, action: Action, tool: object, credential: object
            ) -> ToolReceipt:
                del action, tool, credential
                self.calls += 1
                return ToolReceipt(
                    external_id="ext-1", status=ToolResultStatus.SUCCEEDED, output=()
                )

            async def verify(self, action: Action, tool: object, receipt: ToolReceipt) -> bool:
                del action, tool, receipt
                return True

        executor = FakeExecutor()

        action = Action(
            tenant_id=uuid4(),
            run_id=uuid4(),
            task_id=uuid4(),
            tool_name="safe-tool",
            tool_version="1.0.0",
            operation="execute",
            resource_scope="resources/res-1",
            idempotency_key="key-2",
            expected_effect="do something safe",
            risk_level=RiskLevel.L1_READ,
            parameters=JsonObject.from_value({}),
        )
        gateway = self.gateway(store, action, executor)
        context = AuthorizationContext(
            tenant_id=str(action.tenant_id),
            actor_id="actor-2",
            principal_id="principal-2",
            agent_id="agent-2",
            roles=("operator",),
            policy_version="v1",
            delegation_id="delegation-1",
        )

        result = await gateway.execute(context, action, None, 1)
        assert result.action.status.value == "succeeded"
        assert executor.calls == 1
