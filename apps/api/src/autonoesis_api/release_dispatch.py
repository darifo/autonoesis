"""Tenant-isolated Temporal dispatch for governed release commands."""

from __future__ import annotations

import json
from contextlib import suppress
from hashlib import sha256
from typing import Protocol
from uuid import UUID

from autonoesis_runtime import IsolationRiskPool, TenantNamespaces
from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError


class ReleaseCommandDispatcher(Protocol):
    async def dispatch(
        self,
        *,
        tenant_id: UUID,
        action: str,
        command: dict[str, object],
        target_id: UUID,
    ) -> str: ...


class TemporalReleaseCommandDispatcher:
    """Start idempotent Release Executor workflows in the high-risk pool."""

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
        action: str,
        command: dict[str, object],
        target_id: UUID,
    ) -> str:
        serialized = json.dumps(command, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        command_digest = sha256(serialized.encode()).hexdigest()
        boundaries = TenantNamespaces(tenant_id)
        workflow_id = boundaries.release_workflow_id(action, target_id, command_digest)
        if self._tenant_isolated:
            namespace = boundaries.workflow_namespace(IsolationRiskPool.HIGH_RISK)
            task_queue = boundaries.workflow_task_queue(IsolationRiskPool.HIGH_RISK)
        else:
            namespace = self._shared_namespace
            task_queue = self._shared_task_queue
        client = await Client.connect(self._target, namespace=namespace)
        # An identical retried command must never execute twice; the durable
        # workflow (and the state machine it drives) remains the only executor.
        with suppress(WorkflowAlreadyStartedError):
            await client.start_workflow(
                "ReleaseExecutionWorkflow",
                {"tenant_id": str(tenant_id), "action": action, **command},
                id=workflow_id,
                task_queue=task_queue,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            )
        return workflow_id


__all__ = ["ReleaseCommandDispatcher", "TemporalReleaseCommandDispatcher"]
