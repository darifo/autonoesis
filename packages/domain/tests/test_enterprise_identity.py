from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from autonoesis_domain import (
    ApprovalRequest,
    ApprovalStatus,
    DelegationGrant,
    EnterpriseIdentity,
    IdentityKind,
    TemporaryAuthorization,
)


def test_revoked_delegation_immediately_stops_authorizing() -> None:
    tenant, grantor, delegate = uuid4(), uuid4(), uuid4()
    grant = DelegationGrant(
        tenant,
        grantor,
        delegate,
        "crm.update",
        "customer/42/",
        "resolve-support-case",
        datetime.now(UTC) + timedelta(minutes=5),
    )
    assert grant.authorizes(
        tenant_id=tenant,
        principal_id=delegate,
        tool_name="crm.update",
        resource="customer/42/contact",
        purpose="resolve-support-case",
    )
    assert not grant.revoke().authorizes(
        tenant_id=tenant,
        principal_id=delegate,
        tool_name="crm.update",
        resource="customer/42/contact",
        purpose="resolve-support-case",
    )


def test_service_and_agent_identity_require_specific_identifier() -> None:
    with pytest.raises(ValueError, match="service_id"):
        EnterpriseIdentity(uuid4(), uuid4(), uuid4(), "worker", IdentityKind.SERVICE)


def test_breakglass_post_review_must_be_independent() -> None:
    principal = uuid4()
    authorization = TemporaryAuthorization(
        uuid4(),
        principal,
        "platform.kill_switch",
        "incident response",
        datetime.now(UTC) + timedelta(minutes=15),
    )
    with pytest.raises(ValueError, match="independent"):
        authorization.review(principal)
    assert authorization.review(uuid4()).reviewed_at is not None


def test_two_person_review_is_bound_to_distinct_principals() -> None:
    now = datetime.now(UTC)
    approval = ApprovalRequest(
        tenant_id=uuid4(),
        run_id=uuid4(),
        action_id=uuid4(),
        action_digest="a" * 64,
        tool_version="1",
        operation="delete",
        resource_scope="customer/42",
        argument_digest="b" * 64,
        policy_version="policy@1",
        impact_summary="high-impact deletion",
        required_role="approver",
        expires_at=now + timedelta(minutes=5),
        created_at=now,
        required_reviews=2,
    )
    principal = uuid4()
    first = approval.decide(uuid4(), True, "review one", principal_id=principal)
    assert first.status is ApprovalStatus.PENDING
    with pytest.raises(PermissionError, match="same principal"):
        first.decide(uuid4(), True, "other session", principal_id=principal)
    second = first.decide(uuid4(), True, "independent review", principal_id=uuid4())
    assert second.status is ApprovalStatus.APPROVED
