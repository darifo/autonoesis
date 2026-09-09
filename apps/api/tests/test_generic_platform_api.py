import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from autonoesis_adapters import InMemoryPlatformStore
from autonoesis_api.main import build_app
from autonoesis_domain import ApprovalRequest, Trial, TrialCaseResult, TrialStatus
from autonoesis_runtime import KillSwitchQuery
from fastapi.testclient import TestClient


class RecordingShadowDispatcher:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def dispatch(self, **command: object) -> str:
        self.calls.append(command)
        return f"shadow-workflow-{command['request_id']}"


class RecordingReleaseDispatcher:
    """Test double mirroring the real executor: records and applies transitions."""

    def __init__(self, store: InMemoryPlatformStore) -> None:
        from autonoesis_application import (
            CandidateLifecycleService,
            IdentityContext,
            PromotionPolicy,
        )
        from autonoesis_domain import TrafficAllocation

        self.calls: list[dict[str, object]] = []
        self._TrafficAllocation = TrafficAllocation
        self._PromotionPolicy = PromotionPolicy
        self._IdentityContext = IdentityContext
        self._evolution = CandidateLifecycleService(store)

    async def dispatch(self, **command: object) -> str:
        from typing import cast

        self.calls.append(command)
        action = str(command["action"])
        identity = self._IdentityContext(
            UUID(str(command["tenant_id"])), uuid4(), uuid4(), frozenset({"release_executor"})
        )
        payload = cast(dict[str, object], command["command"])
        if action == "enter_canary":
            deployment = await self._evolution.promote_to_canary(
                identity,
                UUID(str(payload["deployment_id"])),
                self._TrafficAllocation(
                    str(payload["salt"]), int(str(payload["candidate_percent"]))
                ),
            )
            return f"release-workflow-canary-{deployment.deployment_id}"
        if action == "release_stable":
            release = await self._evolution.release_stable(
                identity,
                UUID(str(payload["deployment_id"])),
                UUID(str(payload["stable_version_id"])),
                self._PromotionPolicy(
                    int(str(payload["min_samples"])),
                    int(str(payload["observation_seconds"])),
                    tuple(
                        str(metric) for metric in cast(list[object], payload["required_metrics"])
                    ),
                ),
            )
            return f"release-workflow-stable-{release.release_id}"
        release = await self._evolution.rollback(identity, UUID(str(payload["release_id"])))
        return f"release-workflow-rollback-{release.release_id}"


