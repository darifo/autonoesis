from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from autonoesis_adapters import InMemoryPlatformStore
from autonoesis_application import (
    CreateGoal,
    CreateGoalHandler,
    IdentityContext,
    StartGoalRun,
    StartGoalRunHandler,
    TenantBoundaryViolation,
)
from autonoesis_capability import parse_manifest
from autonoesis_domain import (
    AgentVersion,
    AssetStage,
    GoalStatus,
    LoopPolicy,
    RiskTier,
    SubjectRef,
    SuccessCriterion,
)


def manifest() -> dict[str, object]:
    return {
        "api_version": "autonoesis/v1alpha1",
        "pack_id": "example-pack",
        "version": "1.0.0",
        "python_entry_point": "example_pack.plugin:create",
        "goal_types": [
            {
                "goal_type": "example.deliver",
                "input_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["request"],
                    "properties": {"request": {"type": "string"}},
                },
                "agent": "example-agent",
                "evaluation_suite": "example-suite",
                "default_policy": "example-policy",
                "default_budget": 100,
            }
        ],
        "skills": [],
        "tools": [],
        "policies": ["example-policy"],
        "evaluation_suites": ["example-suite"],
    }


@pytest.mark.asyncio
async def test_goal_and_run_use_capability_pack_without_industry_fields() -> None:
    store = InMemoryPlatformStore()
    tenant_id, actor_id = uuid4(), uuid4()
    store.register_pack(parse_manifest(manifest()))
    agent = AgentVersion(
        tenant_id,
        uuid4(),
        1,
        "Deliver verified outcomes",
        "balanced",
        (),
        (),
        LoopPolicy(5, 1000, 100, 60),
        AssetStage.STABLE,
    )
    store.register_agent("example-agent", agent)
    identity = IdentityContext(tenant_id, actor_id, actor_id, frozenset({"operator"}))
    goal = await CreateGoalHandler(store, store)(
        identity,
        CreateGoal(
            "example.deliver",
            "Deliver result",
            "Verified delivery",
            (SubjectRef("crm", "account", "A-1"),),
            (SuccessCriterion("verified", "result verified", "system-read"),),
            (),
            actor_id,
            RiskTier.MEDIUM,
            None,
            datetime.now(UTC) + timedelta(days=1),
            {"request": "deliver"},
            uuid4(),
        ),
    )
    run = await StartGoalRunHandler(store, store)(identity, StartGoalRun(goal.goal_id, uuid4()))
    assert goal.status is GoalStatus.ACTIVE
    assert run.agent_version_id == agent.agent_version_id
    with pytest.raises(TenantBoundaryViolation):
        await store.get_goal(uuid4(), goal.goal_id)


@pytest.mark.asyncio
async def test_runs_bind_to_canary_candidate_routes_only() -> None:
    """Runs replay the tenant's canary rule at creation (ADR-0033 live routing)."""
    from autonoesis_application.execution import (
        CommandContext,
        GoalExecutionApplication,
        RequestRun,
    )
    from autonoesis_domain import DeploymentStatus, TrafficAllocation

    store = InMemoryPlatformStore()
    tenant_id, actor_id = uuid4(), uuid4()
    store.register_pack(parse_manifest(manifest()))
    agent = AgentVersion(
        tenant_id,
        uuid4(),
        1,
        "Deliver verified outcomes",
        "balanced",
        (),
        (),
        LoopPolicy(5, 1000, 100, 60),
        AssetStage.STABLE,
    )
    store.register_agent("example-agent", agent)
    identity = IdentityContext(tenant_id, actor_id, actor_id, frozenset({"operator"}))

    goal = await CreateGoalHandler(store, store)(
        identity,
        CreateGoal(
            "example.deliver",
            "Deliver result",
            "Verified delivery",
            (SubjectRef("crm", "account", "A-1"),),
            (SuccessCriterion("verified", "result verified", "system-read"),),
            (),
            actor_id,
            RiskTier.MEDIUM,
            None,
            datetime.now(UTC) + timedelta(days=1),
            {"request": "deliver"},
            uuid4(),
        ),
    )

    from autonoesis_domain import Deployment

    shadow = Deployment(tenant_id, uuid4(), DeploymentStatus.SHADOW)
    canary = shadow.enter_canary(
        TrafficAllocation("router-salt", 50), actor_id=actor_id, reason="test canary"
    )
    store.deployments[canary.deployment_id] = canary

    from autonoesis_adapters import CanaryRunRouter

    application = GoalExecutionApplication(
        store.repository, store, run_deployment_router=CanaryRunRouter(store)
    )

    candidate_bound = 0
    stable_unbound = 0
    for index in range(30):
        # Each request needs a distinct idempotency key; goal allows one active
        # run, so complete-or-cancel is skipped by asserting binding only on
        # the first run per goal — instead create fresh goals per iteration.
        iteration_goal = await CreateGoalHandler(store, store)(
            identity,
            CreateGoal(
                "example.deliver",
                f"Deliver result {index}",
                "Verified delivery",
                (SubjectRef("crm", "account", "A-1"),),
                (SuccessCriterion("verified", "result verified", "system-read"),),
                (),
                actor_id,
                RiskTier.MEDIUM,
                None,
                datetime.now(UTC) + timedelta(days=1),
                {"request": "deliver"},
                uuid4(),
            ),
        )
        from hashlib import sha256

        context = CommandContext(
            identity,
            uuid4(),
            uuid4(),
            f"canary-route-{index}",
            sha256(f"canary-route-{index}".encode()).hexdigest(),
        )
        run = await application.request_run(context, RequestRun(goal_id=iteration_goal.goal_id))
        if run.deployment_id is not None:
            assert run.deployment_id == canary.deployment_id
            candidate_bound += 1
        else:
            stable_unbound += 1

    assert candidate_bound > 0, "canary rule never routed a candidate"
    assert stable_unbound > 0, "canary rule routed every run"
