"""Replaceable provider and infrastructure adapters."""

from autonoesis_adapters.emergency_authorization import (
    InMemoryTemporaryAuthorizationStore,
    PostgreSQLTemporaryAuthorizationStore,
)
from autonoesis_adapters.evaluation_runtime import (
    ExactMatchGraderBackend,
    HarnessCandidateEvaluator,
    InProcessSubjectRuntime,
    PackSubjectRuntime,
    SandboxedPackSubjectRuntime,
    SubjectRuntime,
)
from autonoesis_adapters.evidence_store import (
    Boto3ObjectStore,
    InMemoryObjectStore,
    MinioEvidenceStore,
    ObjectStorePort,
)
from autonoesis_adapters.execution_gateway import (
    EphemeralCredentialBroker,
    InMemoryAtomicExecutionReservations,
    InMemoryDelegationStore,
    InMemoryGatewayAudit,
    JsonSchemaValidator,
    PostgreSQLAtomicExecutionReservations,
    PostgreSQLDelegationStore,
    RegistryControlledEgress,
    StaticToolCatalog,
)
from autonoesis_adapters.governance import (
    DevelopmentPolicy,
    OIDCSettings,
    OIDCValidator,
    OPAImprovementTargetPolicy,
    OPAPolicyAdapter,
    cached_oidc_validator,
)
from autonoesis_adapters.graders import (
    HumanGraderBackend,
    LlmGraderBackend,
    OutcomeGraderBackend,
)
from autonoesis_adapters.kill_switch_store import SqlKillSwitchStore, SqlPlatformKillSwitchStore
from autonoesis_adapters.mcp import MCPServerAdapter, MCPToolDefinition
from autonoesis_adapters.memory import (
    InMemoryBudgetLedger,
    InMemoryIdempotencyStore,
    InMemoryPlatformStore,
)
from autonoesis_adapters.models import (
    AnthropicMessagesAdapter,
    FakeModelAdapter,
    OpenAICompatibleAdapter,
    OpenAIResponsesAdapter,
)
from autonoesis_adapters.observability import (
    AuditEventSloProjector,
    CanaryRunRouter,
    CostPhaseLedger,
)
from autonoesis_adapters.outbox import InboxConsumer, OutboxRelay, OutboxWriter
from autonoesis_adapters.persistence import (
    SqlAlchemyPlatformRepository,
    create_repository,
    metadata,
)
from autonoesis_adapters.platform_store import PostgreSQLPlatformStore
from autonoesis_adapters.readback import HttpAuthoritativeReadback, ReadbackEndpoint
from autonoesis_adapters.shadow_write_guard import SqlShadowWriteGuard
from autonoesis_adapters.supply_chain import (
    StrictSupplyChainVerifier,
    SupplyChainVerificationError,
)

__all__ = [
    "AnthropicMessagesAdapter",
    "AuditEventSloProjector",
    "Boto3ObjectStore",
    "CanaryRunRouter",
    "CostPhaseLedger",
    "DevelopmentPolicy",
    "EphemeralCredentialBroker",
    "ExactMatchGraderBackend",
    "FakeModelAdapter",
    "HarnessCandidateEvaluator",
    "HttpAuthoritativeReadback",
    "HumanGraderBackend",
    "InMemoryAtomicExecutionReservations",
    "InMemoryBudgetLedger",
    "InMemoryDelegationStore",
    "InMemoryGatewayAudit",
    "InMemoryIdempotencyStore",
    "InMemoryObjectStore",
    "InMemoryPlatformStore",
    "InMemoryTemporaryAuthorizationStore",
    "InProcessSubjectRuntime",
    "InboxConsumer",
    "JsonSchemaValidator",
    "LlmGraderBackend",
    "MCPServerAdapter",
    "MCPToolDefinition",
    "MinioEvidenceStore",
    "OIDCSettings",
    "OIDCValidator",
    "OPAImprovementTargetPolicy",
    "OPAPolicyAdapter",
    "ObjectStorePort",
    "OpenAICompatibleAdapter",
    "OpenAIResponsesAdapter",
    "OutboxRelay",
    "OutboxWriter",
    "OutcomeGraderBackend",
    "PackSubjectRuntime",
    "PostgreSQLAtomicExecutionReservations",
    "PostgreSQLDelegationStore",
    "PostgreSQLPlatformStore",
    "PostgreSQLTemporaryAuthorizationStore",
    "ReadbackEndpoint",
    "RegistryControlledEgress",
    "SandboxedPackSubjectRuntime",
    "SqlAlchemyPlatformRepository",
    "SqlKillSwitchStore",
    "SqlPlatformKillSwitchStore",
    "SqlShadowWriteGuard",
    "StaticToolCatalog",
    "StrictSupplyChainVerifier",
    "SubjectRuntime",
    "SupplyChainVerificationError",
    "cached_oidc_validator",
    "create_repository",
    "metadata",
]