class DevPackVerifier:
    """Test double mirroring StrictSupplyChainVerifier with an ephemeral key."""

    def __init__(self) -> None:
        from autonoesis_capability.signing import generate_signing_key, public_key_hex

        self.private_key = generate_signing_key()
        self.public_key = public_key_hex(self.private_key)

    async def verify_install(self, manifest: Any) -> None:
        from autonoesis_adapters import StrictSupplyChainVerifier
        from autonoesis_capability import CapabilityPackManifest

        assert isinstance(manifest, CapabilityPackManifest)
        verifier = StrictSupplyChainVerifier(
            allowed_sources=("artifact://packs/",),
            public_keys_hex=(self.public_key,),
        )
        await verifier.verify_install(manifest)

    def signed(self, raw_manifest: dict[str, object]) -> dict[str, object]:
        from autonoesis_capability import manifest_payload, parse_manifest
        from autonoesis_capability.signing import supply_chain_fields

        manifest = parse_manifest(dict(raw_manifest))
        signed = supply_chain_fields(
            manifest,
            private_key_hex=self.private_key,
            sbom_ref="sbom://packs/test/cyclonedx",
            sbom_digest="e" * 64,
        )
        return manifest_payload(signed)


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
    store = InMemoryPlatformStore()
    shadow_dispatcher = RecordingShadowDispatcher()
    release_dispatcher = RecordingReleaseDispatcher(store)
    pack_verifier = DevPackVerifier()
    client = TestClient(
        build_app(
            store,
            shadow_dispatcher=shadow_dispatcher,
            release_dispatcher=release_dispatcher,
            pack_verifier=pack_verifier,
        )
    )
    identity = headers(tenant_id, actor_id)

    unsigned = TestClient(build_app(store))
    refused = unsigned.post(
        "/v1/capability-packs",
        json={"manifest": manifest()},
        headers={**identity, "Idempotency-Key": "pack-unconfigured"},
    )
    assert refused.status_code == 503
    pack = client.post(
        "/v1/capability-packs",
        json={"manifest": pack_verifier.signed(manifest())},
        headers={**identity, "Idempotency-Key": "pack-1"},
    )
    assert pack.status_code == 201
    assert pack.json()["artifact_digest"]
    tampered = manifest()
    tampered["skills"] = ["extra-skill"]
    conflict = client.post(
        "/v1/capability-packs",
        json={"manifest": tampered},
        headers={**identity, "Idempotency-Key": "pack-tampered"},
    )
    assert conflict.status_code == 400
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
            "artifact_digest": "d" * 64,
            "suite_id": "delivery-suite",
            "suite_version": "1",
        },
        headers={**headers(tenant_id, uuid4()), "Idempotency-Key": "candidate-1"},
    )
    candidate_id = UUID(candidate.json()["candidate_id"])
    executed_case = TrialCaseResult(
        case_id="c1",
        input_payload={},
        output_payload={"answer": 42},
        subject_executed=True,
        executor_id="subject-runtime",
        evidence_refs=("evidence://execution/1",),
        environment_ref="environment://fixture/1",
    )
    for _ in range(16):
        asyncio.run(
            store.add_trial(
                Trial(
                    tenant_id=tenant_id,
                    suite_id="delivery-suite",
                    suite_version="1",
                    subject_version_id=candidate_id,
                    harness_version="2",
                    status=TrialStatus.PASSED,
                    case_results=(executed_case,),
                    candidate_id=candidate_id,
                )
            )
        )
    evaluated = client.post(
        f"/v1/candidates/{candidate_id}/evaluate",
        headers={**headers(tenant_id, uuid4()), "Idempotency-Key": "evaluation-1"},
    )
    assert evaluated.json()["status"] == "awaiting_approval"
    assert evaluated.json()["evaluation"]["decision"] == "met"
    assert len(evaluated.json()["evaluation"]["trial_ids"]) == 16
    approved = client.post(
        f"/v1/candidates/{candidate_id}/decision",
        json={"approved": True, "reason": "independent review passed"},
        headers={**headers(tenant_id, uuid4()), "Idempotency-Key": "approval-1"},
    )
    assert approved.json()["status"] == "approved"
    shadow = client.post(
        f"/v1/candidates/{candidate.json()['candidate_id']}/promote",
        headers={**headers(tenant_id, uuid4()), "Idempotency-Key": "promotion-1"},
    )
    assert shadow.json()["status"] == "shadow"
    shadow_request_id = uuid4()
    dispatched = client.post(
        f"/v1/deployments/{shadow.json()['deployment_id']}/shadow-requests",
        json={"request_id": str(shadow_request_id), "input_payload": {"request": "mirror"}},
        headers={**identity, "Idempotency-Key": "shadow-request-1"},
    )
    assert dispatched.status_code == 202
    assert dispatched.json()["status"] == "dispatched"
    assert shadow_dispatcher.calls == [
        {
            "tenant_id": tenant_id,
            "deployment_id": UUID(shadow.json()["deployment_id"]),
            "request_id": shadow_request_id,
            "input_payload": {"request": "mirror"},
        }
    ]
    unavailable = TestClient(build_app(store)).post(
        f"/v1/deployments/{shadow.json()['deployment_id']}/shadow-requests",
        json={"request_id": str(uuid4()), "input_payload": {"request": "mirror"}},
        headers={**identity, "Idempotency-Key": "shadow-request-unconfigured"},
    )
    assert unavailable.status_code == 503
    unconfigured_release = TestClient(build_app(store)).post(
        f"/v1/deployments/{shadow.json()['deployment_id']}/canary",
        json={"candidate_percent": 10, "salt": "audit-salt"},
        headers={**identity, "Idempotency-Key": "canary-unconfigured"},
    )
    assert unconfigured_release.status_code == 503
    canary = client.post(
        f"/v1/deployments/{shadow.json()['deployment_id']}/canary",
        json={"candidate_percent": 10, "salt": "audit-salt"},
        headers={**identity, "Idempotency-Key": "canary-1"},
    )
    assert canary.status_code == 202
    assert canary.json()["status"] == "dispatched"
    stable_version_id = uuid4()
    release_command = client.post(
        f"/v1/deployments/{shadow.json()['deployment_id']}/stable",
        json={"stable_version_id": str(stable_version_id)},
        headers={**identity, "Idempotency-Key": "stable-1"},
    )
    assert release_command.status_code == 202
    assert release_command.json()["status"] == "dispatched"
    assert release_dispatcher.calls == [
        {
            "tenant_id": tenant_id,
            "action": "enter_canary",
            "command": {
                "deployment_id": shadow.json()["deployment_id"],
                "candidate_percent": 10,
                "salt": "audit-salt",
            },
            "target_id": UUID(shadow.json()["deployment_id"]),
        },
        {
            "tenant_id": tenant_id,
            "action": "release_stable",
            "command": {
                "deployment_id": shadow.json()["deployment_id"],
                "stable_version_id": str(stable_version_id),
                "min_samples": 1,
                "observation_seconds": 0,
                "required_metrics": [],
            },
            "target_id": UUID(shadow.json()["deployment_id"]),
        },
    ]
    # Only the dispatched executor transitions moved release state.
    assert store.deployments[UUID(shadow.json()["deployment_id"])].status.value == "stable"
    stable_release_id = release_command.json()["workflow_id"].removeprefix(
        "release-workflow-stable-"
    )
    rolled_back = client.post(
        f"/v1/releases/{stable_release_id}/rollback",
        headers={**identity, "Idempotency-Key": "rollback-1"},
    )
    assert rolled_back.status_code == 202
    assert rolled_back.json()["status"] == "dispatched"
    assert store.deployments[UUID(shadow.json()["deployment_id"])].status.value == "rolled_back"


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


