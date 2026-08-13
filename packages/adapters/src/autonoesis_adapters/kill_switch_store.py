"""Tenant-scoped PostgreSQL Kill Switch store."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from autonoesis_runtime import (
    KillSwitchDimension,
    KillSwitchQuery,
    KillSwitchRecord,
)
from sqlalchemy import and_, func, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from autonoesis_adapters.persistence import kill_switches
from autonoesis_adapters.persistence_schema import (
    breakglass_alerts,
    platform_audit_events,
    platform_kill_switches,
)


class SqlKillSwitchStore:
    """Kill switch store backed by tenant-isolated PostgreSQL rows."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        tenant_id: UUID | None = None,
    ) -> None:
        self._sessions = sessions
        self._tenant_id = tenant_id

    def for_tenant(self, tenant_id: UUID) -> SqlKillSwitchStore:
        return SqlKillSwitchStore(self._sessions, tenant_id)

    async def _scope(self, session: AsyncSession, tenant_id: UUID) -> None:
        await session.execute(select(func.set_config("app.tenant_id", str(tenant_id), True)))

    def _required_tenant(self) -> UUID:
        if self._tenant_id is None:
            raise ValueError("a tenant-scoped kill switch store is required")
        return self._tenant_id

    async def is_blocked(self, query: KillSwitchQuery) -> bool:
        tenant_id = self._tenant_id or (UUID(query.tenant_id) if query.tenant_id else None)
        if tenant_id is None:
            raise ValueError("kill switch query requires tenant_id")
        conditions: list[Any] = []
        for dimension, target in query.dimensions():
            conditions.append(
                and_(
                    kill_switches.c.dimension == dimension.value,
                    kill_switches.c.target == target,
                    kill_switches.c.deactivated_at.is_(None),
                )
            )
        if not conditions:
            return False
        async with self._sessions() as session:
            platform_blocked = await session.scalar(
                select(platform_kill_switches.c.id)
                .where(platform_kill_switches.c.deactivated_at.is_(None))
                .limit(1)
            )
            if platform_blocked is not None:
                return True
            await self._scope(session, tenant_id)
            result = await session.execute(
                select(kill_switches.c.id)
                .where(kill_switches.c.tenant_id == str(tenant_id), or_(*conditions))
                .limit(1)
            )
            return result.scalar() is not None

    async def activate(
        self,
        dimension: KillSwitchDimension,
        target: str,
        reason: str,
        activated_by: str,
    ) -> KillSwitchRecord:
        tenant_id = self._required_tenant()
        if dimension is KillSwitchDimension.PLATFORM:
            raise PermissionError("platform switch requires the Break-glass store")
        now = datetime.now(UTC)
        record = KillSwitchRecord(
            kill_switch_id=uuid4(),
            dimension=dimension,
            target=target,
            reason=reason,
            activated_by=activated_by,
            activated_at=now,
        )
        async with self._sessions.begin() as session:
            await self._scope(session, tenant_id)
            await session.execute(
                kill_switches.insert().values(
                    id=str(record.kill_switch_id),
                    tenant_id=str(tenant_id),
                    dimension=dimension.value,
                    target=target,
                    reason=reason,
                    activated_by=activated_by,
                    deactivated_at=None,
                    optimistic_version=1,
                    created_at=now,
                )
            )
        return record

    async def deactivate(
        self,
        dimension: KillSwitchDimension,
        target: str,
    ) -> KillSwitchRecord | None:
        tenant_id = self._required_tenant()
        if dimension is KillSwitchDimension.PLATFORM:
            raise PermissionError("platform switch requires the Break-glass store")
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            await self._scope(session, tenant_id)
            row = (
                (
                    await session.execute(
                        select(kill_switches)
                        .where(
                            kill_switches.c.tenant_id == str(tenant_id),
                            kill_switches.c.dimension == dimension.value,
                            kill_switches.c.target == target,
                            kill_switches.c.deactivated_at.is_(None),
                        )
                        .limit(1)
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            await session.execute(
                update(kill_switches)
                .where(
                    kill_switches.c.id == row["id"],
                    kill_switches.c.tenant_id == str(tenant_id),
                )
                .values(deactivated_at=now)
            )
            return KillSwitchRecord(
                kill_switch_id=UUID(row["id"]),
                dimension=KillSwitchDimension(row["dimension"]),
                target=row["target"],
                reason=row["reason"],
                activated_by=row["activated_by"],
                activated_at=row["created_at"],
                deactivated_at=now,
            )

    async def list_active(self) -> tuple[KillSwitchRecord, ...]:
        tenant_id = self._required_tenant()
        async with self._sessions() as session:
            await self._scope(session, tenant_id)
            rows = (
                (
                    await session.execute(
                        select(kill_switches).where(
                            kill_switches.c.tenant_id == str(tenant_id),
                            kill_switches.c.deactivated_at.is_(None),
                        )
                    )
                )
                .mappings()
                .all()
            )
            return tuple(
                KillSwitchRecord(
                    kill_switch_id=UUID(row["id"]),
                    dimension=KillSwitchDimension(row["dimension"]),
                    target=row["target"],
                    reason=row["reason"],
                    activated_by=row["activated_by"],
                    activated_at=row["created_at"],
                )
                for row in rows
            )


class SqlPlatformKillSwitchStore:
    """Break-glass-only platform switch with a separate append-only audit surface."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def activate(
        self,
        reason: str,
        actor_id: UUID,
        principal_id: UUID,
        correlation_id: UUID,
    ) -> KillSwitchRecord:
        now, switch_id = datetime.now(UTC), uuid4()
        async with self._sessions.begin() as session:
            existing = await session.scalar(
                select(platform_kill_switches.c.id)
                .where(platform_kill_switches.c.deactivated_at.is_(None))
                .limit(1)
            )
            if existing is not None:
                raise ValueError("the platform kill switch is already active")
            await session.execute(
                insert(platform_kill_switches).values(
                    id=str(switch_id),
                    target="platform",
                    reason=reason,
                    activated_by=str(actor_id),
                    deactivated_at=None,
                    created_at=now,
                )
            )
            await self._audit(
                session,
                "platform.kill_switch.activated",
                switch_id,
                reason,
                actor_id,
                principal_id,
                correlation_id,
                now,
            )
        return KillSwitchRecord(
            switch_id,
            KillSwitchDimension.PLATFORM,
            "platform",
            reason,
            str(actor_id),
            now,
        )

    async def deactivate(
        self,
        reason: str,
        actor_id: UUID,
        principal_id: UUID,
        correlation_id: UUID,
    ) -> KillSwitchRecord | None:
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            row = (
                (
                    await session.execute(
                        select(platform_kill_switches)
                        .where(platform_kill_switches.c.deactivated_at.is_(None))
                        .with_for_update()
                        .limit(1)
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return None
            await session.execute(
                update(platform_kill_switches)
                .where(platform_kill_switches.c.id == row["id"])
                .values(deactivated_at=now)
            )
            await self._audit(
                session,
                "platform.kill_switch.deactivated",
                UUID(row["id"]),
                reason,
                actor_id,
                principal_id,
                correlation_id,
                now,
            )
        return KillSwitchRecord(
            UUID(row["id"]),
            KillSwitchDimension.PLATFORM,
            "platform",
            row["reason"],
            row["activated_by"],
            row["created_at"],
            now,
        )

    async def list_audit(self) -> tuple[dict[str, Any], ...]:
        async with self._sessions() as session:
            rows = (
                (
                    await session.execute(
                        select(platform_audit_events).order_by(
                            platform_audit_events.c.created_at,
                            platform_audit_events.c.id,
                        )
                    )
                )
                .mappings()
                .all()
            )
            return tuple(dict(row) for row in rows)

    @staticmethod
    async def _audit(
        session: AsyncSession,
        event_type: str,
        object_id: UUID,
        reason: str,
        actor_id: UUID,
        principal_id: UUID,
        correlation_id: UUID,
        created_at: datetime,
    ) -> None:
        await session.execute(
            insert(platform_audit_events).values(
                id=str(uuid4()),
                actor_id=str(actor_id),
                principal_id=str(principal_id),
                event_type=event_type,
                object_id=str(object_id),
                correlation_id=str(correlation_id),
                reason=reason,
                created_at=created_at,
            )
        )
        ticket = reason.partition("ticket=")[2].partition(";")[0].strip() or "unavailable"
        await session.execute(
            insert(breakglass_alerts).values(
                id=str(uuid4()),
                authorization_id=str(object_id),
                principal_id=str(principal_id),
                ticket=ticket,
                event_type=f"security.alert.{event_type}",
                created_at=created_at,
                acknowledged_by=None,
                acknowledged_at=None,
            )
        )
