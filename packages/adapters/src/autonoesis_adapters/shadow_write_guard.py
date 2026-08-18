"""Execution-time shadow write suppression backed by authoritative deployment state."""

from __future__ import annotations

from uuid import UUID

from autonoesis_domain import DeploymentStatus

from autonoesis_adapters.memory import InMemoryPlatformStore
from autonoesis_adapters.platform_store import PostgreSQLPlatformStore

PlatformStore = PostgreSQLPlatformStore | InMemoryPlatformStore


class SqlShadowWriteGuard:
    """Refuses write actions for Runs bound to a shadow deployment.

    A Run carries an optional ``deployment_id`` (ADR-0030). When that deployment
    is still in Shadow, its Runs must produce no external side effects, so any
    L2+ write action fails closed. Runs without a deployment, or bound to a
    Canary/Stable deployment, are unaffected.
    """

    def __init__(self, store: PlatformStore) -> None:
        self._store = store

    async def assert_writable(self, tenant_id: UUID, run_id: UUID) -> None:
        run = await self._store.get_run(tenant_id, run_id)
        if run.deployment_id is None:
            return
        deployment = await self._store.get_deployment(tenant_id, run.deployment_id)
        if deployment.status is DeploymentStatus.SHADOW:
            raise PermissionError(
                "shadow deployment cannot produce external side effects: "
                f"run {run_id} is bound to shadow deployment {deployment.deployment_id}"
            )


__all__ = ["SqlShadowWriteGuard"]