async def _stable_release_in_store() -> tuple[InMemoryPlatformStore, UUID, UUID, UUID]:
    """Leave one deployment in Canary and release a second one to Stable."""
    from autonoesis_application import (
        CandidateLifecycleService,
        IdentityContext,
        PromotionPolicy,
        ProposeImprovement,
        RecordObservation,
        RegisterCandidate,
    )
    from autonoesis_domain import DeploymentStatus, TrafficAllocation

    store = InMemoryPlatformStore()
    evolution = CandidateLifecycleService(store)
    tenant_id = uuid4()

    async def _canary_deployment() -> Any:
        generator = IdentityContext(tenant_id, uuid4(), uuid4(), frozenset({"candidate_generator"}))
        proposal = await evolution.propose_improvement(
            generator,
            ProposeImprovement(
                target="agent_instruction",
                target_version_id=uuid4(),
                evidence_refs=("evidence://run/1",),
                diagnosis="Instruction misses a recovery condition",
                proposed_change="Add recovery condition",
                validation_suite_id="delivery-suite",
                rollback_plan="Restore previous stable version",
            ),
        )
        candidate = await evolution.register_candidate(
            generator,
            RegisterCandidate(
                proposal_id=proposal.proposal_id,
                baseline_version_id=uuid4(),
                artifact_ref="artifact://agent/v2",
                artifact_digest="d" * 64,
                suite_id="delivery-suite",
                suite_version="1",
            ),
        )
        await evolution.submit_for_evaluation(tenant_id, candidate.candidate_id)
        executed = TrialCaseResult(
            case_id="c1",
            input_payload={},
            output_payload={"answer": 42},
            subject_executed=True,
            executor_id="subject-runtime",
            evidence_refs=("evidence://execution/1",),
            environment_ref="environment://fixture/1",
        )
        for _ in range(16):
            await store.add_trial(
                Trial(
                    tenant_id=tenant_id,
                    suite_id="delivery-suite",
                    suite_version="1",
                    subject_version_id=candidate.candidate_id,
                    harness_version="2",
                    status=TrialStatus.PASSED,
                    case_results=(executed,),
                    candidate_id=candidate.candidate_id,
                )
            )
        from autonoesis_evaluation import RepeatedTrialPolicy

        grader = IdentityContext(tenant_id, uuid4(), uuid4(), frozenset({"grader"}))
        await evolution.complete_evaluation(
            grader, candidate.candidate_id, RepeatedTrialPolicy(pass_threshold=0.8)
        )
        await evolution.decide(
            IdentityContext(tenant_id, uuid4(), uuid4(), frozenset({"approver"})),
            candidate.candidate_id,
            True,
            "independent review passed",
        )
        executor = IdentityContext(tenant_id, uuid4(), uuid4(), frozenset({"release_executor"}))
        deployment = await evolution.begin_shadow(executor, candidate.candidate_id)
        return await evolution.promote_to_canary(
            executor, deployment.deployment_id, TrafficAllocation("audit-salt", 25)
        )

    remaining_canary = await _canary_deployment()
    released = await _canary_deployment()
    executor = IdentityContext(tenant_id, uuid4(), uuid4(), frozenset({"release_executor"}))
    for _ in range(2):
        await evolution.record_observation(
            executor,
            RecordObservation(
                released.deployment_id, DeploymentStatus.CANARY, "outcome_rate", 0.99
            ),
        )
    release = await evolution.release_stable(
        executor,
        released.deployment_id,
        uuid4(),
        PromotionPolicy(min_samples=2, required_metrics=("outcome_rate",)),
    )
    return store, tenant_id, remaining_canary.deployment_id, release.release_id


