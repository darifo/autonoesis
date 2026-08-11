"""Replaceable provider and infrastructure adapters."""

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
    RegistryControlledEgress,
    StaticToolCatalog,
)
from autonoesis_adapters.governance import (
    DevelopmentPolicy,
    OIDCSettings,
    OIDCValidator,
    OPAPolicyAdapter,
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
from autonoesis_adapters.outbox import InboxConsumer, OutboxRelay, OutboxWriter
from autonoesis_adapters.persistence import (
    SqlAlchemyPlatformRepository,
    create_repository,
    metadata,
)
from autonoesis_adapters.platform_store import PostgreSQLPlatformStore
from autonoesis_adapters.readback import HttpAuthoritativeReadback, ReadbackEndpoint

__all__ = [
    "AnthropicMessagesAdapter",
    "Boto3ObjectStore",
    "DevelopmentPolicy",
    "EphemeralCredentialBroker",
    "FakeModelAdapter",
    "HttpAuthoritativeReadback",
    "InMemoryAtomicExecutionReservations",
    "InMemoryBudgetLedger",
    "InMemoryDelegationStore",
    "InMemoryGatewayAudit",
    "InMemoryIdempotencyStore",
    "InMemoryObjectStore",
    "InMemoryPlatformStore",
    "InboxConsumer",
    "JsonSchemaValidator",
    "MCPServerAdapter",
    "MCPToolDefinition",
    "MinioEvidenceStore",
    "OIDCSettings",
    "OIDCValidator",
    "OPAPolicyAdapter",
    "ObjectStorePort",
    "OpenAICompatibleAdapter",
    "OpenAIResponsesAdapter",
    "OutboxRelay",
    "OutboxWriter",
    "PostgreSQLAtomicExecutionReservations",
    "PostgreSQLPlatformStore",
    "ReadbackEndpoint",
    "RegistryControlledEgress",
    "SqlAlchemyPlatformRepository",
    "SqlKillSwitchStore",
    "SqlPlatformKillSwitchStore",
    "StaticToolCatalog",
    "create_repository",
    "metadata",
]
