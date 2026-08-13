import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from autonoesis_adapters import InMemoryPlatformStore
from autonoesis_api.main import build_app
from autonoesis_domain import ApprovalRequest
from autonoesis_runtime import KillSwitchQuery
from fastapi.testclient import TestClient


def headers(tenant_id: UUID, actor_id: UUID, key: str | None = None) -> dict[str, str]:
    result = {
        "X-Tenant-ID": str(tenant_id),
        "X-Actor-ID": str(actor_id),
        "X-Roles": (
            "tenant_admin,operator,approver,developer,candidate_generator,grader,release_executor"
        ),
    }
    if key:
        result["Idempotency-Key"] = key
    return result


def manifest() -> dict[str, object]:
    return {
        "api_version": "autonoesis/v1alpha1",
        "pack_id": "generic-delivery",
        "version": "1.0.0",
        "python_entry_point": "generic_delivery.plugin:create",
        "goal_types": [
            {
                "goal_type": "generic-delivery.complete",
                "input_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["request"],
                    "properties": {"request": {"type": "string"}},
                },
                "agent": "delivery-agent",
                "evaluation_suite": "delivery-suite",
                "default_policy": "delivery-policy",
                "default_budget": 500,
            }
        ],
        "skills": ["delivery-skill"],
        "tools": ["delivery-tool"],
        "policies": ["delivery-policy"],
        "evaluation_suites": ["delivery-suite"],
    }


def test_generic_goal_run_and_evolution_api() -> None:
    tenant_id, actor_id = uuid4(), uuid4()
    client = TestClient(build_app(InMemoryPlatformStore()))
    identity = headers(tenant_id, actor_id)

    pack = client.post(
        "/v1/capability-packs",
        json={"manifest": manifest()},
        headers={**identity, "Idempotency-Key": "pack-1"},
    )
    assert pack.status_code == 201
    agent = client.post(
        "/v1/agents",
        json={
            "name": "delivery-agent",
            "description": "Delivers verified outcomes",
            "instruction": "Use evidence and remain inside authority.",
            "model_route": "balanced",
        },
        headers={**identity, "Idempotency-Key": "agent-1"},
    )
    assert agent.status_code == 201
    goal_payload = {
        "goal_type": "generic-delivery.complete",
        "statement": "Deliver the requested result",
        "desired_outcome": "External authoritative state is verified",
        "subject_refs": [{"system": "crm", "subject_type": "account", "subject_id": "A-1"}],
        "success_criteria": [
            {
                "criterion_id": "verified",
                "description": "State is verified",
                "evidence_type": "authoritative-read",
            }
        ],
        "owner_id": str(actor_id),
        "deadline": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "input_payload": {"request": "deliver"},
    }
    created = client.post(
        "/v1/goals",
        json=goal_payload,
        headers={**identity, "Idempotency-Key": "goal-1"},
    )
    assert created.status_code == 201
    duplicate = client.post(
        "/v1/goals",
        json=goal_payload,
        headers={**identity, "Idempotency-Key": "goal-1"},
    )
    assert duplicate.json()["goal_id"] == created.json()["goal_id"]
    conflicting = client.post(
        "/v1/goals",
        json={**goal_payload, "statement": "different request"},
        headers={**identity, "Idempotency-Key": "goal-1"},
    )
    assert conflicting.status_code == 409
    assert conflicting.json()["error"]["code"] == "concurrency_conflict"
    assert created.json()["status"] == "draft"
    activated = client.post(
        f"/v1/goals/{created.json()['goal_id']}/activation",
        headers={**identity, "Idempotency-Key": "activate-goal-1"},
    )
    assert activated.json()["status"] == "active"
    run = client.post(
        f"/v1/goals/{created.json()['goal_id']}/runs",
        # Idempotency keys are scoped by operation, so clients may reuse a key safely.
        headers={**identity, "Idempotency-Key": "goal-1"},
    )
    assert run.status_code == 202
    assert run.json()["status"] == "pending"

    proposal = client.post(
        "/v1/improvement-proposals",
        json={
            "target": "agent_instruction",
            "target_version_id": agent.json()["agent_version_id"],
            "evidence_refs": ["evidence://run/1"],
            "diagnosis": "Instruction misses a recovery condition",
            "proposed_change": "Add recovery condition",
            "validation_suite_id": "delivery-suite",
            "rollback_plan": "Restore previous stable version",
        },
        headers={**identity, "Idempotency-Key": "proposal-1"},
    )
    candidate = client.post(
        "/v1/candidates",
        json={
            "proposal_id": proposal.json()["proposal_id"],
            "baseline_version_id": agent.json()["agent_version_id"],
            "artifact_ref": "artifact://agent/v2",
        },
        headers={**headers(tenant_id, uuid4()), "Idempotency-Key": "candidate-1"},
    )
    evaluated = client.post(
        f"/v1/candidates/{candidate.json()['candidate_id']}/evaluate",
        json={
            "passed": True,
            "score": 0.92,
            "threshold": 0.8,
        },
        headers={**headers(tenant_id, uuid4()), "Idempotency-Key": "evaluation-1"},
    )
    assert evaluated.json()["status"] == "awaiting_approval"
    approved = client.post(
        f"/v1/candidates/{candidate.json()['candidate_id']}/decision",
        json={"approved": True},
        headers={**headers(tenant_id, uuid4()), "Idempotency-Key": "approval-1"},
    )
    assert approved.json()["status"] == "approved"
    shadow = client.post(
        f"/v1/candidates/{candidate.json()['candidate_id']}/promote",
        headers={**headers(tenant_id, uuid4()), "Idempotency-Key": "promotion-1"},
    )
    assert shadow.json()["status"] == "shadow"
    canary = client.post(
        f"/v1/deployments/{shadow.json()['deployment_id']}/canary",
        headers={**identity, "Idempotency-Key": "canary-1"},
    )
    assert canary.json()["status"] == "canary"
    release = client.post(
        f"/v1/deployments/{shadow.json()['deployment_id']}/stable",
        json={"stable_version_id": str(uuid4())},
        headers={**identity, "Idempotency-Key": "stable-1"},
    )
    assert release.status_code == 200
    rolled_back = client.post(
        f"/v1/releases/{release.json()['release_id']}/rollback",
        headers={**identity, "Idempotency-Key": "rollback-1"},
    )
    assert rolled_back.status_code == 200


