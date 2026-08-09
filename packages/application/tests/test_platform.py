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
            "medium",
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
