"""Real PostgreSQL checks for live delegation revocation and emergency review."""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from autonoesis_adapters import (
    PostgreSQLDelegationStore,
    PostgreSQLTemporaryAuthorizationStore,
)
from autonoesis_domain import Action, DelegationGrant, JsonObject, RiskLevel, TemporaryAuthorization
from autonoesis_runtime import AuthorizationContext, ResolvedToolVersion
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = pytest.mark.skipif(
    not os.getenv("AUTONOESIS_TEST_DATABASE_URL")
    or not os.getenv("AUTONOESIS_TEST_ADMIN_DATABASE_URL"),
    reason="requires migrated PostgreSQL app and admin roles",
)


@pytest.mark.asyncio
async def test_revocation_and_breakglass_review_use_postgresql_authority() -> None:
    tenant, grantor, delegate, reviewer = uuid4(), uuid4(), uuid4(), uuid4()
    admin = create_async_engine(os.environ["AUTONOESIS_TEST_ADMIN_DATABASE_URL"])
    engine = create_async_engine(os.environ["AUTONOESIS_TEST_DATABASE_URL"])
    try:
        async with admin.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO tenants (id, name, created_at) VALUES "
                    "(:id, :name, CURRENT_TIMESTAMP) ON CONFLICT (id) DO NOTHING"
                ),
                {"id": str(tenant), "name": f"p102-{tenant}"},
            )
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        delegations = PostgreSQLDelegationStore(sessions)
        grant = DelegationGrant(
            tenant,
            grantor,
            delegate,
            "records",
            "subjects/42",
            "resolve-case",
            datetime.now(UTC) + timedelta(minutes=5),
        )
        await delegations.grant(grant)
        action = Action(
            tenant,
            uuid4(),
            uuid4(),
            "records",
            "1.0.0",
            "update",
            "subjects/42/contact",
            JsonObject.from_value({"status": "verified"}),
            RiskLevel.L2_REVERSIBLE_WRITE,
            "p102-delegation",
            "contact becomes verified",
        )
        tool = ResolvedToolVersion(
            "records",
            "1.0.0",
            "test",
            frozenset({"update"}),
            ("subjects/",),
            {"type": "object"},
            RiskLevel.L2_REVERSIBLE_WRITE,
            "records.write",
        )
        context = AuthorizationContext(
            str(tenant),
            str(uuid4()),
            str(delegate),
            "agent-1",
            ("operator",),
            "policy@1",
            str(grant.delegation_id),
            purpose="resolve-case",
        )
        assert await delegations.authorize(context, action, tool)
        await delegations.revoke(tenant, grant.delegation_id)
        assert not await delegations.authorize(context, action, tool)

        emergency = PostgreSQLTemporaryAuthorizationStore(sessions)
        authorization = TemporaryAuthorization(
            tenant,
            delegate,
            "platform.kill_switch",
            "verified incident response",
            datetime.now(UTC) + timedelta(minutes=10),
        )
        await emergency.issue(authorization)
        assert (
            await emergency.require_active(
                tenant,
                authorization.authorization_id,
                delegate,
                "platform.kill_switch",
            )
        ).principal_id == delegate
        reviewed = await emergency.review(tenant, authorization.authorization_id, reviewer)
        assert reviewed.reviewed_by == reviewer
    finally:
        await engine.dispose()
        await admin.dispose()