def test_cross_tenant_goal_is_hidden() -> None:
    tenant_id, actor_id = uuid4(), uuid4()
    store = InMemoryPlatformStore()
    client = TestClient(build_app(store))
    # Unknown identifiers and cross-tenant identifiers have the same public response.
    response = client.get(f"/v1/goals/{uuid4()}", headers=headers(tenant_id, actor_id))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "record_not_found"
    assert store.audits[-1].event_type == "security.tenant_scope_lookup_denied"
    assert store.audits[-1].tenant_id == tenant_id
    assert str(response.request.url.path) not in store.audits[-1].object_id


def test_tenant_admin_cannot_target_another_tenants_kill_switch() -> None:
    tenant_id, other_tenant, actor_id = uuid4(), uuid4(), uuid4()
    store = InMemoryPlatformStore()
    client = TestClient(build_app(store))
    response = client.post(
        "/v1/kill-switches",
        json={"dimension": "tenant", "target": str(other_tenant), "reason": "hostile"},
        headers=headers(tenant_id, actor_id, "cross-tenant-kill-switch"),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "record_not_found"
    assert store.audits[-1].event_type == "security.tenant_scope_lookup_denied"


def test_platform_kill_switch_requires_separate_audited_break_glass_path() -> None:
    tenant_id, actor_id = uuid4(), uuid4()
    store = InMemoryPlatformStore()
    app = build_app(store)
    client = TestClient(app)
    identity = headers(tenant_id, actor_id)

    ordinary = client.post(
        "/v1/kill-switches",
        json={"dimension": "platform", "target": "platform", "reason": "ordinary path"},
        headers={**identity, "Idempotency-Key": "ordinary-platform-switch"},
    )
    assert ordinary.status_code == 403

    security_admin = uuid4()
    issued = client.post(
        "/v1/platform/break-glass/authorizations",
        json={
            "principal_id": str(actor_id),
            "reason": "temporary incident response authorization",
            "ttl_minutes": 15,
        },
        headers={
            **headers(tenant_id, security_admin, "issue-break-glass"),
            "X-Roles": "security_admin",
        },
    )
    assert issued.status_code == 201
    authorization_id = issued.json()["authorization_id"]

    break_glass = client.post(
        "/v1/platform/break-glass/kill-switch",
        json={"reason": "verified platform-wide incident response"},
        headers={
            **identity,
            "X-Roles": "break_glass",
            "Idempotency-Key": "break-glass-platform-switch",
            "X-Break-Glass-Ticket": "SEC-12345",
            "X-Break-Glass-Authorization": authorization_id,
        },
    )
    assert break_glass.status_code == 201
    assert break_glass.json()["dimension"] == "platform"
    assert store.audits[-2].event_type == "platform.kill_switch.activated"
    assert store.audits[-1].event_type == "security.alert.breakglass_activated"
    assert store.audits[-1].details["review_required"] is True

    reviewer = uuid4()
    reviewed = client.post(
        f"/v1/platform/break-glass/authorizations/{authorization_id}/review",
        headers={
            **headers(tenant_id, reviewer, "review-break-glass"),
            "X-Roles": "security_auditor",
        },
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["reviewed_by"] == str(reviewer)
    assert asyncio.run(app.state.kill_switch.is_blocked(KillSwitchQuery(tenant_id=str(tenant_id))))


def test_authentication_errors_use_the_common_envelope() -> None:
    client = TestClient(build_app(InMemoryPlatformStore()))
    response = client.get("/v1/goals")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "http_error"
    assert response.json()["error"]["retryable"] is False
    assert response.json()["error"]["correlation_id"]
    assert response.json()["error"]["audit_ref"] is None


def test_approval_decision_is_tenant_scoped_and_digest_bound() -> None:
    tenant_id, actor_id, approval_id = uuid4(), uuid4(), uuid4()
    store = InMemoryPlatformStore()
    digest = "a" * 64
    store.approvals[approval_id] = ApprovalRequest(
        tenant_id=tenant_id,
        run_id=uuid4(),
        action_id=uuid4(),
        action_digest=digest,
        tool_version="tool@1",
        operation="read",
        resource_scope="records/1",
        argument_digest=digest,
        policy_version="policy@1",
        impact_summary="read record",
        required_role="approver",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        approval_id=approval_id,
    )
    client = TestClient(build_app(store))
    response = client.post(
        f"/v1/approvals/{approval_id}/decision",
        json={"approved": True, "reason": "impact verified", "action_digest": digest},
        headers=headers(tenant_id, actor_id, "approval-1"),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    mismatch = client.post(
        f"/v1/approvals/{approval_id}/decision",
        json={"approved": True, "reason": "changed", "action_digest": "b" * 64},
        headers=headers(tenant_id, actor_id, "approval-2"),
    )
    assert mismatch.status_code == 403
