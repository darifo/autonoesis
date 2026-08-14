"""Frozen SQLAlchemy schema for PostgreSQL authoritative state."""

from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)

metadata = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)


def tenant_table(name: str, *items: Any) -> Table:
    """Create a tenant-authoritative table with a composite reference target."""

    return Table(
        name,
        metadata,
        Column("id", String(36), primary_key=True),
        Column(
            "tenant_id",
            String(36),
            ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        *items,
        Column("optimistic_version", Integer, nullable=False, default=1),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=True),
        UniqueConstraint("tenant_id", "id", name=f"uq_{name}_tenant_id_id"),
        CheckConstraint("optimistic_version > 0", name="positive_optimistic_version"),
    )


def tenant_reference(
    local_column: str,
    target_table: str,
    *,
    ondelete: str = "RESTRICT",
) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["tenant_id", local_column],
        [f"{target_table}.tenant_id", f"{target_table}.id"],
        ondelete=ondelete,
    )


def status_check(*values: str) -> CheckConstraint:
    allowed = ", ".join(f"'{value}'" for value in values)
    return CheckConstraint(f"status IN ({allowed})", name="legal_status")


def stage_check(*values: str) -> CheckConstraint:
    allowed = ", ".join(f"'{value}'" for value in values)
    return CheckConstraint(f"stage IN ({allowed})", name="legal_stage")


