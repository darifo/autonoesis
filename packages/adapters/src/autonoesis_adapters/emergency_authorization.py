"""Temporary Break-glass authorization stores."""

from datetime import UTC, datetime
from uuid import UUID

from autonoesis_domain import TemporaryAuthorization
from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class InMemoryTemporaryAuthorizationStore:
    def __init__(self) -> None:
        self._items: dict[UUID, TemporaryAuthorization] = {}

    async def issue(self, authorization: TemporaryAuthorization) -> None:
        self._items[authorization.authorization_id] = authorization

    async def require_active(
        self, tenant_id: UUID, authorization_id: UUID, principal_id: UUID, scope: str
    ) -> TemporaryAuthorization:
        item = self._items.get(authorization_id)
        if (
            item is None
            or item.tenant_id != tenant_id
            or item.principal_id != principal_id
            or item.scope != scope
            or item.expires_at <= datetime.now(UTC)
        ):
            raise PermissionError("active scoped Break-glass authorization is required")
        return item

    async def review(
        self, tenant_id: UUID, authorization_id: UUID, reviewer: UUID
    ) -> TemporaryAuthorization:
        item = self._items.get(authorization_id)
        if item is None or item.tenant_id != tenant_id:
            raise LookupError("temporary authorization was not found")
        reviewed = item.review(reviewer)
        self._items[authorization_id] = reviewed
        return reviewed


class PostgreSQLTemporaryAuthorizationStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @staticmethod
    async def _scope(session: AsyncSession, tenant_id: UUID) -> None:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )

    async def issue(self, authorization: TemporaryAuthorization) -> None:
        async with self._sessions.begin() as session:
            await self._scope(session, authorization.tenant_id)
            await session.execute(
                text(
                    "INSERT INTO temporary_authorizations "
                    "(id, tenant_id, principal_id, scope, reason, expires_at, created_at) "
                    "VALUES (:id, :tenant_id, :principal_id, :scope, :reason, :expires_at, "
                    ":created_at)"
                ),
                {
                    "id": str(authorization.authorization_id),
                    "tenant_id": str(authorization.tenant_id),
                    "principal_id": str(authorization.principal_id),
                    "scope": authorization.scope,
                    "reason": authorization.reason,
                    "expires_at": authorization.expires_at,
                    "created_at": authorization.created_at,
                },
            )

    async def require_active(
        self, tenant_id: UUID, authorization_id: UUID, principal_id: UUID, scope: str
    ) -> TemporaryAuthorization:
        async with self._sessions() as session:
            await self._scope(session, tenant_id)
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM temporary_authorizations WHERE tenant_id=:tenant_id "
                            "AND id=:id AND principal_id=:principal_id AND scope=:scope "
                            "AND expires_at > now()"
                        ),
                        {
                            "tenant_id": str(tenant_id),
                            "id": str(authorization_id),
                            "principal_id": str(principal_id),
                            "scope": scope,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise PermissionError("active scoped Break-glass authorization is required")
        return self._from_row(row)

    async def review(
        self, tenant_id: UUID, authorization_id: UUID, reviewer: UUID
    ) -> TemporaryAuthorization:
        async with self._sessions.begin() as session:
            await self._scope(session, tenant_id)
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM temporary_authorizations WHERE tenant_id=:tenant_id "
                            "AND id=:id FOR UPDATE"
                        ),
                        {"tenant_id": str(tenant_id), "id": str(authorization_id)},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise LookupError("temporary authorization was not found")
            reviewed = self._from_row(row).review(reviewer)
            await session.execute(
                text(
                    "UPDATE temporary_authorizations SET reviewed_by=:reviewer, "
                    "reviewed_at=:reviewed_at WHERE tenant_id=:tenant_id AND id=:id"
                ),
                {
                    "reviewer": str(reviewer),
                    "reviewed_at": reviewed.reviewed_at,
                    "tenant_id": str(tenant_id),
                    "id": str(authorization_id),
                },
            )
        return reviewed

    @staticmethod
    def _from_row(row: RowMapping) -> TemporaryAuthorization:
        values = dict(row)
        return TemporaryAuthorization(
            tenant_id=UUID(values["tenant_id"]),
            principal_id=UUID(values["principal_id"]),
            scope=values["scope"],
            reason=values["reason"],
            expires_at=values["expires_at"],
            authorization_id=UUID(values["id"]),
            created_at=values["created_at"],
            reviewed_by=UUID(values["reviewed_by"]) if values["reviewed_by"] else None,
            reviewed_at=values["reviewed_at"],
        )
