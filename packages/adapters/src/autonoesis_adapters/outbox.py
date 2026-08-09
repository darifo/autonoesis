"""Transactional outbox publisher and inbox consumer for at-least-once event delivery."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from autonoesis_contracts import MessageEnvelope
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from autonoesis_adapters.persistence import inbox, outbox


class OutboxWriter:
    """Writes events to the outbox table.

    The caller must commit the transaction that the *session* belongs to
    so that the outbox row is atomically persisted with the business data.
    """

    @staticmethod
    async def publish(session: AsyncSession, envelope: MessageEnvelope) -> None:
        """Insert an event into the outbox. Call inside an active transaction."""
        await session.execute(
            outbox.insert().values(
                id=str(uuid4()),
                tenant_id=str(envelope.tenant_id),
                schema=envelope.schema,
                payload=_envelope_to_payload(envelope),
                optimistic_version=1,
                created_at=datetime.now(UTC),
            )
        )


class OutboxRelay:
    """Polls the outbox for unpublished events and relays them through a callback.

    The callback receives a ``MessageEnvelope`` and should publish it to a
    message channel (NATS, Kafka, etc.).  On success the relay marks the row
    as published.
    """

    def __init__(
        self,
        engine: AsyncEngine,
        publisher: Callable[[MessageEnvelope], Awaitable[None]],
        *,
        batch_size: int = 100,
    ) -> None:
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)
        self._publisher = publisher
        self._batch_size = batch_size

    async def poll_and_publish(self) -> int:
        """Fetch unpublished events, relay them, and mark as published.

        Returns the number of events successfully published.
        """
        published = 0
        async with self._sessions.begin() as session:
            rows = (
                (
                    await session.execute(
                        select(outbox)
                        .where(outbox.c.published_at.is_(None))
                        .order_by(outbox.c.created_at.asc())
                        .limit(self._batch_size)
                    )
                )
                .mappings()
                .all()
            )

            for row in rows:
                envelope = _payload_to_envelope(dict(row))
                try:
                    await self._publisher(envelope)
                except Exception:
                    # Leave unpublished so the relay retries on the next poll.
                    continue

                await session.execute(
                    update(outbox)
                    .where(outbox.c.id == row["id"])
                    .values(published_at=datetime.now(UTC))
                )
                published += 1

        return published


class InboxConsumer:
    """Deduplicates incoming events using the inbox table.

    Each event is identified by its unique ``message_id``.  Events that have
    already been processed are silently skipped.
    """

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def receive(
        self,
        message_id: str,
        handler: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> bool:
        """Process *message_id* if it has not been processed before.

        Returns ``True`` when the event was newly processed, ``False`` when it
        was already known (idempotent skip).
        """
        async with self._sessions.begin() as session:
            existing = (
                await session.execute(select(inbox.c.id).where(inbox.c.message_id == message_id))
            ).scalar()

            if existing is not None:
                return False  # already processed

            # Reserve the slot *before* handling so that concurrent consumers
            # do not race on the same message.
            row_id = str(uuid4())
            now = datetime.now(UTC)
            try:
                await session.execute(
                    inbox.insert().values(
                        id=row_id,
                        tenant_id="00000000-0000-0000-0000-000000000000",
                        message_id=message_id,
                        processed_at=now,
                        optimistic_version=1,
                        created_at=now,
                    )
                )
            except IntegrityError:
                # Another consumer claimed this message first.
                return False

            # The handler runs *inside* the transaction so that if it fails
            # the inbox slot is rolled back and the message can be retried.
            await handler({"message_id": message_id})

        return True


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _envelope_to_payload(envelope: MessageEnvelope) -> dict[str, Any]:
    return {
        "schema": envelope.schema,
        "schema_version": envelope.schema_version,
        "tenant_id": str(envelope.tenant_id),
        "actor_id": str(envelope.actor_id),
        "payload": envelope.payload,
        "message_id": str(envelope.message_id),
        "correlation_id": str(envelope.correlation_id),
        "causation_id": str(envelope.causation_id) if envelope.causation_id else None,
        "traceparent": envelope.traceparent,
        "classification": envelope.classification.value,
        "created_at": envelope.created_at.isoformat(),
    }


def _payload_to_envelope(row: dict[str, Any]) -> MessageEnvelope:
    payload = row["payload"]
    return MessageEnvelope(
        schema=payload["schema"],
        schema_version=payload["schema_version"],
        tenant_id=UUID(payload["tenant_id"]),
        actor_id=UUID(payload["actor_id"]),
        payload=payload["payload"],
        message_id=UUID(payload["message_id"]),
        correlation_id=UUID(payload["correlation_id"]),
        causation_id=UUID(payload["causation_id"]) if payload.get("causation_id") else None,
        traceparent=payload.get("traceparent"),
        classification=payload.get("classification", "internal"),
        created_at=datetime.fromisoformat(payload["created_at"]),
    )