def test_release_route_and_rollback_dispatch() -> None:
    from autonoesis_domain import TrafficAllocation

    store, tenant_id, deployment_id, release_id = asyncio.run(_stable_release_in_store())
    release_dispatcher = RecordingReleaseDispatcher(store)
    client = TestClient(build_app(store, release_dispatcher=release_dispatcher))
    identity = headers(tenant_id, uuid4())

    request_id = uuid4()
    route = client.get(
        f"/v1/deployments/{deployment_id}/route",
        params={"request_id": str(request_id)},
        headers=identity,
    )
    assert route.status_code == 200
    resolved = route.json()
    expected_route = TrafficAllocation("audit-salt", 25).assign(request_id).value
    assert resolved["route"] == expected_route
    assert resolved["candidate_percent"] == 25
    assert resolved["salt"] == "audit-salt"

    rolled_back = client.post(
        f"/v1/releases/{release_id}/rollback",
        headers={**identity, "Idempotency-Key": "rollback-1"},
    )
    assert rolled_back.status_code == 202
    assert rolled_back.json()["status"] == "dispatched"
    assert release_dispatcher.calls == [
        {
            "tenant_id": tenant_id,
            "action": "rollback_release",
            "command": {"release_id": str(release_id)},
            "target_id": release_id,
        }
    ]

    missing = client.post(
        f"/v1/releases/{uuid4()}/rollback",
        headers={**identity, "Idempotency-Key": "rollback-unknown"},
    )
    assert missing.status_code == 404
    unconfigured = TestClient(build_app(store)).post(
        f"/v1/releases/{release_id}/rollback",
        headers={**identity, "Idempotency-Key": "rollback-unconfigured"},
    )
    assert unconfigured.status_code == 503


def test_route_resolution_requires_allocatable_canary() -> None:
    store, tenant_id, canary_id, _ = asyncio.run(_stable_release_in_store())
    client = TestClient(build_app(store))
    identity = headers(tenant_id, uuid4())
    stable_id = next(
        item.deployment_id for item in store.deployments.values() if item.status.value == "stable"
    )
    # A stable deployment no longer routes live traffic through a rule.
    refused = client.get(
        f"/v1/deployments/{stable_id}/route",
        params={"request_id": str(uuid4())},
        headers=identity,
    )
    assert refused.status_code == 409
    # The canary deployment keeps replaying its persisted rule.
    allowed = client.get(
        f"/v1/deployments/{canary_id}/route",
        params={"request_id": str(uuid4())},
        headers=identity,
    )
    assert allowed.status_code == 200


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
