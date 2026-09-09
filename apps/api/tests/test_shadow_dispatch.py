"""Tests for deterministic tenant-isolated Shadow workflow dispatch."""

from typing import Any
from uuid import uuid4

import pytest
from autonoesis_api.shadow_dispatch import TemporalShadowWorkflowDispatcher
from autonoesis_runtime import IsolationRiskPool, TenantNamespaces
from temporalio.exceptions import WorkflowAlreadyStartedError


def test_shadow_workflow_id_is_deterministic_and_payload_bound() -> None:
    tenant_id = uuid4()
    deployment_id = uuid4()
    request_id = uuid4()
    digest = "a" * 64
    boundaries = TenantNamespaces(tenant_id)

    first = boundaries.shadow_workflow_id(deployment_id, request_id, digest)
    second = boundaries.shadow_workflow_id(deployment_id, request_id, digest)

    assert first == second
    assert tenant_id.hex in first
    assert str(deployment_id) in first
    assert first.endswith("a" * 16)


def test_shadow_workflow_id_rejects_untrusted_digest() -> None:
    with pytest.raises(ValueError, match="lowercase sha256"):
        TenantNamespaces(uuid4()).shadow_workflow_id(uuid4(), uuid4(), "../not-a-digest")


@pytest.mark.asyncio
async def test_temporal_dispatch_uses_high_risk_tenant_pool_and_exact_retry_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connections: list[tuple[str, str]] = []
    starts: list[dict[str, Any]] = []

    class FakeClient:
        @classmethod
        async def connect(cls, target: str, *, namespace: str) -> "FakeClient":
            connections.append((target, namespace))
            return cls()

        async def start_workflow(
            self, workflow: str, payload: dict[str, Any], **options: Any
        ) -> None:
            if starts:
                raise WorkflowAlreadyStartedError(options["id"], workflow)
            starts.append({"workflow": workflow, "payload": payload, **options})

    monkeypatch.setattr("autonoesis_api.shadow_dispatch.Client", FakeClient)
    tenant_id, deployment_id, request_id = uuid4(), uuid4(), uuid4()
    dispatcher = TemporalShadowWorkflowDispatcher("temporal.internal:7233")
    payload = {"request": "镜像", "priority": 2}

    first = await dispatcher.dispatch(
        tenant_id=tenant_id,
        deployment_id=deployment_id,
        request_id=request_id,
        input_payload=payload,
    )
    second = await dispatcher.dispatch(
        tenant_id=tenant_id,
        deployment_id=deployment_id,
        request_id=request_id,
        input_payload={"priority": 2, "request": "镜像"},
    )

    boundaries = TenantNamespaces(tenant_id)
    assert first == second
    assert connections == [
        (
            "temporal.internal:7233",
            boundaries.workflow_namespace(IsolationRiskPool.HIGH_RISK),
        ),
        (
            "temporal.internal:7233",
            boundaries.workflow_namespace(IsolationRiskPool.HIGH_RISK),
        ),
    ]
    assert starts[0]["workflow"] == "ShadowPairWorkflow"
    assert starts[0]["task_queue"] == boundaries.workflow_task_queue(IsolationRiskPool.HIGH_RISK)
    assert starts[0]["payload"]["request_ref"].startswith(f"shadow-request://{request_id}/")
