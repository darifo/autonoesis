from collections.abc import Callable
from uuid import uuid4

import pytest
from autonoesis_runtime import (
    IsolationRiskPool,
    TenantNamespaces,
    TenantTelemetryRecord,
)


def test_every_runtime_surface_has_a_non_overlapping_tenant_namespace() -> None:
    first_id, second_id = uuid4(), uuid4()
    first = TenantNamespaces(first_id)
    second = TenantNamespaces(second_id)

    projections: tuple[Callable[[TenantNamespaces], str], ...] = (
        lambda value: value.object_prefix("evidence"),
        lambda value: value.cache_key("same-key"),
        lambda value: value.search_index("same-index"),
        lambda value: value.vector_collection("same-index"),
        lambda value: value.message_topic("run-events"),
        lambda value: value.workflow_namespace(IsolationRiskPool.HIGH_RISK),
        lambda value: value.workflow_task_queue(IsolationRiskPool.HIGH_RISK),
        lambda value: value.worker_pool(IsolationRiskPool.HIGH_RISK),
        lambda value: value.evaluation_dataset("same-suite"),
        lambda value: value.audit_export_prefix(),
    )
    for projection in projections:
        assert projection(first) != projection(second)
    assert set(first.resource_registry("same-name", IsolationRiskPool.READ)) == {
        "object",
        "cache",
        "search",
        "vector",
        "topic",
        "workflow",
        "telemetry",
        "evaluation_dataset",
        "audit_export",
    }


def test_workflow_identity_is_tenant_and_run_scoped() -> None:
    tenant_id, other_tenant, run_id = uuid4(), uuid4(), uuid4()
    assert TenantNamespaces(tenant_id).workflow_id(run_id) != TenantNamespaces(
        other_tenant
    ).workflow_id(run_id)
    assert IsolationRiskPool.from_risk_tier("critical") is IsolationRiskPool.HIGH_RISK
    assert IsolationRiskPool.from_risk_tier("medium") is IsolationRiskPool.WRITE


def test_telemetry_export_fails_closed_for_another_tenant() -> None:
    tenant_id = uuid4()
    signal = TenantTelemetryRecord(tenant_id, "trace", "trace-1", {"operation": "plan"})

    exported = signal.for_export(tenant_id)
    assert exported["attributes"] == {"autonoesis.tenant.id": str(tenant_id)}
    with pytest.raises(LookupError, match="not found"):
        signal.for_export(uuid4())
