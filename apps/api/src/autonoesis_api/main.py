"""Industry-neutral Autonoesis control-plane API."""

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID, uuid4

from autonoesis_adapters import (
    InMemoryPlatformStore,
    OIDCSettings,
    OIDCValidator,
    PostgreSQLPlatformStore,
    SqlKillSwitchStore,
    SqlPlatformKillSwitchStore,
)
from autonoesis_application import (
    ActivateGoal,
    AuditEvent,
    CandidateLifecycleService,
    CommandContext,
    ConcurrencyConflict,
    CreateGoal,
    DecideApproval,
    EvaluationDecision,
    GoalExecutionApplication,
    IdentityContext,
    RecordNotFound,
    RequestRun,
    TenantBoundaryViolation,
)
from autonoesis_capability import ManifestError, load_manifest, parse_manifest
from autonoesis_domain import (
    AgentDefinition,
    AgentVersion,
    ApprovalRequest,
    AssetStage,
    BudgetUnit,
    CandidateVersion,
    DataClassification,
    Evidence,
    ExecutionMode,
    GoalContract,
    ImprovementProposal,
    ImprovementTarget,
    LoopPolicy,
    RiskTier,
    SubjectRef,
    SuccessCriterion,
    Trial,
)
from autonoesis_governance import InMemoryKillSwitchStore, KillSwitchDimension
from autonoesis_runtime import IsolationRiskPool, TenantNamespaces
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from temporalio.client import Client


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorDetail(BaseModel):
    code: str
    message: str
    retryable: bool
    next_action: str
    correlation_id: UUID
    audit_ref: str | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


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
    risk_tier: RiskTier = RiskTier.MEDIUM
    budget_limit: int | None = Field(default=None, ge=1)
    budget_unit: BudgetUnit = BudgetUnit.COST_UNITS
    deadline: datetime
    input_payload: dict[str, Any]
    delegation_id: UUID | None = None
    maximum_classification: DataClassification = DataClassification.INTERNAL
    allowed_regions: tuple[str, ...] = ()
    retention_days: int = Field(default=30, ge=1)
    execution_mode: ExecutionMode = ExecutionMode.SUPERVISED
    max_concurrent_runs: int = Field(default=1, ge=1)


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
                # No reference is emitted until an AuditEvent has actually been committed.
                "audit_ref": None,
            }
        },
    )


PlatformStore = InMemoryPlatformStore | PostgreSQLPlatformStore


