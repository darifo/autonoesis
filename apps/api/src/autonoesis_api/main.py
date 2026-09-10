"""Industry-neutral Autonoesis control-plane API."""

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID, uuid4

from autonoesis_adapters import (
    InMemoryPlatformStore,
    InMemoryTemporaryAuthorizationStore,
    OIDCSettings,
    OPAImprovementTargetPolicy,
    PostgreSQLPlatformStore,
    PostgreSQLTemporaryAuthorizationStore,
    SqlKillSwitchStore,
    SqlPlatformKillSwitchStore,
    SqlShadowWriteGuard,
    StrictSupplyChainVerifier,
    cached_oidc_validator,
)
from autonoesis_adapters.observability import (
    AuditEventSloProjector,
    CanaryRunRouter,
    CostPhaseLedger,
)
from autonoesis_adapters.telemetry import (
    configure_json_logging,
    configure_telemetry,
)
from autonoesis_adapters.telemetry import (
    tracer as platform_tracer,
)
from autonoesis_application import (
    ActivateGoal,
    AuditEvent,
    CancelRun,
    CandidateLifecycleService,
    CapabilityPackService,
    CommandContext,
    ConcurrencyConflict,
    CreateGoal,
    DecideApproval,
    GoalExecutionApplication,
    IdentityContext,
    ImprovementTargetPolicy,
    PackArtifactVerifier,
    PackLifecycleCommand,
    ProposeImprovement,
    ReconcileUnknownAction,
    RecordNotFound,
    RecordObservation,
    RegisterCandidate,
    RequestRun,
    TakeOverRun,
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
    DeploymentStatus,
    Evidence,
    ExecutionMode,
    GoalContract,
    GuardrailOperator,
    ImprovementTarget,
    LoopPolicy,
    RiskTier,
    SubjectRef,
    SuccessCriterion,
    TemporaryAuthorization,
    Trial,
)
from autonoesis_evaluation import RepeatedTrialPolicy
from autonoesis_governance import InMemoryKillSwitchStore, KillSwitchDimension
from autonoesis_runtime import IsolationRiskPool, TenantNamespaces
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.middleware.base import BaseHTTPMiddleware
from temporalio.client import Client

from autonoesis_api.release_dispatch import (
    ReleaseCommandDispatcher,
    TemporalReleaseCommandDispatcher,
)
from autonoesis_api.shadow_dispatch import (
    ShadowWorkflowDispatcher,
    TemporalShadowWorkflowDispatcher,
)


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


class RunControlRequest(StrictRequest):
    reason: str = Field(min_length=8, max_length=1000)


class ReconcileRequest(StrictRequest):
    invocation_id: UUID
    succeeded: bool
    receipt_ref: str = Field(min_length=1, max_length=500)
    failure_reason: str | None = Field(default=None, max_length=1000)


class PackReasonRequest(StrictRequest):
    reason: str = Field(min_length=8, max_length=1000)


class PackStableRequest(StrictRequest):
    version: str = Field(min_length=5, max_length=64)
    reason: str = Field(min_length=8, max_length=1000)


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


class CandidateRequest(StrictRequest):
    proposal_id: UUID
    baseline_version_id: UUID
    artifact_ref: str
    artifact_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    suite_id: str = Field(min_length=1, max_length=200)
    suite_version: str = Field(min_length=1, max_length=64)


class CandidateDecisionRequest(StrictRequest):
    approved: bool
    reason: str = Field(min_length=1, max_length=2000)


class ApprovalDecisionRequest(StrictRequest):
    approved: bool
    reason: str = Field(min_length=1, max_length=2000)
    action_digest: str = Field(min_length=64, max_length=64)


class PromotionRequest(StrictRequest):
    stable_version_id: UUID
    min_samples: int = Field(default=1, ge=1)
    observation_seconds: int = Field(default=0, ge=0)
    required_metrics: tuple[str, ...] = ()


