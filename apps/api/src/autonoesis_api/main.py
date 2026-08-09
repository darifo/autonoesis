"""Industry-neutral Autonoesis control-plane API."""

import json
import os
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID, uuid4

from autonoesis_adapters import (
    InMemoryPlatformStore,
    OIDCSettings,
    OIDCValidator,
    PostgreSQLPlatformStore,
)
from autonoesis_application import (
    CandidateLifecycleService,
    CreateGoal,
    CreateGoalHandler,
    EvaluationDecision,
    IdentityContext,
    RecordNotFound,
    StartGoalRun,
    StartGoalRunHandler,
    TenantBoundaryViolation,
)
from autonoesis_capability import ManifestError, load_manifest, parse_manifest
from autonoesis_domain import (
    AgentDefinition,
    AgentVersion,
    AssetStage,
    CandidateVersion,
    GoalContract,
    ImprovementProposal,
    ImprovementTarget,
    LoopPolicy,
    SubjectRef,
    SuccessCriterion,
)
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from temporalio.client import Client


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentRequest(StrictRequest):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1000)
    instruction: str = Field(min_length=1, max_length=20_000)
    model_route: str = Field(min_length=1, max_length=200)
    skill_ids: tuple[str, ...] = ()
    tool_ids: tuple[str, ...] = ()
    max_rounds: int = Field(default=8, ge=1, le=100)
    max_tokens: int = Field(default=32_000, ge=1)
    max_cost_units: int = Field(default=1000, ge=1)
    timeout_seconds: int = Field(default=900, ge=1)


class CapabilityPackRequest(StrictRequest):
    manifest: dict[str, Any]


class ConfigAssetRequest(StrictRequest):
    asset_id: str = Field(min_length=1, max_length=200)
    definition: dict[str, Any]


class SubjectRequest(StrictRequest):
    system: str
    subject_type: str
    subject_id: str
    version: str | None = None


class CriterionRequest(StrictRequest):
    criterion_id: str
    description: str
    evidence_type: str


class GoalRequest(StrictRequest):
    goal_type: str
    statement: str
    desired_outcome: str
    subject_refs: tuple[SubjectRequest, ...] = Field(min_length=1)
    success_criteria: tuple[CriterionRequest, ...] = Field(min_length=1)
    constraints: tuple[str, ...] = ()
    owner_id: UUID
    risk_tier: str = "medium"
    budget_limit: int | None = Field(default=None, ge=1)
    deadline: datetime
    input_payload: dict[str, Any]


class ImprovementProposalRequest(StrictRequest):
    target: ImprovementTarget
    target_version_id: UUID
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    diagnosis: str
    proposed_change: str
    validation_suite_id: str
    rollback_plan: str
    proposer_id: str


class CandidateRequest(StrictRequest):
    proposal_id: UUID
    baseline_version_id: UUID
    artifact_ref: str
    generator_id: str


class EvaluationRequest(StrictRequest):
    passed: bool
    score: float = Field(ge=0, le=1)
    grader_id: str
    threshold: float = Field(ge=0, le=1)


class CandidateDecisionRequest(StrictRequest):
    approved: bool


class ApprovalDecisionRequest(StrictRequest):
    approved: bool
    reason: str = Field(min_length=1, max_length=2000)
    action_digest: str = Field(min_length=64, max_length=64)


class PromotionRequest(StrictRequest):
    stable_version_id: UUID


def error_response(
    status_code: int, code: str, message: str, retryable: bool, next_action: str
) -> JSONResponse:
    correlation_id = str(uuid4())
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "retryable": retryable,
                "next_action": next_action,
                "correlation_id": correlation_id,
                "audit_ref": f"audit://errors/{correlation_id}",
            }
        },
    )