def build_app(
    store: PlatformStore | None = None, platform_kill_switch: Any | None = None
) -> FastAPI:
    platform_store = store or InMemoryPlatformStore()
    breakglass_engine = None
    if platform_kill_switch is None and isinstance(platform_store, PostgreSQLPlatformStore):
        breakglass_url = os.getenv("AUTONOESIS_BREAKGLASS_DATABASE_URL")
        if breakglass_url:
            breakglass_engine = create_async_engine(breakglass_url, pool_pre_ping=True)
            platform_kill_switch = SqlPlatformKillSwitchStore(
                async_sessionmaker(breakglass_engine, expire_on_commit=False)
            )
    if platform_kill_switch is None and isinstance(platform_store, InMemoryPlatformStore):
        platform_kill_switch = InMemoryKillSwitchStore()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        pack_path = os.getenv("AUTONOESIS_CAPABILITY_PACK")
        if pack_path:
            manifest = load_manifest(Path(pack_path))
            if isinstance(platform_store, PostgreSQLPlatformStore):
                tenant_value = os.getenv("AUTONOESIS_BOOTSTRAP_TENANT_ID")
                if tenant_value is None:
                    raise RuntimeError(
                        "AUTONOESIS_BOOTSTRAP_TENANT_ID is required for a production pack"
                    )
                tenant_id = UUID(tenant_value)
                await platform_store.add_capability_pack(tenant_id, manifest)
            else:
                platform_store.register_pack(manifest)
        yield
        if isinstance(platform_store, PostgreSQLPlatformStore):
            await platform_store.close()
        if breakglass_engine is not None:
            await breakglass_engine.dispose()

    app = FastAPI(
        title="Autonoesis API",
        description="Engineering preview of a goal-driven governed agent platform",
        version="0.1.0",
        lifespan=lifespan,
        responses={
            status: {
                "model": ErrorEnvelope,
                "description": "Common tenant-safe error envelope",
            }
            for status in (400, 401, 403, 404, 409, 422, 500)
        },
    )
    app.state.store = platform_store
    app.state.kill_switch = (
        SqlKillSwitchStore(platform_store.repository.sessions)
        if isinstance(platform_store, PostgreSQLPlatformStore)
        else platform_kill_switch or InMemoryKillSwitchStore()
    )
    app.state.platform_kill_switch = platform_kill_switch

    def kill_switch_for(context: IdentityContext) -> Any:
        if isinstance(app.state.kill_switch, SqlKillSwitchStore):
            return app.state.kill_switch.for_tenant(context.tenant_id)
        return app.state.kill_switch

    execution = GoalExecutionApplication(platform_store.repository, platform_store)
    evolution = CandidateLifecycleService(platform_store)

    @app.exception_handler(RecordNotFound)
    @app.exception_handler(TenantBoundaryViolation)
    async def hidden_record(request: Request, __: Exception) -> JSONResponse:
        requester = getattr(request.state, "identity", None)
        if isinstance(requester, IdentityContext):
            try:
                correlation_id = UUID(request.headers.get("X-Correlation-ID", str(uuid4())))
            except ValueError:
                correlation_id = uuid4()
            await platform_store.repository.record_audit(
                AuditEvent(
                    tenant_id=requester.tenant_id,
                    actor_id=requester.actor_id,
                    principal_id=requester.principal_id,
                    event_type="security.tenant_scope_lookup_denied",
                    object_type="http_resource",
                    object_id=sha256(request.url.path.encode()).hexdigest(),
                    correlation_id=correlation_id,
                    details={"method": request.method, "result": "not_found"},
                )
            )
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

    @app.exception_handler(RequestValidationError)
    async def request_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {"msg": "request validation failed"}
        return error_response(
            422,
            "invalid_request",
            str(first.get("msg", "request validation failed")),
            False,
            "correct the request",
        )

    @app.exception_handler(PermissionError)
    async def forbidden(_: Request, exc: PermissionError) -> JSONResponse:
        return error_response(403, "permission_denied", str(exc), False, "request authorization")

    @app.exception_handler(ConcurrencyConflict)
    async def conflict(_: Request, exc: ConcurrencyConflict) -> JSONResponse:
        return error_response(
            409,
            "concurrency_conflict",
            str(exc),
            True,
            "reload authoritative state and retry with a new idempotency key",
        )

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
            resolved = IdentityContext(tenant_id, actor_id, principal_id, roles)
            request.state.identity = resolved
            return resolved
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
        resolved = validator.validate(authorization.removeprefix("Bearer "))
        request.state.identity = resolved
        return resolved

    def require_role(context: IdentityContext, allowed: set[str]) -> None:
        if not context.roles.intersection(allowed):
            raise PermissionError("the current principal does not have the required role")

    def command_context(
        request: Request,
        identity_context: IdentityContext,
        idempotency_key: str,
        payload: object,
    ) -> CommandContext:
        try:
            correlation_id = UUID(request.headers.get("X-Correlation-ID", str(uuid4())))
            causation_id = UUID(request.headers.get("X-Causation-ID", str(correlation_id)))
        except ValueError as exc:
            raise HTTPException(400, "correlation and causation headers must be UUIDs") from exc
        request_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        request_digest = sha256(
            f"{request.method}\n{request.url.path}\n{request_payload}".encode()
        ).hexdigest()
        return CommandContext(
            identity_context,
            correlation_id,
            causation_id,
            idempotency_key,
            request_digest,
        )

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
            "positioning": "Goal-driven governed agent platform engineering preview",
            "phase": "engineering-preview",
            "docs": "/docs",
        }

    @app.post("/v1/capability-packs", status_code=201, tags=["configuration"])
    async def install_pack(
        body: CapabilityPackRequest, context: Identity, _: WriteKey
    ) -> dict[str, Any]:
        require_role(context, {"platform_admin", "tenant_admin", "developer"})
        manifest = parse_manifest(body.manifest)
        await platform_store.add_capability_pack(context.tenant_id, manifest)
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
            for item in await platform_store.list_capability_packs(context.tenant_id)
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
        await platform_store.add_agent(body.name, version)
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
            for name, version in await platform_store.list_agents(context.tenant_id)
        ]

    @app.post("/v1/skills", status_code=201, tags=["configuration"])
    async def create_skill(
        body: ConfigAssetRequest, context: Identity, _: WriteKey
    ) -> dict[str, object]:
        require_role(context, {"platform_admin", "tenant_admin", "developer"})
        return await platform_store.add_skill(context.tenant_id, body.asset_id, body.definition)

    @app.get("/v1/skills", tags=["configuration"])
    async def list_skills(context: Identity) -> list[dict[str, object]]:
        return list(await platform_store.list_skills(context.tenant_id))

    @app.post("/v1/tools", status_code=201, tags=["configuration"])
    async def create_tool(
        body: ConfigAssetRequest, context: Identity, _: WriteKey
    ) -> dict[str, object]:
        require_role(context, {"platform_admin", "tenant_admin", "developer"})
        return await platform_store.add_tool(context.tenant_id, body.asset_id, body.definition)

    @app.get("/v1/tools", tags=["configuration"])
    async def list_tools(context: Identity) -> list[dict[str, object]]:
        return list(await platform_store.list_tools(context.tenant_id))

    @app.post("/v1/policies", status_code=201, tags=["governance"])
    async def create_policy(
        body: ConfigAssetRequest, context: Identity, _: WriteKey
    ) -> dict[str, object]:
        require_role(context, {"platform_admin", "tenant_admin", "developer"})
        return await platform_store.add_policy(context.tenant_id, body.asset_id, body.definition)

    @app.get("/v1/policies", tags=["governance"])
    async def list_policies(context: Identity) -> list[dict[str, object]]:
        return list(await platform_store.list_policies(context.tenant_id))

    @app.post("/v1/budgets", status_code=201, tags=["governance"])
    async def create_budget(
        body: ConfigAssetRequest, context: Identity, _: WriteKey
    ) -> dict[str, object]:
        require_role(context, {"platform_admin", "tenant_admin", "developer"})
        return await platform_store.add_budget(context.tenant_id, body.asset_id, body.definition)

    @app.get("/v1/budgets", tags=["governance"])
    async def list_budgets(context: Identity) -> list[dict[str, object]]:
        return list(await platform_store.list_budgets(context.tenant_id))

    # ── Kill Switch ────────────────────────────────────────────────────

    class KillSwitchActivateRequest(StrictRequest):
        dimension: str = Field(min_length=1, max_length=32)
        target: str = Field(min_length=1, max_length=300)
        reason: str = Field(min_length=1, max_length=1000)

    class KillSwitchDeactivateRequest(StrictRequest):
        dimension: str = Field(min_length=1, max_length=32)
        target: str = Field(min_length=1, max_length=300)

    class BreakGlassKillSwitchRequest(StrictRequest):
        reason: str = Field(min_length=20, max_length=1000)

    @app.post("/v1/kill-switches", status_code=201, tags=["governance"])
    async def activate_kill_switch(
        body: KillSwitchActivateRequest, context: Identity, _: WriteKey
    ) -> dict[str, Any]:
        require_role(context, {"platform_admin", "tenant_admin", "operator"})
        dimension = KillSwitchDimension(body.dimension)
        if dimension is KillSwitchDimension.PLATFORM:
            raise PermissionError("platform control requires the break-glass endpoint")
        if dimension is KillSwitchDimension.TENANT and body.target != str(context.tenant_id):
            raise TenantBoundaryViolation("tenant kill switch target is outside the current scope")
        record = await kill_switch_for(context).activate(
            dimension,
            body.target,
            body.reason,
            str(context.actor_id),
        )
        return {
            "kill_switch_id": str(record.kill_switch_id),
            "dimension": record.dimension.value,
            "target": record.target,
            "reason": record.reason,
            "activated_by": record.activated_by,
            "activated_at": record.activated_at.isoformat(),
        }

    @app.delete("/v1/kill-switches", tags=["governance"])
    async def deactivate_kill_switch(
        body: KillSwitchDeactivateRequest, context: Identity, _: WriteKey
    ) -> dict[str, Any]:
        require_role(context, {"platform_admin", "tenant_admin", "operator"})
        dimension = KillSwitchDimension(body.dimension)
        if dimension is KillSwitchDimension.PLATFORM:
            raise PermissionError("platform control requires the break-glass endpoint")
        if dimension is KillSwitchDimension.TENANT and body.target != str(context.tenant_id):
            raise TenantBoundaryViolation("tenant kill switch target is outside the current scope")
        record = await kill_switch_for(context).deactivate(dimension, body.target)
        if record is None:
            raise HTTPException(status_code=404, detail="no active kill switch for that target")
        return {
            "kill_switch_id": str(record.kill_switch_id),
            "dimension": record.dimension.value,
            "target": record.target,
            "deactivated_at": record.deactivated_at.isoformat() if record.deactivated_at else None,
        }

    @app.get("/v1/kill-switches", tags=["governance"])
    async def list_kill_switches(context: Identity) -> list[dict[str, Any]]:
        require_role(context, {"platform_admin", "tenant_admin", "operator", "auditor"})
        return [
            {
                "kill_switch_id": str(r.kill_switch_id),
                "dimension": r.dimension.value,
                "target": r.target,
                "reason": r.reason,
                "activated_by": r.activated_by,
                "activated_at": r.activated_at.isoformat(),
            }
            for r in await kill_switch_for(context).list_active()
        ]

    @app.post("/v1/platform/break-glass/kill-switch", status_code=201, tags=["platform-security"])
    async def activate_platform_kill_switch(
        body: BreakGlassKillSwitchRequest,
        context: Identity,
        _: WriteKey,
        ticket: Annotated[str, Header(alias="X-Break-Glass-Ticket")],
    ) -> dict[str, Any]:
        require_role(context, {"break_glass"})
        if len(ticket.strip()) < 8 or app.state.platform_kill_switch is None:
            raise PermissionError("a configured break-glass identity and ticket are required")
        correlation_id = uuid4()
        reason = f"ticket={ticket.strip()}; {body.reason}"
        if isinstance(app.state.platform_kill_switch, SqlPlatformKillSwitchStore):
            record = await app.state.platform_kill_switch.activate(
                reason, context.actor_id, context.principal_id, correlation_id
            )
        else:
            record = await app.state.platform_kill_switch.activate(
                KillSwitchDimension.PLATFORM, "platform", reason, str(context.actor_id)
            )
            await platform_store.repository.record_audit(
                AuditEvent(
                    context.tenant_id,
                    context.actor_id,
                    context.principal_id,
                    "platform.kill_switch.activated",
                    "platform",
                    str(record.kill_switch_id),
                    correlation_id,
                    {"ticket": ticket.strip()},
                )
            )
        return {
            "kill_switch_id": str(record.kill_switch_id),
            "dimension": "platform",
            "target": "platform",
            "activated_at": record.activated_at.isoformat(),
        }

    @app.delete("/v1/platform/break-glass/kill-switch", tags=["platform-security"])
    async def deactivate_platform_kill_switch(
        body: BreakGlassKillSwitchRequest,
        context: Identity,
        _: WriteKey,
        ticket: Annotated[str, Header(alias="X-Break-Glass-Ticket")],
    ) -> dict[str, Any]:
        require_role(context, {"break_glass"})
        if len(ticket.strip()) < 8 or app.state.platform_kill_switch is None:
            raise PermissionError("a configured break-glass identity and ticket are required")
        correlation_id = uuid4()
        reason = f"ticket={ticket.strip()}; {body.reason}"
        if isinstance(app.state.platform_kill_switch, SqlPlatformKillSwitchStore):
            record = await app.state.platform_kill_switch.deactivate(
                reason, context.actor_id, context.principal_id, correlation_id
            )
        else:
            record = await app.state.platform_kill_switch.deactivate(
                KillSwitchDimension.PLATFORM, "platform"
            )
            if record is not None:
                await platform_store.repository.record_audit(
                    AuditEvent(
                        context.tenant_id,
                        context.actor_id,
                        context.principal_id,
                        "platform.kill_switch.deactivated",
                        "platform",
                        str(record.kill_switch_id),
                        correlation_id,
                        {"ticket": ticket.strip()},
                    )
                )
        if record is None:
            raise HTTPException(404, "no active platform kill switch")
        return {
            "kill_switch_id": str(record.kill_switch_id),
            "dimension": "platform",
            "target": "platform",
            "deactivated_at": record.deactivated_at.isoformat() if record.deactivated_at else None,
        }

    @app.post("/v1/goals", status_code=201, tags=["goals"])
    async def create_goal(
        body: GoalRequest, request: Request, context: Identity, key: WriteKey
    ) -> dict[str, Any]:
        use_case_context = command_context(request, context, key, body.model_dump(mode="json"))
        goal = await execution.create_goal(
            use_case_context,
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
                budget_unit=body.budget_unit,
                deadline=body.deadline,
                input_payload=body.input_payload,
                delegation_id=body.delegation_id,
                maximum_classification=body.maximum_classification,
                allowed_regions=body.allowed_regions,
                retention_days=body.retention_days,
                execution_mode=body.execution_mode,
                max_concurrent_runs=body.max_concurrent_runs,
                correlation_id=use_case_context.correlation_id,
            ),
        )
        return goal_view(goal)

    @app.post("/v1/goals/{goal_id}/activation", tags=["goals"])
    async def activate_goal(
        goal_id: UUID, request: Request, context: Identity, key: WriteKey
    ) -> dict[str, Any]:
        return goal_view(
            await execution.activate_goal(
                command_context(request, context, key, {"goal_id": str(goal_id)}),
                ActivateGoal(goal_id),
            )
        )

    @app.get("/v1/goals", tags=["goals"])
    async def list_goals(context: Identity) -> list[dict[str, Any]]:
        return [goal_view(goal) for goal in await platform_store.list_goals(context.tenant_id)]

    @app.get("/v1/goals/{goal_id}", tags=["goals"])
    async def get_goal(goal_id: UUID, context: Identity) -> dict[str, Any]:
        return goal_view(await platform_store.get_goal(context.tenant_id, goal_id))

    @app.post("/v1/goals/{goal_id}/runs", status_code=202, tags=["runs"])
    async def start_run(
        goal_id: UUID, request: Request, context: Identity, key: WriteKey
    ) -> dict[str, Any]:
        run = await execution.request_run(
            command_context(request, context, key, {"goal_id": str(goal_id)}),
            RequestRun(goal_id),
        )
        if os.getenv("AUTONOESIS_TEMPORAL_START", "false").lower() == "true":
            goal = await platform_store.get_goal(context.tenant_id, goal_id)
            boundaries = TenantNamespaces(context.tenant_id)
            risk_pool = IsolationRiskPool.from_risk_tier(goal.risk_tier.value)
            isolated = os.getenv("AUTONOESIS_TENANT_ISOLATED_WORKFLOWS", "true").lower() == "true"
            namespace = (
                boundaries.workflow_namespace(risk_pool)
                if isolated
                else os.getenv("AUTONOESIS_TEMPORAL_NAMESPACE", "default")
            )
            task_queue = (
                boundaries.workflow_task_queue(risk_pool)
                if isolated
                else os.getenv("AUTONOESIS_TEMPORAL_TASK_QUEUE", "autonoesis")
            )
            client = await Client.connect(
                os.getenv("AUTONOESIS_TEMPORAL_TARGET", "localhost:7233"), namespace=namespace
            )
            await client.start_workflow(
                "GoalRunWorkflow",
                {
                    "tenant_id": str(context.tenant_id),
                    "goal_id": str(goal_id),
                    "run_id": str(run.run_id),
                    "deadline_epoch_seconds": goal.deadline.timestamp(),
                    "requires_approval": goal.risk_tier.value in {"high", "critical"},
                    "risk_tier": goal.risk_tier.value,
                },
                id=boundaries.workflow_id(run.run_id),
                task_queue=task_queue,
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
                for event in await platform_store.list_audit_events(context.tenant_id)
                if event.object_id == str(run_id)
            ]
            for event in events:
                yield f"event: {event.event_type}\ndata: {json.dumps(event.details)}\n\n"
            yield "event: snapshot-complete\ndata: {}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/v1/approvals", tags=["governance"])
    async def list_approvals(context: Identity) -> list[dict[str, object]]:
        return [
            approval_view(item) for item in await platform_store.list_approvals(context.tenant_id)
        ]

    @app.post("/v1/approvals/{approval_id}/decision", tags=["governance"])
    async def decide_approval(
        approval_id: UUID,
        body: ApprovalDecisionRequest,
        request: Request,
        context: Identity,
        key: WriteKey,
    ) -> dict[str, object]:
        decided = await execution.decide_approval(
            command_context(
                request,
                context,
                key,
                {"approval_id": str(approval_id), **body.model_dump(mode="json")},
            ),
            DecideApproval(approval_id, body.action_digest, body.approved, body.reason),
        )
        return approval_view(decided)

    @app.get("/v1/evidence", tags=["evidence"])
    async def list_evidence(context: Identity) -> list[dict[str, object]]:
        return [
            evidence_view(item) for item in await platform_store.list_evidence(context.tenant_id)
        ]

    @app.get("/v1/evaluation-suites", tags=["evaluation"])
    async def evaluation_suites(context: Identity) -> list[str]:
        _ = context
        return sorted(
            {
                suite
                for pack in await platform_store.list_capability_packs(context.tenant_id)
                for suite in pack.evaluation_suites
            }
        )

    @app.get("/v1/trials", tags=["evaluation"])
    async def trials(context: Identity) -> list[object]:
        return [trial_view(item) for item in await platform_store.list_trials(context.tenant_id)]

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
        await platform_store.add_proposal(proposal)
        return {"proposal_id": proposal.proposal_id, "target": proposal.target}

    @app.get("/v1/improvement-proposals", tags=["improvement"])
    async def list_proposals(context: Identity) -> list[dict[str, Any]]:
        return [
            {"proposal_id": item.proposal_id, "target": item.target, "diagnosis": item.diagnosis}
            for item in await platform_store.list_proposals(context.tenant_id)
        ]

    @app.post("/v1/candidates", status_code=201, tags=["improvement"])
    async def create_candidate(
        body: CandidateRequest, context: Identity, _: WriteKey
    ) -> dict[str, Any]:
        await platform_store.get_proposal(context.tenant_id, body.proposal_id)
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
        candidate_id: UUID, context: Identity, _: WriteKey
    ) -> dict[str, Any]:
        require_role(context, {"platform_admin", "tenant_admin", "approver"})
        deployment = await evolution.begin_shadow(context, candidate_id)
        return {
            "deployment_id": deployment.deployment_id,
            "candidate_id": deployment.candidate_id,
            "status": deployment.status,
        }

    @app.post("/v1/deployments/{deployment_id}/canary", tags=["improvement"])
    async def promote_deployment_to_canary(
        deployment_id: UUID, context: Identity, _: WriteKey
    ) -> dict[str, Any]:
        require_role(context, {"platform_admin", "tenant_admin", "approver"})
        deployment = await evolution.promote_to_canary(context, deployment_id)
        return {"deployment_id": deployment.deployment_id, "status": deployment.status}

    @app.post("/v1/deployments/{deployment_id}/stable", tags=["improvement"])
    async def promote_deployment_to_stable(
        deployment_id: UUID, body: PromotionRequest, context: Identity, _: WriteKey
    ) -> dict[str, Any]:
        require_role(context, {"platform_admin", "tenant_admin", "approver"})
        release = await evolution.release_stable(context, deployment_id, body.stable_version_id)
        return {
            "release_id": release.release_id,
            "deployment_id": release.deployment_id,
            "stable_version_id": release.stable_version_id,
            "previous_stable_version_id": release.previous_stable_version_id,
        }

    @app.post("/v1/releases/{release_id}/rollback", tags=["improvement"])
    async def rollback_release(release_id: UUID, context: Identity, _: WriteKey) -> dict[str, Any]:
        require_role(context, {"platform_admin", "tenant_admin", "approver"})
        release = await evolution.rollback(context, release_id)
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
            for item in await platform_store.list_releases(context.tenant_id)
        ]

    @app.get("/v1/audit-events", tags=["audit"])
    async def list_audit_events(context: Identity) -> list[dict[str, Any]]:
        require_role(context, {"platform_admin", "tenant_admin", "auditor", "operator"})
        return [
            {
                "event_id": item.event_id,
                "event_type": item.event_type,
                "object_type": item.object_type,
                "object_id": item.object_id,
                "correlation_id": item.correlation_id,
                "sequence": item.sequence,
                "previous_digest": item.previous_digest,
                "event_digest": item.event_digest,
                "audit_ref": item.audit_ref,
                "details": item.details,
            }
            for item in await platform_store.list_audit_events(context.tenant_id)
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
        "risk_tier": goal.risk_tier,
        "budget_limit": goal.budget_limit.amount,
        "budget_unit": goal.budget_limit.unit,
        "execution_mode": goal.execution_mode,
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


def approval_view(item: ApprovalRequest | dict[str, object]) -> dict[str, object]:
    if isinstance(item, dict):
        return item
    return {
        "approval_id": str(item.approval_id),
        "tenant_id": str(item.tenant_id),
        "run_id": str(item.run_id),
        "action_id": str(item.action_id),
        "action_digest": item.action_digest,
        "status": item.status.value,
        "expires_at": item.expires_at.isoformat(),
        "decided_by": str(item.decided_by) if item.decided_by else None,
        "reason": item.reason,
    }


def evidence_view(item: Evidence | dict[str, object]) -> dict[str, object]:
    if isinstance(item, dict):
        return item
    return {
        "evidence_id": str(item.evidence_id),
        "tenant_id": str(item.tenant_id),
        "run_id": str(item.run_id),
        "action_id": str(item.action_id),
        "source": item.source,
        "reference": item.reference,
        "content_digest": item.content_digest,
        "integrity": item.integrity.value,
    }


def trial_view(item: Trial) -> dict[str, object]:
    return {
        "trial_id": str(item.trial_id),
        "suite_id": item.suite_id,
        "suite_version": item.suite_version,
        "subject_version_id": str(item.subject_version_id),
        "harness_version": item.harness_version,
        "status": item.status.value,
    }


def configured_store() -> PlatformStore:
    database_url = os.getenv("AUTONOESIS_DATABASE_URL")
    store: PlatformStore
    if database_url:
        store = PostgreSQLPlatformStore.from_url(database_url)
    else:
        store = InMemoryPlatformStore()
    return store


app = build_app(configured_store())
