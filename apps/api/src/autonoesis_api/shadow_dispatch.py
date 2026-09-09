"""Tenant-isolated Temporal dispatch for live Shadow request mirrors."""

from __future__ import annotations

import json
from contextlib import suppress
from hashlib import sha256
from typing import Any, Protocol
from uuid import UUID

from autonoesis_runtime import IsolationRiskPool, TenantNamespaces
from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError


class ShadowWorkflowDispatcher(Protocol):
    async def dispatch(
        self,
        *,
        tenant_id: UUID,
        deployment_id: UUID,
        request_id: UUID,
        input_payload: dict[str, Any],
    ) -> str: ...


class TemporalShadowWorkflowDispatcher:
    """Start idempotent per-request Shadow workflows in the high-risk pool."""

    def __init__(
        self,
        target: str,
        *,
        tenant_isolated: bool = True,
        shared_namespace: str = "default",
        shared_task_queue: str = "autonoesis",
    ) -> None:
        self._target = target
        self._tenant_isolated = tenant_isolated
        self._shared_namespace = shared_namespace
        self._shared_task_queue = shared_task_queue

    async def dispatch(
        self,
        *,
        tenant_id: UUID,
        deployment_id: UUID,
        request_id: UUID,
        input_payload: dict[str, Any],
    ) -> str:
        serialized = json.dumps(
            input_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        payload_digest = sha256(serialized.encode()).hexdigest()
        boundaries = TenantNamespaces(tenant_id)
        request_ref = f"shadow-request://{request_id}/{payload_digest}"
        workflow_id = boundaries.shadow_workflow_id(deployment_id, request_id, payload_digest)
        if self._tenant_isolated:
            namespace = boundaries.workflow_namespace(IsolationRiskPool.HIGH_RISK)
            task_queue = boundaries.workflow_task_queue(IsolationRiskPool.HIGH_RISK)
        else:
            namespace = self._shared_namespace
            task_queue = self._shared_task_queue
        client = await Client.connect(self._target, namespace=namespace)
        # Completed exact retries are also idempotent: never execute Stable
        # again, and return the authoritative deterministic Workflow ID.
        with suppress(WorkflowAlreadyStartedError):
            await client.start_workflow(
                "ShadowPairWorkflow",
                {
                    "tenant_id": str(tenant_id),
                    "deployment_id": str(deployment_id),
                    "request_ref": request_ref,
                    "input_payload": input_payload,
                },
                id=workflow_id,
                task_queue=task_queue,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            )
        return workflow_id


__all__ = ["ShadowWorkflowDispatcher", "TemporalShadowWorkflowDispatcher"]
