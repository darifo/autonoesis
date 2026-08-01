from datetime import datetime
from uuid import uuid4

import pytest
from autonoesis_contracts import MessageEnvelope


def test_message_envelope_requires_timezone_aware_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        MessageEnvelope(
            schema="run.started",
            schema_version=1,
            tenant_id=uuid4(),
            actor_id=uuid4(),
            payload={},
            created_at=datetime(2026, 8, 1),
        )


def test_message_envelope_requires_positive_schema_version() -> None:
    with pytest.raises(ValueError, match="positive"):
        MessageEnvelope(
            schema="run.started",
            schema_version=0,
            tenant_id=uuid4(),
            actor_id=uuid4(),
            payload={},
        )