def build_app(store: InMemoryPlatformStore | None = None) -> FastAPI:
    platform_store = store or InMemoryPlatformStore()
    app = FastAPI(
        title="Autonoesis API",
        description="Goal-driven governed and evolving AI agent platform",
        version="0.3.0",
    )
    app.state.store = platform_store
    app.state.idempotency = {}
    goal_handler = CreateGoalHandler(platform_store, platform_store)
    run_handler = StartGoalRunHandler(platform_store, platform_store)
    evolution = CandidateLifecycleService(platform_store)

    @app.exception_handler(RecordNotFound)
    @app.exception_handler(TenantBoundaryViolation)
    async def hidden_record(_: Request, __: Exception) -> JSONResponse:
        return error_response(
            404,
            "record_not_found",
            "The requested resource was not found.",
            False,
            "verify the identifier and tenant scope",
        )

    @app.exception_handler(ManifestError)
    @app.exception_handler(ValueError)
    async def invalid_request(_: Request, exc: Exception) -> JSONResponse:
        return error_response(422, "invalid_request", str(exc), False, "correct the request")

    @app.exception_handler(PermissionError)
    async def forbidden(_: Request, exc: PermissionError) -> JSONResponse:
        return error_response(403, "permission_denied", str(exc), False, "request authorization")

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        return error_response(
            exc.status_code,
            "http_error",
            str(exc.detail),
            exc.status_code >= 500,
            "correct the request or authentication context",
        )

    async def identity(request: Request) -> IdentityContext:
        auth_mode = os.getenv("AUTONOESIS_AUTH_MODE", "development")
        if auth_mode == "development":
            try:
                tenant_id = UUID(request.headers["X-Tenant-ID"])
                actor_id = UUID(request.headers["X-Actor-ID"])
            except (KeyError, ValueError) as exc:
                raise HTTPException(401, "development identity headers are required") from exc
            principal_id = UUID(request.headers.get("X-Principal-ID", str(actor_id)))
            roles = frozenset(
                role.strip()
                for role in request.headers.get("X-Roles", "operator").split(",")
                if role.strip()
            )
            return IdentityContext(tenant_id, actor_id, principal_id, roles)
        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            raise HTTPException(401, "bearer token is required")
        validator = OIDCValidator(
            OIDCSettings(
                issuer=os.environ["AUTONOESIS_OIDC_ISSUER"],
                audience=os.environ["AUTONOESIS_OIDC_AUDIENCE"],
                jwks_url=os.environ["AUTONOESIS_OIDC_JWKS_URL"],
            )
        )
        return validator.validate(authorization.removeprefix("Bearer "))

    def require_role(context: IdentityContext, allowed: set[str]) -> None:
        if not context.roles.intersection(allowed):
            raise PermissionError("the current principal does not have the required role")

    async def write_key(
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> str:
        if not idempotency_key.strip() or len(idempotency_key) > 300:
            raise HTTPException(400, "a bounded Idempotency-Key is required")
        return idempotency_key

    Identity = Annotated[IdentityContext, Depends(identity)]
    WriteKey = Annotated[str, Depends(write_key)]

    @app.get("/health/live", tags=["health"])
    async def liveness() -> dict[str, str]:
        return {"status": "ok", "service": "autonoesis-api"}

    @app.get("/", tags=["system"])
    async def root() -> dict[str, str]:
        return {
            "name": "Autonoesis",
            "positioning": "Goal-driven governed and evolving AI agent platform",
            "phase": "generic-platform-mvp",
            "docs": "/docs",
        }

    @app.post("/v1/capability-packs", status_code=201, tags=["configuration"])
    async def install_pack(
        body: CapabilityPackRequest, context: Identity, _: WriteKey
    ) -> dict[str, Any]:
        require_role(context, {"platform_admin", "tenant_admin", "developer"})
        manifest = parse_manifest(body.manifest)
        platform_store.register_pack(manifest)
        return {"pack_id": manifest.pack_id, "version": manifest.version, "status": "enabled"}

    @app.get("/v1/capability-packs", tags=["configuration"])
    async def list_packs(context: Identity) -> list[dict[str, Any]]:
        _ = context
        return [
            {
                "pack_id": item.pack_id,
                "version": item.version,
                "goal_types": [g.goal_type for g in item.goal_types],
            }
            for item in platform_store.packs.values()
        ]

    @app.post("/v1/agents", status_code=201, tags=["configuration"])
    async def create_agent(body: AgentRequest, context: Identity, _: WriteKey) -> dict[str, Any]:
        require_role(context, {"platform_admin", "tenant_admin", "developer"})
        definition = AgentDefinition(context.tenant_id, body.name, body.description)
        version = AgentVersion(
            tenant_id=context.tenant_id,
            agent_id=definition.agent_id,
            version=1,
            instruction=body.instruction,
            model_route=body.model_route,
            skill_ids=body.skill_ids,
            tool_ids=body.tool_ids,
            loop_policy=LoopPolicy(
                body.max_rounds, body.max_tokens, body.max_cost_units, body.timeout_seconds
            ),
            stage=AssetStage.STABLE,
        )
        platform_store.register_agent(body.name, version)
        return {
            "agent_id": definition.agent_id,
            "agent_version_id": version.agent_version_id,
            "stage": version.stage,
        }

    @app.get("/v1/agents", tags=["configuration"])
    async def list_agents(context: Identity) -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "agent_version_id": version.agent_version_id,
                "version": version.version,
                "stage": version.stage,
            }
            for (tenant_id, name), version in platform_store.agents.items()
            if tenant_id == context.tenant_id
        ]

    async def save_config_asset(
        collection: dict[str, dict[str, object]],
        body: ConfigAssetRequest,
        context: IdentityContext,
    ) -> dict[str, object]:
        require_role(context, {"platform_admin", "tenant_admin", "developer"})
        value: dict[str, object] = {
            "asset_id": body.asset_id,
            "tenant_id": str(context.tenant_id),
            "definition": body.definition,
        }
        collection[body.asset_id] = value
        return value

    @app.post("/v1/skills", status_code=201, tags=["configuration"])
    async def create_skill(
        body: ConfigAssetRequest, context: Identity, _: WriteKey
    ) -> dict[str, object]:
        return await save_config_asset(platform_store.skills, body, context)

    @app.get("/v1/skills", tags=["configuration"])
    async def list_skills(context: Identity) -> list[dict[str, object]]:
        return [
            item
            for item in platform_store.skills.values()
            if item["tenant_id"] == str(context.tenant_id)
        ]

    @app.post("/v1/tools", status_code=201, tags=["configuration"])
    async def create_tool(
        body: ConfigAssetRequest, context: Identity, _: WriteKey
    ) -> dict[str, object]:
        return await save_config_asset(platform_store.tools, body, context)

    @app.get("/v1/tools", tags=["configuration"])
    async def list_tools(context: Identity) -> list[dict[str, object]]:
        return [
            item
            for item in platform_store.tools.values()
            if item["tenant_id"] == str(context.tenant_id)
        ]

    @app.post("/v1/policies", status_code=201, tags=["governance"])
    async def create_policy(
        body: ConfigAssetRequest, context: Identity, _: WriteKey
    ) -> dict[str, object]:
        return await save_config_asset(platform_store.policies, body, context)

    @app.get("/v1/policies", tags=["governance"])
    async def list_policies(context: Identity) -> list[dict[str, object]]:
        return [
            item
            for item in platform_store.policies.values()
            if item["tenant_id"] == str(context.tenant_id)
        ]

    @app.post("/v1/budgets", status_code=201, tags=["governance"])
    async def create_budget(
        body: ConfigAssetRequest, context: Identity, _: WriteKey
    ) -> dict[str, object]:
        return await save_config_asset(platform_store.budgets, body, context)

    @app.get("/v1/budgets", tags=["governance"])
    async def list_budgets(context: Identity) -> list[dict[str, object]]:
        return [
            item
            for item in platform_store.budgets.values()
            if item["tenant_id"] == str(context.tenant_id)
        ]

    @app.post("/v1/goals", status_code=201, tags=["goals"])
    async def create_goal(body: GoalRequest, context: Identity, key: WriteKey) -> dict[str, Any]:
        cached = app.state.idempotency.get(("create_goal", context.tenant_id, key))
        if cached is not None:
            goal = await platform_store.get_goal(context.tenant_id, cached)
            return goal_view(goal)
        goal = await goal_handler(
            context,
            CreateGoal(
                goal_type=body.goal_type,
                statement=body.statement,
                desired_outcome=body.desired_outcome,
                subject_refs=tuple(SubjectRef(**item.model_dump()) for item in body.subject_refs),
                success_criteria=tuple(
                    SuccessCriterion(**item.model_dump()) for item in body.success_criteria
                ),
                constraints=body.constraints,
                owner_id=body.owner_id,
                risk_tier=body.risk_tier,
                budget_limit=body.budget_limit,
                deadline=body.deadline,
                input_payload=body.input_payload,
                correlation_id=uuid4(),
            ),
        )
        app.state.idempotency[("create_goal", context.tenant_id, key)] = goal.goal_id
        return goal_view(goal)

    @app.get("/v1/goals", tags=["goals"])
    async def list_goals(context: Identity) -> list[dict[str, Any]]:
        return [goal_view(goal) for goal in await platform_store.list_goals(context.tenant_id)]

    @app.get("/v1/goals/{goal_id}", tags=["goals"])
    async def get_goal(goal_id: UUID, context: Identity) -> dict[str, Any]:
        return goal_view(await platform_store.get_goal(context.tenant_id, goal_id))

    @app.post("/v1/goals/{goal_id}/runs", status_code=202, tags=["runs"])
    async def start_run(goal_id: UUID, context: Identity, key: WriteKey) -> dict[str, Any]:
        cached = app.state.idempotency.get(("start_run", context.tenant_id, key))
        if cached is not None:
            return run_view(await platform_store.get_run(context.tenant_id, cached))
        run = await run_handler(context, StartGoalRun(goal_id, uuid4()))
        app.state.idempotency[("start_run", context.tenant_id, key)] = run.run_id
        if os.getenv("AUTONOESIS_TEMPORAL_START", "false").lower() == "true":
            client = await Client.connect(os.getenv("AUTONOESIS_TEMPORAL_TARGET", "localhost:7233"))
            await client.start_workflow(
                "GoalRunWorkflow",
                {
                    "tenant_id": str(context.tenant_id),
                    "goal_id": str(goal_id),
                    "run_id": str(run.run_id),
                },
                id=f"goal-run-{run.run_id}",
                task_queue=os.getenv("AUTONOESIS_TEMPORAL_TASK_QUEUE", "autonoesis"),
            )
        return run_view(run)

    @app.get("/v1/runs/{run_id}", tags=["runs"])
    async def get_run(run_id: UUID, context: Identity) -> dict[str, Any]:
        return run_view(await platform_store.get_run(context.tenant_id, run_id))

    @app.get("/v1/runs/{run_id}/events", tags=["runs"])
    async def run_events(run_id: UUID, context: Identity) -> StreamingResponse:
        await platform_store.get_run(context.tenant_id, run_id)

        async def stream() -> AsyncIterator[str]:
            events = [
                event
                for event in platform_store.audits
                if event.tenant_id == context.tenant_id and event.object_id == str(run_id)
            ]
            for event in events:
                yield f"event: {event.event_type}\ndata: {json.dumps(event.details)}\n\n"
            yield "event: snapshot-complete\ndata: {}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/v1/approvals", tags=["governance"])
    async def list_approvals(context: Identity) -> list[dict[str, object]]:
        return [
            item
            for item in platform_store.approvals.values()
            if item.get("tenant_id") == str(context.tenant_id)
        ]

    @app.post("/v1/approvals/{approval_id}/decision", tags=["governance"])
    async def decide_approval(
        approval_id: UUID,
        body: ApprovalDecisionRequest,
        context: Identity,
        _: WriteKey,
    ) -> dict[str, object]:
        require_role(context, {"platform_admin", "tenant_admin", "approver"})
        approval = platform_store.approvals.get(approval_id)
        if approval is None or approval.get("tenant_id") != str(context.tenant_id):
            raise RecordNotFound("approval was not found")
        if approval.get("action_digest") != body.action_digest:
            raise PermissionError("approval does not match the exact action parameters")
        decision = "approved" if body.approved else "rejected"
        current = str(approval.get("status", "pending"))
        if current != "pending" and current != decision:
            raise ValueError("approval has already received a different decision")
        approval.update(
            {
                "status": decision,
                "decided_by": str(context.actor_id),
                "reason": body.reason,
            }
        )
        return approval

    @app.get("/v1/evidence", tags=["evidence"])
    async def list_evidence(context: Identity) -> list[dict[str, object]]:
        return [
            item
            for item in platform_store.evidence.values()
            if item.get("tenant_id") == str(context.tenant_id)
        ]

    @app.get("/v1/evaluation-suites", tags=["evaluation"])
    async def evaluation_suites(context: Identity) -> list[str]:
        _ = context
        return sorted(
            {suite for pack in platform_store.packs.values() for suite in pack.evaluation_suites}
        )

    @app.get("/v1/trials", tags=["evaluation"])
    async def trials(context: Identity) -> list[object]:
        _ = context
        return []

    @app.post("/v1/improvement-proposals", status_code=201, tags=["improvement"])
    async def create_proposal(
        body: ImprovementProposalRequest, context: Identity, _: WriteKey
    ) -> dict[str, Any]:
        proposal = ImprovementProposal(
            tenant_id=context.tenant_id,
            target=body.target,
            target_version_id=body.target_version_id,
            evidence_refs=body.evidence_refs,
            diagnosis=body.diagnosis,
            proposed_change=body.proposed_change,
            validation_suite_id=body.validation_suite_id,
            rollback_plan=body.rollback_plan,
            proposer_id=body.proposer_id,
        )
        platform_store.proposals[proposal.proposal_id] = proposal
        return {"proposal_id": proposal.proposal_id, "target": proposal.target}

    @app.get("/v1/improvement-proposals", tags=["improvement"])
    async def list_proposals(context: Identity) -> list[dict[str, Any]]:
        return [
            {"proposal_id": item.proposal_id, "target": item.target, "diagnosis": item.diagnosis}
            for item in platform_store.proposals.values()
            if item.tenant_id == context.tenant_id
        ]

    @app.post("/v1/candidates", status_code=201, tags=["improvement"])
    async def create_candidate(
        body: CandidateRequest, context: Identity, _: WriteKey
    ) -> dict[str, Any]:
        if body.proposal_id not in platform_store.proposals:
            raise RecordNotFound("proposal was not found")
        candidate = CandidateVersion(
            tenant_id=context.tenant_id,
            proposal_id=body.proposal_id,
            baseline_version_id=body.baseline_version_id,
            artifact_ref=body.artifact_ref,
            generator_id=body.generator_id,
        )
        await platform_store.add_candidate(candidate)
        return candidate_view(candidate)

    @app.post("/v1/candidates/{candidate_id}/evaluate", tags=["improvement"])
    async def evaluate_candidate(
        candidate_id: UUID, body: EvaluationRequest, context: Identity, _: WriteKey
    ) -> dict[str, Any]:
        await evolution.submit_for_evaluation(context.tenant_id, candidate_id)
        candidate = await evolution.record_evaluation(
            context.tenant_id,
            candidate_id,
            EvaluationDecision(body.passed, body.score, body.grader_id, body.threshold),
        )
        return candidate_view(candidate)

    @app.post("/v1/candidates/{candidate_id}/decision", tags=["improvement"])
    async def decide_candidate(
        candidate_id: UUID, body: CandidateDecisionRequest, context: Identity, _: WriteKey
    ) -> dict[str, Any]:
        require_role(context, {"platform_admin", "tenant_admin", "approver"})
        return candidate_view(await evolution.decide(context, candidate_id, body.approved))

    @app.post("/v1/candidates/{candidate_id}/promote", tags=["improvement"])
    async def promote_candidate(
        candidate_id: UUID, body: PromotionRequest, context: Identity, _: WriteKey
    ) -> dict[str, Any]:
        require_role(context, {"platform_admin", "tenant_admin", "approver"})
        release = await evolution.promote(context, candidate_id, body.stable_version_id)
        return {
            "release_id": release.release_id,
            "stable_version_id": release.stable_version_id,
            "previous_stable_version_id": release.previous_stable_version_id,
        }

    @app.post("/v1/releases/{release_id}/rollback", tags=["improvement"])
    async def rollback_release(release_id: UUID, context: Identity, _: WriteKey) -> dict[str, Any]:
        require_role(context, {"platform_admin", "tenant_admin", "approver"})
        release = await evolution.rollback(context, release_id)
        await platform_store.add_release(release)
        return {
            "release_id": release.release_id,
            "stable_version_id": release.stable_version_id,
            "rollback_of": release_id,
        }

    @app.get("/v1/releases", tags=["improvement"])
    async def list_releases(context: Identity) -> list[dict[str, Any]]:
        return [
            {
                "release_id": item.release_id,
                "stable_version_id": item.stable_version_id,
                "candidate_id": item.candidate_id,
            }
            for item in platform_store.releases.values()
            if item.tenant_id == context.tenant_id
        ]

    @app.get("/v1/audit-events", tags=["audit"])
    async def list_audit_events(context: Identity) -> list[dict[str, Any]]:
        require_role(context, {"platform_admin", "tenant_admin", "auditor", "operator"})
        return [
            {
                "event_type": item.event_type,
                "object_type": item.object_type,
                "object_id": item.object_id,
                "correlation_id": item.correlation_id,
                "details": item.details,
            }
            for item in platform_store.audits
            if item.tenant_id == context.tenant_id
        ]

    return app