class CanaryRequest(StrictRequest):
    candidate_percent: int = Field(ge=1, le=100)
    salt: str = Field(min_length=1, max_length=200)


class ObservationRequest(StrictRequest):
    deployment_id: UUID
    stage: DeploymentStatus
    metric: str = Field(min_length=1, max_length=300)
    value: float
    operator: GuardrailOperator | None = None
    threshold: float | None = None


class ShadowDispatchRequest(StrictRequest):
    request_id: UUID
    input_payload: dict[str, Any]


class TemporaryAuthorizationRequest(StrictRequest):
    principal_id: UUID
    reason: str = Field(min_length=8, max_length=1000)
    ttl_minutes: int = Field(default=15, ge=1, le=60)


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
    store: PlatformStore | None = None,
    platform_kill_switch: Any | None = None,
    improvement_policy: ImprovementTargetPolicy | None = None,
    evaluation_policy: RepeatedTrialPolicy | None = None,
    shadow_dispatcher: ShadowWorkflowDispatcher | None = None,
    release_dispatcher: ReleaseCommandDispatcher | None = None,
    pack_verifier: PackArtifactVerifier | None = None,
) -> FastAPI:
    platform_store = store or InMemoryPlatformStore()
    resolved_pack_verifier = pack_verifier or StrictSupplyChainVerifier.from_env()
    pack_service = CapabilityPackService(platform_store, resolved_pack_verifier)
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
                # Bootstrap is an operator-controlled file, but PostgreSQL
                # installs still require supply-chain verification.
                if resolved_pack_verifier is None:
                    raise RuntimeError(
                        "AUTONOESIS_PACK_ALLOWED_SOURCES and AUTONOESIS_PACK_SIGNING_KEYS "
                        "are required to bootstrap a capability pack"
                    )
                await resolved_pack_verifier.verify_install(manifest)
                tenant_id = UUID(tenant_value)
                await platform_store.install_pack(tenant_id, manifest)
            else:
                platform_store.register_pack(manifest)
        yield
        if isinstance(platform_store, PostgreSQLPlatformStore):
            await platform_store.close()
        if breakglass_engine is not None:
            await breakglass_engine.dispose()

    configure_json_logging("autonoesis-api")
    configure_telemetry(
        "autonoesis-api",
        os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"),
    )

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

    async def bind_request_trace(request: Request, call_next: Any) -> Any:
        with platform_tracer("autonoesis.api").start_as_current_span(
            f"{request.method} {request.url.path}",
            attributes={
                "http.request.method": request.method,
                "url.path": request.url.path,
                "autonoesis.tenant.id": request.headers.get("X-Tenant-ID", "unknown"),
                "autonoesis.correlation.id": request.headers.get("X-Correlation-ID", "unknown"),
            },
        ) as span:
            response = await call_next(request)
            span.set_attribute("http.response.status_code", response.status_code)
            response.headers["X-Trace-ID"] = format(span.get_span_context().trace_id, "032x")
            return response

    app.add_middleware(BaseHTTPMiddleware, dispatch=bind_request_trace)
    app.state.store = platform_store
    app.state.kill_switch = (
        SqlKillSwitchStore(platform_store.repository.sessions)
        if isinstance(platform_store, PostgreSQLPlatformStore)
        else platform_kill_switch or InMemoryKillSwitchStore()
    )
    app.state.platform_kill_switch = platform_kill_switch
    app.state.temporary_authorizations = (
        PostgreSQLTemporaryAuthorizationStore(platform_store.repository.sessions)
        if isinstance(platform_store, PostgreSQLPlatformStore)
        else InMemoryTemporaryAuthorizationStore()
    )

    def kill_switch_for(context: IdentityContext) -> Any:
        if isinstance(app.state.kill_switch, SqlKillSwitchStore):
            return app.state.kill_switch.for_tenant(context.tenant_id)
        return app.state.kill_switch

    execution = GoalExecutionApplication(
        platform_store.repository,
        platform_store,
        shadow_write_guard=SqlShadowWriteGuard(platform_store),
        run_deployment_router=CanaryRunRouter(platform_store),
    )
    evolution = CandidateLifecycleService(platform_store, improvement_policy)
    resolved_evaluation_policy = evaluation_policy or configured_evaluation_policy()
    resolved_shadow_dispatcher = shadow_dispatcher
    if (
        resolved_shadow_dispatcher is None
        and os.getenv("AUTONOESIS_TEMPORAL_START", "false").lower() == "true"
    ):
        resolved_shadow_dispatcher = TemporalShadowWorkflowDispatcher(
            os.getenv("AUTONOESIS_TEMPORAL_TARGET", "localhost:7233"),
            tenant_isolated=os.getenv("AUTONOESIS_TENANT_ISOLATED_WORKFLOWS", "true").lower()
            == "true",
            shared_namespace=os.getenv("AUTONOESIS_TEMPORAL_NAMESPACE", "default"),
            shared_task_queue=os.getenv("AUTONOESIS_TEMPORAL_TASK_QUEUE", "autonoesis"),
        )
    resolved_release_dispatcher = release_dispatcher
    if (
        resolved_release_dispatcher is None
        and os.getenv("AUTONOESIS_TEMPORAL_START", "false").lower() == "true"
    ):
        resolved_release_dispatcher = TemporalReleaseCommandDispatcher(
            os.getenv("AUTONOESIS_TEMPORAL_TARGET", "localhost:7233"),
            tenant_isolated=os.getenv("AUTONOESIS_TENANT_ISOLATED_WORKFLOWS", "true").lower()
            == "true",
            shared_namespace=os.getenv("AUTONOESIS_TEMPORAL_NAMESPACE", "default"),
            shared_task_queue=os.getenv("AUTONOESIS_TEMPORAL_TASK_QUEUE", "autonoesis"),
        )

    async def dispatch_release_command(
        *,
        action: str,
        target_id: UUID,
        command: dict[str, object],
        context: IdentityContext,
    ) -> str:
        if resolved_release_dispatcher is None:
            raise HTTPException(503, "Release executor dispatch is not configured")
        return await resolved_release_dispatcher.dispatch(
            tenant_id=context.tenant_id,
            action=action,
            command=command,
            target_id=target_id,
        )

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
        validator = cached_oidc_validator(
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
        if resolved_pack_verifier is None:
            raise HTTPException(503, "Capability pack verification is not configured")
        manifest = parse_manifest(body.manifest)
        try:
            await pack_service.install_pack(context, manifest)
        except PermissionError as exc:
            raise HTTPException(400, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {
            "pack_id": manifest.pack_id,
            "version": manifest.version,
            "artifact_digest": manifest.artifact_digest,
            "status": "enabled",
        }

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

    @app.post("/v1/capability-packs/{pack_id}/versions/{version}/disable", tags=["configuration"])
    async def disable_pack(
        pack_id: str, version: str, body: PackReasonRequest, context: Identity, _: WriteKey
    ) -> dict[str, Any]:
        require_role(context, {"platform_admin", "tenant_admin"})
        try:
            await pack_service.disable_pack(
                context, PackLifecycleCommand(pack_id, version, body.reason)
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except RecordNotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"pack_id": pack_id, "version": version, "status": "disabled"}

    @app.post("/v1/capability-packs/{pack_id}/versions/{version}/enable", tags=["configuration"])
    async def enable_pack(
        pack_id: str, version: str, body: PackReasonRequest, context: Identity, _: WriteKey
    ) -> dict[str, Any]:
        require_role(context, {"platform_admin", "tenant_admin"})
        try:
            await pack_service.enable_pack(
                context, PackLifecycleCommand(pack_id, version, body.reason)
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"pack_id": pack_id, "version": version, "status": "enabled"}

    @app.post("/v1/capability-packs/{pack_id}/versions/{version}/revoke", tags=["configuration"])
    async def revoke_pack(
        pack_id: str, version: str, body: PackReasonRequest, context: Identity, _: WriteKey
    ) -> dict[str, Any]:
        require_role(context, {"platform_admin"})
        try:
            await pack_service.revoke_pack(
                context, PackLifecycleCommand(pack_id, version, body.reason)
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"pack_id": pack_id, "version": version, "status": "revoked"}

    @app.post("/v1/capability-packs/{pack_id}/stable", tags=["configuration"])
    async def set_pack_stable(
        pack_id: str, body: PackStableRequest, context: Identity, _: WriteKey
    ) -> dict[str, Any]:
        require_role(context, {"platform_admin", "tenant_admin"})
        try:
            await pack_service.set_stable_channel(
                context, PackLifecycleCommand(pack_id, body.version, body.reason)
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"pack_id": pack_id, "stable_version": body.version}

    @app.get("/v1/capability-packs/{pack_id}/stable", tags=["configuration"])
    async def get_pack_stable(pack_id: str, context: Identity) -> dict[str, Any]:
        return {
            "pack_id": pack_id,
            "stable_version": await platform_store.get_stable_channel(context.tenant_id, pack_id),
        }

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

    @app.post(
        "/v1/platform/break-glass/authorizations",
        status_code=201,
        tags=["platform-security"],
    )
    async def issue_temporary_authorization(
        body: TemporaryAuthorizationRequest, context: Identity, _: WriteKey
    ) -> dict[str, Any]:
        require_role(context, {"security_admin"})
        if body.principal_id == context.principal_id:
            raise PermissionError("Break-glass authorization must be granted to another principal")
        authorization = TemporaryAuthorization(
            tenant_id=context.tenant_id,
            principal_id=body.principal_id,
            scope="platform.kill_switch",
            reason=body.reason,
            expires_at=datetime.now(UTC) + timedelta(minutes=body.ttl_minutes),
        )
        await app.state.temporary_authorizations.issue(authorization)
        await platform_store.repository.record_audit(
            AuditEvent(
                context.tenant_id,
                context.actor_id,
                context.principal_id,
                "breakglass.authorization.issued",
                "temporary_authorization",
                str(authorization.authorization_id),
                uuid4(),
                {
                    "grantee_principal_id": str(body.principal_id),
                    "scope": authorization.scope,
                    "expires_at": authorization.expires_at.isoformat(),
                    "review_required": True,
                },
            )
        )
        return {
            "authorization_id": str(authorization.authorization_id),
            "scope": authorization.scope,
            "expires_at": authorization.expires_at.isoformat(),
            "review_required": True,
        }

    @app.post(
        "/v1/platform/break-glass/authorizations/{authorization_id}/review",
        tags=["platform-security"],
    )
    async def review_temporary_authorization(
        authorization_id: UUID, context: Identity, _: WriteKey
    ) -> dict[str, Any]:
        require_role(context, {"security_auditor"})
        reviewed = await app.state.temporary_authorizations.review(
            context.tenant_id, authorization_id, context.principal_id
        )
        await platform_store.repository.record_audit(
            AuditEvent(
                context.tenant_id,
                context.actor_id,
                context.principal_id,
                "breakglass.authorization.reviewed",
                "temporary_authorization",
                str(authorization_id),
                uuid4(),
                {"grantee_principal_id": str(reviewed.principal_id)},
            )
        )
        return {
            "authorization_id": str(authorization_id),
            "reviewed_by": str(reviewed.reviewed_by),
            "reviewed_at": reviewed.reviewed_at.isoformat() if reviewed.reviewed_at else None,
        }

    @app.post("/v1/platform/break-glass/kill-switch", status_code=201, tags=["platform-security"])
    async def activate_platform_kill_switch(
        body: BreakGlassKillSwitchRequest,
        context: Identity,
        _: WriteKey,
        ticket: Annotated[str, Header(alias="X-Break-Glass-Ticket")],
        authorization_id: Annotated[UUID, Header(alias="X-Break-Glass-Authorization")],
    ) -> dict[str, Any]:
        require_role(context, {"break_glass"})
        if len(ticket.strip()) < 8 or app.state.platform_kill_switch is None:
            raise PermissionError("a configured break-glass identity and ticket are required")
        await app.state.temporary_authorizations.require_active(
            context.tenant_id,
            authorization_id,
            context.principal_id,
            "platform.kill_switch",
        )
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
        await platform_store.repository.record_audit(
            AuditEvent(
                context.tenant_id,
                context.actor_id,
                context.principal_id,
                "security.alert.breakglass_activated",
                "platform",
                str(record.kill_switch_id),
                correlation_id,
                {"ticket": ticket.strip(), "review_required": True},
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
        authorization_id: Annotated[UUID, Header(alias="X-Break-Glass-Authorization")],
    ) -> dict[str, Any]:
        require_role(context, {"break_glass"})
        if len(ticket.strip()) < 8 or app.state.platform_kill_switch is None:
            raise PermissionError("a configured break-glass identity and ticket are required")
        await app.state.temporary_authorizations.require_active(
            context.tenant_id,
            authorization_id,
            context.principal_id,
            "platform.kill_switch",
        )
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

    @app.get("/v1/runs", tags=["runs"])
    async def list_runs(context: Identity, goal_id: UUID | None = None) -> list[dict[str, Any]]:
        return [
            run_view(item) for item in await platform_store.list_runs(context.tenant_id, goal_id)
        ]

    @app.post("/v1/runs/{run_id}/takeover", status_code=202, tags=["runs"])
    async def take_over_run(
        run_id: UUID,
        body: RunControlRequest,
        request: Request,
        context: Identity,
        _: WriteKey,
    ) -> dict[str, Any]:
        require_role(context, {"platform_admin", "tenant_admin", "operator"})
        run = await execution.take_over_run(
            command_context(request, context, f"takeover:{run_id}", body),
            TakeOverRun(run_id, body.reason),
        )
        return run_view(run)

    @app.post("/v1/runs/{run_id}/cancel", status_code=202, tags=["runs"])
    async def cancel_run(
        run_id: UUID,
        body: RunControlRequest,
        request: Request,
        context: Identity,
        _: WriteKey,
    ) -> dict[str, Any]:
        require_role(context, {"platform_admin", "tenant_admin", "operator"})
        run = await execution.cancel_run(
            command_context(request, context, f"cancel:{run_id}", body),
            CancelRun(run_id, body.reason),
        )
        return run_view(run)

    @app.get("/v1/runs/{run_id}/actions", tags=["runs"])
    async def list_run_actions(run_id: UUID, context: Identity) -> list[dict[str, Any]]:
        await platform_store.get_run(context.tenant_id, run_id)
        actions: list[dict[str, Any]] = []
        for action in await platform_store.list_actions(context.tenant_id, run_id):
            attempts = await platform_store.list_action_attempts(
                context.tenant_id, action.action_id
            )
            actions.append(
                {
                    "action_id": action.action_id,
                    "run_id": action.run_id,
                    "tool_name": action.tool_name,
                    "status": action.status.value,
                    "risk_level": action.risk_level.value,
                    "attempts": [
                        {
                            "attempt_id": attempt.attempt_id,
                            "status": attempt.status.value,
                        }
                        for attempt in attempts
                    ],
                }
            )
        return actions

    @app.post("/v1/actions/{action_id}/reconcile", status_code=202, tags=["actions"])
    async def reconcile_unknown_action(
        action_id: UUID,
        body: ReconcileRequest,
        request: Request,
        context: Identity,
        _: WriteKey,
    ) -> dict[str, Any]:
        require_role(context, {"platform_admin", "tenant_admin", "operator"})
        action = await execution.reconcile_unknown_action(
            command_context(request, context, f"reconcile:{action_id}", body),
            ReconcileUnknownAction(
                action_id=action_id,
                invocation_id=body.invocation_id,
                succeeded=body.succeeded,
                receipt_ref=body.receipt_ref,
                executor_identity=str(context.principal_id),
                failure_reason=body.failure_reason,
            ),
        )
        return {"action_id": action_id, "status": action.status.value}

    @app.get("/v1/slos", tags=["observability"])
    async def service_levels(context: Identity) -> list[dict[str, Any]]:
        """Sample-weighted error budgets computed from persisted audit events."""
        projector = AuditEventSloProjector(platform_store.list_audit_events)
        registry = await projector.project(context.tenant_id)
        budgets = []
        for budget in await registry.all_budgets():
            budgets.append(
                {
                    "sli": budget.sli.value,
                    "total_budget": budget.total_budget,
                    "consumed": budget.consumed,
                    "remaining": budget.remaining,
                    "exhausted": budget.exhausted,
                }
            )
        return budgets

    @app.get("/v1/finops/runs/{run_id}", tags=["observability"])
    async def run_finops(run_id: UUID, context: Identity) -> dict[str, Any]:
        await platform_store.get_run(context.tenant_id, run_id)
        phases = await CostPhaseLedger(platform_store).summarize_run(context.tenant_id, run_id)
        return {
            "run_id": run_id,
            "phases": phases,
            "settled_total": phases["settle"],
            "waste_total": phases["retry_waste"],
        }

    @app.get("/v1/finops/goals/{goal_id}", tags=["observability"])
    async def goal_finops(goal_id: UUID, context: Identity) -> dict[str, Any]:
        ledger = CostPhaseLedger(platform_store)
        totals = {phase: 0 for phase in ("estimate", "reserve", "settle", "retry_waste")}
        runs = await platform_store.list_runs(context.tenant_id, goal_id)
        for run in runs:
            phases = await ledger.summarize_run(context.tenant_id, run.run_id)
            for phase in totals:
                totals[phase] += phases[phase]
        return {"goal_id": goal_id, "phases": totals, "runs_counted": len(runs)}

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
        proposal = await evolution.propose_improvement(
            context,
            ProposeImprovement(
                target=body.target.value,
                target_version_id=body.target_version_id,
                evidence_refs=body.evidence_refs,
                diagnosis=body.diagnosis,
                proposed_change=body.proposed_change,
                validation_suite_id=body.validation_suite_id,
                rollback_plan=body.rollback_plan,
            ),
        )
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
        require_role(context, {"candidate_generator"})
        candidate = await evolution.register_candidate(
            context,
            RegisterCandidate(
                proposal_id=body.proposal_id,
                baseline_version_id=body.baseline_version_id,
                artifact_ref=body.artifact_ref,
                artifact_digest=body.artifact_digest,
                suite_id=body.suite_id,
                suite_version=body.suite_version,
            ),
        )
        return candidate_view(candidate)

    @app.post("/v1/candidates/{candidate_id}/evaluate", tags=["improvement"])
    async def evaluate_candidate(
        candidate_id: UUID, context: Identity, _: WriteKey
    ) -> dict[str, Any]:
        """Gate on persisted Trials; grader-supplied outcomes are not accepted."""
        require_role(context, {"grader"})
        await evolution.submit_for_evaluation(context.tenant_id, candidate_id)
        candidate, record = await evolution.complete_evaluation(
            context, candidate_id, resolved_evaluation_policy
        )
        view = candidate_view(candidate)
        view["evaluation"] = {
            "evaluation_id": record.evaluation_id,
            "decision": record.decision,
            "trial_ids": [str(trial_id) for trial_id in record.trial_ids],
            "assessment": record.assessment,
        }
        return view

    @app.post("/v1/candidates/{candidate_id}/decision", tags=["improvement"])
    async def decide_candidate(
        candidate_id: UUID, body: CandidateDecisionRequest, context: Identity, _: WriteKey
    ) -> dict[str, Any]:
        require_role(context, {"approver"})
        return candidate_view(
            await evolution.decide(context, candidate_id, body.approved, body.reason)
        )

    @app.post("/v1/candidates/{candidate_id}/promote", tags=["improvement"])
    async def promote_candidate(
        candidate_id: UUID, context: Identity, _: WriteKey
    ) -> dict[str, Any]:
        require_role(context, {"release_executor"})
        deployment = await evolution.begin_shadow(context, candidate_id)
        return {
            "deployment_id": deployment.deployment_id,
            "candidate_id": deployment.candidate_id,
            "status": deployment.status,
        }

    @app.post("/v1/deployments/{deployment_id}/canary", status_code=202, tags=["improvement"])
    async def promote_deployment_to_canary(
        deployment_id: UUID, body: CanaryRequest, context: Identity, _: WriteKey
    ) -> dict[str, Any]:
        require_role(context, {"release_executor"})
        deployment = await platform_store.get_deployment(context.tenant_id, deployment_id)
        if deployment.status is not DeploymentStatus.SHADOW:
            raise HTTPException(409, "canary entry requires a shadow deployment")
        workflow_id = await dispatch_release_command(
            action="enter_canary",
            target_id=deployment_id,
            command={
                "deployment_id": str(deployment_id),
                "candidate_percent": body.candidate_percent,
                "salt": body.salt,
            },
            context=context,
        )
        return {
            "deployment_id": deployment_id,
            "workflow_id": workflow_id,
            "status": "dispatched",
        }

    @app.post(
        "/v1/deployments/{deployment_id}/shadow-requests",
        status_code=202,
        tags=["improvement"],
    )
    async def dispatch_shadow_request(
        deployment_id: UUID,
        body: ShadowDispatchRequest,
        context: Identity,
        _: WriteKey,
    ) -> dict[str, Any]:
        require_role(context, {"release_executor", "shadow_dispatcher"})
        deployment = await platform_store.get_deployment(context.tenant_id, deployment_id)
        if deployment.status is not DeploymentStatus.SHADOW:
            raise HTTPException(409, "shadow requests require a Shadow deployment")
        if resolved_shadow_dispatcher is None:
            raise HTTPException(503, "Shadow workflow dispatch is not configured")
        workflow_id = await resolved_shadow_dispatcher.dispatch(
            tenant_id=context.tenant_id,
            deployment_id=deployment_id,
            request_id=body.request_id,
            input_payload=body.input_payload,
        )
        return {
            "deployment_id": deployment_id,
            "request_id": body.request_id,
            "workflow_id": workflow_id,
            "status": "dispatched",
        }

    @app.post("/v1/deployments/{deployment_id}/stable", status_code=202, tags=["improvement"])
    async def promote_deployment_to_stable(
        deployment_id: UUID, body: PromotionRequest, context: Identity, _: WriteKey
    ) -> dict[str, Any]:
        require_role(context, {"release_executor"})
        deployment = await platform_store.get_deployment(context.tenant_id, deployment_id)
        if deployment.status is not DeploymentStatus.CANARY:
            raise HTTPException(409, "stable release requires a canary deployment")
        workflow_id = await dispatch_release_command(
            action="release_stable",
            target_id=deployment_id,
            command={
                "deployment_id": str(deployment_id),
                "stable_version_id": str(body.stable_version_id),
                "min_samples": body.min_samples,
                "observation_seconds": body.observation_seconds,
                "required_metrics": list(body.required_metrics),
            },
            context=context,
        )
        return {
            "deployment_id": deployment_id,
            "workflow_id": workflow_id,
            "status": "dispatched",
        }

    @app.get("/v1/deployments/{deployment_id}/route", tags=["improvement"])
    async def resolve_route(
        deployment_id: UUID, request_id: UUID, context: Identity
    ) -> dict[str, Any]:
        """Replay the persisted allocation rule to explain a request's route."""
        deployment = await platform_store.get_deployment(context.tenant_id, deployment_id)
        if deployment.status is not DeploymentStatus.CANARY or (
            deployment.traffic_allocation is None
        ):
            raise HTTPException(409, "route resolution requires a canary deployment with a rule")
        route, allocation = await evolution.resolve_request_route(
            context, deployment_id, request_id
        )
        return {
            "deployment_id": deployment_id,
            "request_id": request_id,
            "route": route.value,
            "candidate_percent": allocation.candidate_percent,
            "salt": allocation.salt,
        }

    @app.post("/v1/deployments/observations", status_code=201, tags=["improvement"])
    async def record_observation(
        body: ObservationRequest, context: Identity, _: WriteKey
    ) -> dict[str, Any]:
        require_role(context, {"release_executor"})
        observation = await evolution.record_observation(
            context,
            RecordObservation(
                deployment_id=body.deployment_id,
                stage=body.stage,
                metric=body.metric,
                value=body.value,
                operator=body.operator,
                threshold=body.threshold,
            ),
        )
        return {
            "deployment_id": observation.deployment_id,
            "stage": observation.stage,
            "metric": observation.metric,
            "sample_count": observation.sample_count,
            "breach_count": observation.breach_count,
        }

    @app.post("/v1/releases/{release_id}/rollback", status_code=202, tags=["improvement"])
    async def rollback_release(release_id: UUID, context: Identity, _: WriteKey) -> dict[str, Any]:
        require_role(context, {"release_executor"})
        await platform_store.get_active_release(context.tenant_id, release_id)
        workflow_id = await dispatch_release_command(
            action="rollback_release",
            target_id=release_id,
            command={"release_id": str(release_id)},
            context=context,
        )
        return {
            "release_id": release_id,
            "workflow_id": workflow_id,
            "status": "dispatched",
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
        "artifact_digest": candidate.artifact_digest,
        "suite_id": candidate.suite_id,
        "suite_version": candidate.suite_version,
        "generator_id": candidate.generator_id,
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
        "required_reviews": item.required_reviews,
        "completed_reviews": len(item.reviews),
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
        "random_seed": item.random_seed,
        "case_count": len(item.case_results),
        "total_cost_microunits": item.total_cost_microunits,
        "failure_reason": item.failure_reason,
    }


def configured_store() -> PlatformStore:
    database_url = os.getenv("AUTONOESIS_DATABASE_URL")
    store: PlatformStore
    if database_url:
        store = PostgreSQLPlatformStore.from_url(database_url)
    else:
        store = InMemoryPlatformStore()
    return store


def configured_improvement_policy() -> ImprovementTargetPolicy | None:
    """Second prohibition layer: OPA denies forbidden targets independently."""
    opa_url = os.getenv("AUTONOESIS_OPA_URL")
    if not opa_url:
        return None
    return OPAImprovementTargetPolicy(opa_url, "opa-improvement@1")


def configured_evaluation_policy() -> RepeatedTrialPolicy:
    """Governed confidence policy; grader requests cannot weaken it."""
    return RepeatedTrialPolicy(
        pass_threshold=float(os.getenv("AUTONOESIS_EVALUATION_PASS_THRESHOLD", "0.8")),
        confidence_level=float(os.getenv("AUTONOESIS_EVALUATION_CONFIDENCE_LEVEL", "0.95")),
        min_valid_trials=int(os.getenv("AUTONOESIS_EVALUATION_MIN_VALID_TRIALS", "10")),
    )


app = build_app(
    configured_store(),
    improvement_policy=configured_improvement_policy(),
    evaluation_policy=configured_evaluation_policy(),
)