tenants = Table(
    "tenants",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("name", String(200), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
platform_kill_switches = Table(
    "platform_kill_switches",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("target", String(32), nullable=False),
    Column("reason", String(1000), nullable=False),
    Column("activated_by", String(36), nullable=False),
    Column("deactivated_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("target = 'platform'", name="target"),
)
Index(
    "uq_active_platform_kill_switch",
    platform_kill_switches.c.target,
    unique=True,
    postgresql_where=text("deactivated_at IS NULL"),
    sqlite_where=text("deactivated_at IS NULL"),
)
platform_audit_events = Table(
    "platform_audit_events",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("actor_id", String(36), nullable=False),
    Column("principal_id", String(36), nullable=False),
    Column("event_type", String(200), nullable=False),
    Column("object_id", String(200), nullable=False),
    Column("correlation_id", String(36), nullable=False),
    Column("reason", String(1000), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
breakglass_alerts = Table(
    "breakglass_alerts",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("authorization_id", String(36), nullable=False),
    Column("principal_id", String(36), nullable=False),
    Column("ticket", String(300), nullable=False),
    Column("event_type", String(200), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("acknowledged_by", String(36), nullable=True),
    Column("acknowledged_at", DateTime(timezone=True), nullable=True),
)

capability_packs = tenant_table(
    "capability_packs",
    Column("pack_id", String(200), nullable=False),
    Column("version", String(64), nullable=False),
    Column("manifest", JSON, nullable=False),
    Column("enabled", Boolean, nullable=False, default=True),
    UniqueConstraint("tenant_id", "pack_id", "version", name="uq_capability_pack_version"),
)
agent_versions = tenant_table(
    "agent_versions",
    Column("agent_id", String(36), nullable=False),
    Column("name", String(120), nullable=False),
    Column("version", Integer, nullable=False),
    Column("stage", String(32), nullable=False),
    Column("definition", JSON, nullable=False),
    UniqueConstraint("tenant_id", "agent_id", "version", name="uq_agent_asset_version"),
    UniqueConstraint("tenant_id", "name", "version", name="uq_agent_name_version"),
    stage_check("candidate", "stable", "retired"),
)
skill_versions = tenant_table(
    "skill_versions",
    Column("skill_id", String(200), nullable=False),
    Column("version", String(64), nullable=False),
    Column("definition", JSON, nullable=False),
    UniqueConstraint("tenant_id", "skill_id", "version", name="uq_skill_asset_version"),
)
tool_versions = tenant_table(
    "tool_versions",
    Column("tool_id", String(200), nullable=False),
    Column("version", String(64), nullable=False),
    Column("definition", JSON, nullable=False),
    UniqueConstraint("tenant_id", "tool_id", "version", name="uq_tool_asset_version"),
)
policy_versions = tenant_table(
    "policy_versions",
    Column("policy_id", String(200), nullable=False),
    Column("version", String(64), nullable=False),
    Column("definition", JSON, nullable=False),
    UniqueConstraint("tenant_id", "policy_id", "version", name="uq_policy_asset_version"),
)
budgets = tenant_table(
    "budgets",
    Column("budget_id", String(200), nullable=False),
    Column("version", String(64), nullable=False),
    Column("definition", JSON, nullable=False),
    UniqueConstraint("tenant_id", "budget_id", "version", name="uq_budget_asset_version"),
)

goals = tenant_table(
    "goals",
    Column("goal_type", String(200), nullable=False),
    Column("owner_id", String(36), nullable=False),
    Column("status", String(32), nullable=False),
    Column("contract", JSON, nullable=False),
    status_check("draft", "active", "paused", "satisfied", "failed", "cancelled"),
)
runs = tenant_table(
    "runs",
    Column("goal_id", String(36), nullable=False),
    Column("agent_version_id", String(36), nullable=False),
    Column("status", String(32), nullable=False),
    Column("temporal_workflow_id", String(200), nullable=True),
    Column("definition", JSON, nullable=False),
    tenant_reference("goal_id", "goals"),
    UniqueConstraint("tenant_id", "temporal_workflow_id", name="uq_run_workflow_id"),
    status_check(
        "pending",
        "running",
        "blocked",
        "awaiting_evidence",
        "succeeded",
        "failed",
        "cancelled",
    ),
)
plans = tenant_table(
    "plans",
    Column("goal_id", String(36), nullable=False),
    Column("run_id", String(36), nullable=False),
    Column("version", Integer, nullable=False),
    Column("definition", JSON, nullable=False),
    tenant_reference("goal_id", "goals"),
    tenant_reference("run_id", "runs"),
    UniqueConstraint("tenant_id", "run_id", "version", name="uq_plan_run_version"),
)
tasks = tenant_table(
    "tasks",
    Column("run_id", String(36), nullable=False),
    Column("plan_id", String(36), nullable=False),
    Column("status", String(32), nullable=False),
    Column("definition", JSON, nullable=False),
    tenant_reference("run_id", "runs"),
    tenant_reference("plan_id", "plans", ondelete="CASCADE"),
    status_check("pending", "ready", "running", "blocked", "succeeded", "failed"),
)
actions = tenant_table(
    "actions",
    Column("run_id", String(36), nullable=False),
    Column("task_id", String(36), nullable=False),
    Column("status", String(32), nullable=False),
    Column("idempotency_key", String(300), nullable=False),
    Column("action_digest", String(64), nullable=False),
    Column("definition", JSON, nullable=False),
    tenant_reference("run_id", "runs"),
    tenant_reference("task_id", "tasks"),
    UniqueConstraint("tenant_id", "idempotency_key", name="uq_action_idempotency_key"),
    UniqueConstraint("tenant_id", "run_id", "id", name="uq_action_run_id"),
    status_check(
        "proposed",
        "awaiting_approval",
        "authorized",
        "executing",
        "succeeded",
        "failed",
        "denied",
        "unknown",
    ),
)
action_attempts = tenant_table(
    "action_attempts",
    Column("run_id", String(36), nullable=False),
    Column("action_id", String(36), nullable=False),
    Column("invocation_id", String(36), nullable=False),
    Column("status", String(32), nullable=False),
    Column("idempotency_key", String(300), nullable=False),
    Column("receipt_ref", String(1000), nullable=False),
    Column("definition", JSON, nullable=False),
    tenant_reference("run_id", "runs"),
    tenant_reference("action_id", "actions"),
    ForeignKeyConstraint(
        ["tenant_id", "run_id", "action_id"],
        ["actions.tenant_id", "actions.run_id", "actions.id"],
        name="fk_action_attempts_action_run",
    ),
    UniqueConstraint(
        "tenant_id",
        "invocation_id",
        "status",
        name="uq_action_attempt_invocation_status",
    ),
    UniqueConstraint("tenant_id", "idempotency_key", name="uq_action_attempt_idempotency"),
    status_check("started", "succeeded", "failed", "unknown"),
)
approvals = tenant_table(
    "approvals",
    Column("run_id", String(36), nullable=False),
    Column("action_id", String(36), nullable=False),
    Column("status", String(32), nullable=False),
    Column("action_digest", String(64), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("definition", JSON, nullable=False),
    tenant_reference("run_id", "runs"),
    tenant_reference("action_id", "actions"),
    ForeignKeyConstraint(
        ["tenant_id", "run_id", "action_id"],
        ["actions.tenant_id", "actions.run_id", "actions.id"],
        name="fk_approvals_action_run",
    ),
    status_check("pending", "approved", "rejected", "expired"),
)
context_snapshots = tenant_table(
    "context_snapshots",
    Column("goal_id", String(36), nullable=False),
    Column("run_id", String(36), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("content_digest", String(64), nullable=False),
    tenant_reference("goal_id", "goals"),
    tenant_reference("run_id", "runs"),
    UniqueConstraint("tenant_id", "run_id", name="uq_context_snapshot_run"),
)
evidence = tenant_table(
    "evidence",
    Column("run_id", String(36), nullable=False),
    Column("action_id", String(36), nullable=False),
    Column("source", String(300), nullable=False),
    Column("source_identity", String(300), nullable=False),
    Column("capture_method", String(64), nullable=False),
    Column("artifact_uri", String(1000), nullable=False),
    Column("content_digest", String(64), nullable=False),
    Column("classification", String(32), nullable=False),
    Column("valid_from", DateTime(timezone=True), nullable=False),
    Column("valid_until", DateTime(timezone=True), nullable=False),
    Column("integrity", String(32), nullable=False),
    Column("definition", JSON, nullable=False),
    tenant_reference("run_id", "runs"),
    tenant_reference("action_id", "actions"),
    ForeignKeyConstraint(
        ["tenant_id", "run_id", "action_id"],
        ["actions.tenant_id", "actions.run_id", "actions.id"],
        name="fk_evidence_action_run",
    ),
    CheckConstraint("length(content_digest) = 64", name="content_digest_length"),
    CheckConstraint("valid_until >= valid_from", name="validity_interval"),
)
evidence_capture_sagas = tenant_table(
    "evidence_capture_sagas",
    Column("evidence_id", String(36), nullable=False),
    Column("run_id", String(36), nullable=False),
    Column("action_id", String(36), nullable=False),
    Column("criterion_id", String(200), nullable=False),
    Column("source", String(300), nullable=False),
    Column("artifact_uri", String(1000), nullable=False),
    Column("expected_digest", String(64), nullable=False),
    Column("status", String(32), nullable=False),
    Column("definition", JSON, nullable=False),
    Column("failure_reason", String(1000), nullable=True),
    tenant_reference("run_id", "runs"),
    tenant_reference("action_id", "actions"),
    UniqueConstraint("tenant_id", "evidence_id", name="uq_evidence_capture_saga_evidence"),
    CheckConstraint("length(expected_digest) = 64", name="expected_digest_length"),
    status_check("pending", "committed", "failed"),
)
evidence_deletions = tenant_table(
    "evidence_deletions",
    Column("evidence_id", String(36), nullable=False),
    Column("artifact_uri", String(1000), nullable=False),
    Column("requested_by", String(36), nullable=False),
    Column("reason", String(1000), nullable=False),
    Column("requested_at", DateTime(timezone=True), nullable=False),
    Column("status", String(32), nullable=False),
    Column("deleted_at", DateTime(timezone=True), nullable=True),
    Column("provider_version_id", String(300), nullable=True),
    Column("proof_digest", String(64), nullable=True),
    Column("failure_reason", String(1000), nullable=True),
    tenant_reference("evidence_id", "evidence"),
    UniqueConstraint("tenant_id", "evidence_id", name="uq_evidence_deletion_evidence"),
    CheckConstraint(
        "proof_digest IS NULL OR length(proof_digest) = 64", name="proof_digest_length"
    ),
    status_check("requested", "retention_blocked", "deleted", "failed"),
)
outcomes = tenant_table(
    "outcomes",
    Column("goal_id", String(36), nullable=False),
    Column("run_id", String(36), nullable=False),
    Column("criterion_id", String(200), nullable=False),
    Column("verifier_version", String(200), nullable=False),
    Column("status", String(32), nullable=False),
    Column("result", JSON, nullable=False),
    tenant_reference("goal_id", "goals"),
    tenant_reference("run_id", "runs"),
    UniqueConstraint("tenant_id", "run_id", "criterion_id", name="uq_outcome_criterion"),
    status_check("verified", "not_met", "unknown"),
)
budget_ledger = tenant_table(
    "budget_ledger",
    Column("run_id", String(36), nullable=False),
    Column("category", String(64), nullable=False),
    Column("amount", BigInteger, nullable=False),
    Column("unit", String(32), nullable=False),
    Column("reference", String(300), nullable=False),
    tenant_reference("run_id", "runs"),
    UniqueConstraint("tenant_id", "run_id", "reference", name="uq_budget_entry_reference"),
    CheckConstraint("amount > 0", name="positive_amount"),
)

evaluation_trials = tenant_table(
    "evaluation_trials",
    Column("suite_id", String(200), nullable=False),
    Column("suite_version", String(64), nullable=False),
    Column("subject_version_id", String(36), nullable=False),
    Column("harness_version", String(200), nullable=False),
    Column("status", String(32), nullable=False),
    Column("result", JSON, nullable=False),
    status_check("pending", "running", "passed", "failed", "invalid"),
)
environment_facts = tenant_table(
    "environment_facts",
    Column("fact_key", String(300), nullable=False),
    Column("subject", String(500), nullable=False),
    Column("source", String(500), nullable=False),
    Column("source_authority", String(500), nullable=False),
    Column("classification", String(32), nullable=False),
    Column("freshness_policy", String(32), nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("valid_until", DateTime(timezone=True), nullable=False),
    Column("value", JSON, nullable=False),
    Column("acl", JSON, nullable=False),
)
memory_records = tenant_table(
    "memory_records",
    Column("scope", String(300), nullable=False),
    Column("content", Text, nullable=False),
    Column("provenance", JSON, nullable=False),
    Column("confidence", Float, nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("approved_by", String(36), nullable=False),
    Column("status", String(32), nullable=False),
    Column("definition", JSON, nullable=False),
    Column("deleted_at", DateTime(timezone=True), nullable=True),
    CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
    status_check("proposed", "stable", "deleted"),
)
memory_ledger = tenant_table(
    "memory_ledger",
    Column("memory_id", String(36), nullable=False),
    Column("kind", String(32), nullable=False),
    Column("actor_id", String(36), nullable=False),
    Column("metadata", JSON, nullable=False),
    CheckConstraint("kind IN ('write', 'merge', 'delete')", name="memory_ledger_kind"),
)
memory_deletion_edges = tenant_table(
    "memory_deletion_edges",
    Column("parent_memory_id", String(36), nullable=False),
    Column("child_memory_id", String(36), nullable=False),
    UniqueConstraint(
        "tenant_id", "parent_memory_id", "child_memory_id", name="uq_memory_deletion_edge"
    ),
)
vector_index_projections = tenant_table(
    "vector_index_projections",
    Column("memory_id", String(36), nullable=False),
    Column("content_digest", String(64), nullable=False),
    Column("index_version", String(200), nullable=False),
    UniqueConstraint("tenant_id", "memory_id", name="uq_vector_projection_memory"),
)
telemetry_records = tenant_table(
    "telemetry_records",
    Column("signal_type", String(32), nullable=False),
    Column("trace_id", String(64), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("signal_type IN ('trace', 'log', 'metric')", name="signal_type"),
)
tenant_resource_namespaces = tenant_table(
    "tenant_resource_namespaces",
    Column("resource_kind", String(32), nullable=False),
    Column("logical_name", String(200), nullable=False),
    Column("physical_namespace", String(500), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "resource_kind",
        "logical_name",
        name="uq_tenant_resource_logical_name",
    ),
    UniqueConstraint(
        "resource_kind",
        "physical_namespace",
        name="uq_tenant_resource_physical_namespace",
    ),
    CheckConstraint(
        "resource_kind IN ('object', 'cache', 'search', 'vector', 'topic', 'workflow', "
        "'telemetry', 'evaluation_dataset', 'audit_export')",
        name="resource_kind",
    ),
)
improvement_proposals = tenant_table(
    "improvement_proposals",
    Column("target_type", String(64), nullable=False),
    Column("target_version_id", String(36), nullable=False),
    Column("proposal", JSON, nullable=False),
)
candidates = tenant_table(
    "candidates",
    Column("proposal_id", String(36), nullable=False),
    Column("baseline_version_id", String(36), nullable=False),
    Column("status", String(32), nullable=False),
    Column("artifact_uri", String(1000), nullable=False),
    Column("generator_id", String(300), nullable=False),
    Column("definition", JSON, nullable=False),
    tenant_reference("proposal_id", "improvement_proposals"),
    UniqueConstraint("tenant_id", "proposal_id", "artifact_uri", name="uq_candidate_artifact"),
    status_check("draft", "evaluating", "awaiting_approval", "approved", "rejected"),
)
deployments = tenant_table(
    "deployments",
    Column("candidate_id", String(36), nullable=False),
    Column("status", String(32), nullable=False),
    Column("definition", JSON, nullable=False),
    tenant_reference("candidate_id", "candidates"),
    status_check("shadow", "canary", "stable", "failed", "rolled_back"),
)
releases = tenant_table(
    "releases",
    Column("candidate_id", String(36), nullable=False),
    Column("deployment_id", String(36), nullable=False),
    Column("stable_slot", String(200), nullable=False),
    Column("stable_version_id", String(36), nullable=False),
    Column("previous_stable_version_id", String(36), nullable=False),
    Column("approved_by", String(36), nullable=False),
    Column("active", Boolean, nullable=False, default=True),
    Column("definition", JSON, nullable=False),
    tenant_reference("candidate_id", "candidates"),
    tenant_reference("deployment_id", "deployments"),
)
Index(
    "uq_releases_active_stable_slot",
    releases.c.tenant_id,
    releases.c.stable_slot,
    unique=True,
    postgresql_where=text("active"),
    sqlite_where=text("active = 1"),
)

audit_events = tenant_table(
    "audit_events",
    Column("actor_id", String(36), nullable=False),
    Column("principal_id", String(36), nullable=False),
    Column("event_type", String(200), nullable=False),
    Column("object_type", String(100), nullable=False),
    Column("object_id", String(200), nullable=False),
    Column("correlation_id", String(36), nullable=False),
    Column("details", JSON, nullable=False),
    Column("sequence", BigInteger, nullable=True),
    Column("previous_digest", String(64), nullable=True),
    Column("event_digest", String(64), nullable=True),
    UniqueConstraint("tenant_id", "sequence", name="uq_audit_event_tenant_sequence"),
    UniqueConstraint("tenant_id", "event_digest", name="uq_audit_event_tenant_digest"),
)
kill_switches = tenant_table(
    "kill_switches",
    Column("dimension", String(32), nullable=False),
    Column("target", String(300), nullable=False),
    Column("reason", String(1000), nullable=False),
    Column("activated_by", String(300), nullable=False),
    Column("deactivated_at", DateTime(timezone=True), nullable=True),
)
outbox = tenant_table(
    "outbox",
    Column("schema", String(200), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=True),
)
inbox = tenant_table(
    "inbox",
    Column("message_id", String(36), nullable=False),
    Column("processed_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("tenant_id", "message_id", name="uq_inbox_message"),
)
idempotency_records = tenant_table(
    "idempotency_records",
    Column("run_id", String(36), nullable=True),
    Column("action_id", String(36), nullable=True),
    Column("tool_name", String(200), nullable=True),
    Column("tool_version", String(64), nullable=True),
    Column("idempotency_key", String(300), nullable=False),
    Column("request_digest", String(64), nullable=False),
    Column("cost_units", BigInteger, nullable=True),
    Column("external_id", String(300), nullable=True),
    Column("status", String(32), nullable=False),
    Column("response", JSON, nullable=True),
    UniqueConstraint("tenant_id", "idempotency_key", name="uq_idempotency_tenant_key"),
    status_check("pending", "accepted", "completed", "failed", "unknown"),
)

AUTHORITATIVE_TABLES = (
    goals,
    runs,
    plans,
    tasks,
    actions,
    action_attempts,
    approvals,
    context_snapshots,
    environment_facts,
    evidence,
    evidence_capture_sagas,
    evidence_deletions,
    outcomes,
    memory_records,
    memory_ledger,
    memory_deletion_edges,
    budget_ledger,
    audit_events,
    candidates,
    evaluation_trials,
    deployments,
    releases,
)