def goal_view(goal: GoalContract) -> dict[str, Any]:
    return {
        "goal_id": goal.goal_id,
        "goal_type": goal.goal_type,
        "statement": goal.statement,
        "desired_outcome": goal.desired_outcome,
        "subjects": [
            {
                "system": item.system,
                "type": item.subject_type,
                "id": item.subject_id,
                "version": item.version,
            }
            for item in goal.subject_refs
        ],
        "status": goal.status,
        "version": goal.version,
        "budget_limit": goal.budget_limit,
        "deadline": goal.deadline,
    }


def run_view(run: Any) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "goal_id": run.goal_id,
        "agent_version_id": run.agent_version_id,
        "status": run.status,
        "version": run.optimistic_version,
    }


def candidate_view(candidate: CandidateVersion) -> dict[str, Any]:
    return {
        "candidate_id": candidate.candidate_id,
        "proposal_id": candidate.proposal_id,
        "baseline_version_id": candidate.baseline_version_id,
        "artifact_ref": candidate.artifact_ref,
        "status": candidate.status,
    }


def configured_store() -> InMemoryPlatformStore:
    database_url = os.getenv("AUTONOESIS_DATABASE_URL")
    store: InMemoryPlatformStore
    if database_url:
        store = PostgreSQLPlatformStore.from_url(database_url)
    else:
        store = InMemoryPlatformStore()
    pack_path = os.getenv("AUTONOESIS_CAPABILITY_PACK")
    if pack_path:
        store.register_pack(load_manifest(Path(pack_path)))
    return store


app = build_app(configured_store())
