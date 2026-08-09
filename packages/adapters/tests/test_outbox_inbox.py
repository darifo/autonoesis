# mypy: disable_error_code = no-untyped-def
"""Tests for OutboxWriter, OutboxRelay, and InboxConsumer."""

import asyncio
from typing import Any
from uuid import uuid4

import pytest
from autonoesis_adapters.outbox import InboxConsumer, OutboxRelay, OutboxWriter
from autonoesis_adapters.persistence import inbox, metadata, outbox
from autonoesis_contracts import MessageEnvelope
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield eng
    await eng.dispose()


def _make_envelope(**overrides: object) -> MessageEnvelope:
    defaults = {
        "schema": "ai.example.agent.goal.activated.v1",
        "schema_version": 1,
        "tenant_id": uuid4(),
        "actor_id": uuid4(),
        "payload": {"goal_id": str(uuid4()), "status": "active"},
    }
    defaults.update({k: v for k, v in overrides.items() if v is not None})
    return MessageEnvelope(**defaults)  # type: ignore[arg-type]


class TestOutboxWriter:
    @pytest.mark.asyncio
    async def test_publish_inserts_row(self, engine) -> None:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        envelope = _make_envelope()

        async with sessions.begin() as session:
            await OutboxWriter.publish(session, envelope)

        async with sessions() as session:
            rows = (await session.execute(select(outbox))).mappings().all()
        assert len(rows) == 1
        assert rows[0]["schema"] == envelope.schema
        assert rows[0]["published_at"] is None

    @pytest.mark.asyncio
    async def test_publish_rolls_back_with_transaction(self, engine) -> None:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        envelope = _make_envelope()

        with pytest.raises(RuntimeError):
            async with sessions.begin() as session:
                await OutboxWriter.publish(session, envelope)
                raise RuntimeError("forced rollback")

        async with sessions() as session:
            rows = (await session.execute(select(outbox))).mappings().all()
        assert len(rows) == 0

    @pytest.mark.asyncio
    async def test_publish_multiple_events(self, engine) -> None:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        envelopes = [_make_envelope() for _ in range(3)]

        async with sessions.begin() as session:
            for env in envelopes:
                await OutboxWriter.publish(session, env)

        async with sessions() as session:
            rows = (await session.execute(select(outbox))).mappings().all()
        assert len(rows) == 3


class TestOutboxRelay:
    @pytest.mark.asyncio
    async def test_relay_publishes_and_marks(self, engine) -> None:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        envelope = _make_envelope()

        async with sessions.begin() as session:
            await OutboxWriter.publish(session, envelope)

        published: list[MessageEnvelope] = []

        async def publisher(env: MessageEnvelope) -> None:
            published.append(env)

        relay = OutboxRelay(engine, publisher)
        count = await relay.poll_and_publish()

        assert count == 1
        assert len(published) == 1
        assert published[0].message_id == envelope.message_id

        # Row is now marked as published
        async with sessions() as session:
            row = (await session.execute(select(outbox))).mappings().one()
        assert row["published_at"] is not None

    @pytest.mark.asyncio
    async def test_relay_skips_already_published(self, engine) -> None:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        envelope = _make_envelope()

        async with sessions.begin() as session:
            await OutboxWriter.publish(session, envelope)

        published: list[MessageEnvelope] = []

        async def publisher(env: MessageEnvelope) -> None:
            published.append(env)

        relay = OutboxRelay(engine, publisher)
        await relay.poll_and_publish()
        assert len(published) == 1

        # Second poll should find nothing new
        count = await relay.poll_and_publish()
        assert count == 0
        assert len(published) == 1

    @pytest.mark.asyncio
    async def test_relay_handles_publisher_failure(self, engine) -> None:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        envelope = _make_envelope()

        async with sessions.begin() as session:
            await OutboxWriter.publish(session, envelope)

        call_count = 0

        async def failing_publisher(env: MessageEnvelope) -> None:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("publish failed")

        relay = OutboxRelay(engine, failing_publisher)
        count = await relay.poll_and_publish()
        assert count == 0  # nothing successfully published
        assert call_count == 1

        # Row remains unpublished for retry
        async with sessions() as session:
            row = (await session.execute(select(outbox))).mappings().one()
        assert row["published_at"] is None


class TestInboxConsumer:
    @pytest.mark.asyncio
    async def test_receive_processes_once(self, engine) -> None:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        consumer = InboxConsumer(sessions)
        message_id = str(uuid4())

        handled: list[str] = []

        async def handler(payload: dict[str, Any]) -> None:
            handled.append(payload["message_id"])

        result1 = await consumer.receive(message_id, handler)
        assert result1 is True
        assert handled == [message_id]

        # Duplicate should be skipped
        result2 = await consumer.receive(message_id, handler)
        assert result2 is False
        assert handled == [message_id]  # handler not called again

    @pytest.mark.asyncio
    async def test_receive_rolls_back_on_handler_failure(self, engine) -> None:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        consumer = InboxConsumer(sessions)
        message_id = str(uuid4())

        async def failing_handler(payload: dict[str, Any]) -> None:
            raise RuntimeError("handler failed")

        with pytest.raises(RuntimeError, match="handler failed"):
            await consumer.receive(message_id, failing_handler)

        # Inbox slot should not exist (rolled back)
        async with sessions() as session:
            row = (
                await session.execute(select(inbox).where(inbox.c.message_id == message_id))
            ).one_or_none()
        assert row is None

        # Retry should succeed
        async def success_handler(payload: dict[str, Any]) -> None:
            pass

        result = await consumer.receive(message_id, success_handler)
        assert result is True

    @pytest.mark.asyncio
    async def test_receive_multiple_different_messages(self, engine) -> None:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        consumer = InboxConsumer(sessions)

        handled: list[str] = []

        async def handler(payload: dict[str, Any]) -> None:
            handled.append(payload["message_id"])

        for _ in range(5):
            await consumer.receive(str(uuid4()), handler)

        assert len(handled) == 5

    @pytest.mark.asyncio
    async def test_concurrent_receive_same_message(self, engine) -> None:
        """Two concurrent receives for the same message_id: only one succeeds."""
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        consumer = InboxConsumer(sessions)
        message_id = str(uuid4())

        handled: list[str] = []

        async def handler(payload: dict[str, Any]) -> None:
            handled.append(payload["message_id"])

        # Run two concurrent receives; at least one should succeed.
        results = await asyncio.gather(
            consumer.receive(message_id, handler),
            consumer.receive(message_id, handler),
            return_exceptions=True,
        )

        success_count = sum(1 for r in results if r is True)
        assert success_count >= 1
        assert len(handled) == 1
