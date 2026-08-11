"""Contract tests for configured HTTP authoritative readback."""

from uuid import uuid4

import httpx
import pytest
from autonoesis_adapters import HttpAuthoritativeReadback, ReadbackEndpoint
from autonoesis_domain import SubjectRef, SuccessCriterion


@pytest.mark.asyncio
async def test_readback_uses_registered_authority_and_canonical_state() -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://records.example.test/v1/readback"
        return httpx.Response(
            200,
            json={
                "reference": "records://42?v=7",
                "state": {"version": 7, "status": "delivered"},
                "criterion_met": True,
                "valid_for_seconds": 60,
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    adapter = HttpAuthoritativeReadback(
        {
            "records": ReadbackEndpoint(
                "https://records.example.test",
                "records-authority@1",
            )
        },
        client,
    )
    observation = await adapter.observe(
        "records",
        uuid4(),
        (SubjectRef("records", "record", "42"),),
        SuccessCriterion("delivered", "record delivered", "authoritative-readback"),
    )
    assert observation.source_identity == "records-authority@1"
    assert observation.reference == "records://42?v=7"
    assert observation.content == b'{"status":"delivered","version":7}'
    assert observation.criterion_met is True
    await client.aclose()


@pytest.mark.asyncio
async def test_unavailable_or_unregistered_readback_is_not_authority() -> None:
    async def unavailable(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client = httpx.AsyncClient(transport=httpx.MockTransport(unavailable))
    adapter = HttpAuthoritativeReadback(
        {"records": ReadbackEndpoint("https://records.example.test", "records-authority@1")},
        client,
    )
    args = (
        uuid4(),
        (SubjectRef("records", "record", "42"),),
        SuccessCriterion("delivered", "record delivered", "authoritative-readback"),
    )
    with pytest.raises(LookupError, match="unavailable"):
        await adapter.observe("records", *args)
    with pytest.raises(LookupError, match="not registered"):
        await adapter.observe("caller-url", *args)
    await client.aclose()


def test_non_loopback_plaintext_authority_is_rejected() -> None:
    with pytest.raises(ValueError, match="must use TLS"):
        ReadbackEndpoint("http://records.example.test", "records-authority@1")
