"""PostgreSQL-backed Kill Switch store."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from autonoesis_runtime import (
    KillSwitchDimension,
    KillSwitchQuery,
    KillSwitchRecord,
)
from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from autonoesis_adapters.persistence import kill_switches


class SqlKillSwitchStore:
    """Kill switch store backed by the ``kill_switches`` PostgreSQL table."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def is_blocked(self, query: KillSwitchQuery) -> bool:
        conditions: list[Any] = []
        for dim, target in query.dimensions():
            conditions.append(
                and_(
                    kill_switches.c.dimension == dim.value,
                    kill_switches.c.target == target,
                    kill_switches.c.deactivated_at.is_(None),
                )
            )
        if not conditions:
            return False
        async with self._sessions() as session:
            result = await session.execute(
                select(kill_switches.c.id).where(or_(*conditions)).limit(1)
            )
            return result.scalar() is not None

    async def activate(
        self,
        dimension: KillSwitchDimension,
        target: str,
        reason: str,
        activated_by: str,
    ) -> KillSwitchRecord:
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
            await session.execute(
                kill_switches.insert().values(
                    id=str(record.kill_switch_id),
                    tenant_id="00000000-0000-0000-0000-000000000000",
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
        now = datetime.now(UTC)
        async with self._sessions.begin() as session:
            row = (
                (
                    await session.execute(
                        select(kill_switches)
                        .where(
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
                .where(kill_switches.c.id == row["id"])
                .values(deactivated_at=now)
            )

            return KillSwitchRecord(
                kill_switch_id=row["id"],
                dimension=KillSwitchDimension(row["dimension"]),
                target=row["target"],
                reason=row["reason"],
                activated_by=row["activated_by"],
                activated_at=row["created_at"],
                deactivated_at=now,
            )

    async def list_active(self) -> tuple[KillSwitchRecord, ...]:
        async with self._sessions() as session:
            rows = (
                (
                    await session.execute(
                        select(kill_switches).where(kill_switches.c.deactivated_at.is_(None))
                    )
                )
                .mappings()
                .all()
            )
            return tuple(
                KillSwitchRecord(
                    kill_switch_id=row["id"],
                    dimension=KillSwitchDimension(row["dimension"]),
                    target=row["target"],
                    reason=row["reason"],
                    activated_by=row["activated_by"],
                    activated_at=row["created_at"],
                )
                for row in rows
            )
