"""Real PostgreSQL authority checks for the P1-03 Memory ledger and deletion graph."""

import os
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from autonoesis_adapters import PostgreSQLPlatformStore
from autonoesis_adapters.persistence_schema import (
    memory_deletion_edges,
    memory_ledger,
    vector_index_projections,
)
from autonoesis_domain import MemoryRecord, MemoryStatus, TrustLevel
from sqlalchemy import func, insert, select, text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.skipif(
    not os.getenv("AUTONOESIS_TEST_DATABASE_URL")
    or not os.getenv("AUTONOESIS_TEST_ADMIN_DATABASE_URL"),
    reason="requires migrated PostgreSQL app and admin roles",
)


def memory(tenant_id: UUID, content: str) -> MemoryRecord:
    return MemoryRecord(
        tenant_id=tenant_id,
        scope="customer-support",
        content=content,
        provenance=("authority://crm/customer-42",),
        confidence=0.95,
        expires_at=datetime.now(UTC) + timedelta(days=1),
        approved_by=uuid4(),
        source_trust=TrustLevel.AUTHORITATIVE,
    )


@pytest.mark.asyncio
async def test_write_gate_ledger_and_recursive_deletion_are_authoritative() -> None:
    tenant_id = uuid4()
    admin = create_async_engine(os.environ["AUTONOESIS_TEST_ADMIN_DATABASE_URL"])
    store = PostgreSQLPlatformStore.from_url(os.environ["AUTONOESIS_TEST_DATABASE_URL"])
    try:
        async with admin.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO tenants (id, name, created_at) VALUES "
                    "(:id, :name, CURRENT_TIMESTAMP) ON CONFLICT (id) DO NOTHING"
                ),
                {"id": str(tenant_id), "name": f"p103-{tenant_id}"},
            )
        observation = memory(tenant_id, "customer prefers email")
        with pytest.raises(PermissionError, match="Write Gate"):
            await store.add_memory(observation)

        parent = observation.stabilize()
        child = memory(tenant_id, "derived outreach preference").stabilize()
        await store.add_memory(parent)
        await store.add_memory(child)
        async with store.repository.sessions.begin() as session:
            await session.execute(select(func.set_config("app.tenant_id", str(tenant_id), True)))
            await session.execute(
                insert(memory_deletion_edges).values(
                    id=str(uuid4()),
                    tenant_id=str(tenant_id),
                    parent_memory_id=str(parent.memory_id),
                    child_memory_id=str(child.memory_id),
                    optimistic_version=1,
                    created_at=datetime.now(UTC),
                )
            )
            await session.execute(
                insert(vector_index_projections).values(
                    id=str(uuid4()),
                    tenant_id=str(tenant_id),
                    memory_id=str(child.memory_id),
                    content_digest=sha256(child.content.encode()).hexdigest(),
                    index_version="test-index@1",
                    optimistic_version=1,
                    created_at=datetime.now(UTC),
                )
            )

        assert await store.repository.delete_memory(tenant_id, parent.memory_id, uuid4()) == 2
        assert await store.list_memory(tenant_id) == ()
        async with store.repository.sessions() as session:
            await session.execute(select(func.set_config("app.tenant_id", str(tenant_id), True)))
            kinds = (
                (
                    await session.execute(
                        select(memory_ledger.c.kind).where(
                            memory_ledger.c.tenant_id == str(tenant_id)
                        )
                    )
                )
                .scalars()
                .all()
            )
            projections = await session.scalar(
                select(func.count()).select_from(vector_index_projections)
            )
        assert kinds.count("write") == 2
        assert kinds.count("delete") == 2
        assert projections == 0
        assert parent.status is MemoryStatus.STABLE
    finally:
        await store.close()
        await admin.dispose()
