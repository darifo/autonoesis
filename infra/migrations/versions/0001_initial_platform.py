"""Create the original Goal-driven platform authority schema.

This revision is intentionally self-contained. Historical migrations must never
import live application metadata because doing so makes old revisions mutable.
"""

from collections.abc import Iterable

import sqlalchemy as sa
from alembic import op

revision = "0001_initial_platform"
down_revision = None
branch_labels = None
depends_on = None


TENANT_TABLES = (
    "capability_packs",
    "agent_versions",
    "skill_versions",
    "tool_versions",
    "goals",
    "runs",
    "plans",
    "tasks",
    "actions",
    "approvals",
    "context_snapshots",
    "evidence",
    "outcomes",
    "budget_ledger",
    "evaluation_trials",
    "improvement_proposals",
    "candidates",
    "releases",
    "audit_events",
    "kill_switches",
    "outbox",
    "inbox",
    "idempotency_records",
)


def _tenant_table(name: str, columns: Iterable[sa.Column[object]]) -> None:
    op.create_table(
        name,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False, index=True),
        *columns,
        sa.Column("optimistic_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _tenant_table(
        "capability_packs",
        (
            sa.Column("pack_id", sa.String(length=200), nullable=False),
            sa.Column("version", sa.String(length=64), nullable=False),
            sa.Column("manifest", sa.JSON(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
        ),
    )
    _tenant_table(
        "agent_versions",
        (
            sa.Column("agent_id", sa.String(length=36), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("stage", sa.String(length=32), nullable=False),
            sa.Column("definition", sa.JSON(), nullable=False),
        ),
    )
    for name, identifier in (("skill_versions", "skill_id"), ("tool_versions", "tool_id")):
        _tenant_table(
            name,
            (
                sa.Column(identifier, sa.String(length=200), nullable=False),
                sa.Column("version", sa.String(length=64), nullable=False),
                sa.Column("definition", sa.JSON(), nullable=False),
            ),
        )
    _tenant_table(
        "goals",
        (
            sa.Column("goal_type", sa.String(length=200), nullable=False),
            sa.Column("owner_id", sa.String(length=36), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("contract", sa.JSON(), nullable=False),
        ),
    )
    _tenant_table(
        "runs",
        (
            sa.Column("goal_id", sa.String(length=36), sa.ForeignKey("goals.id"), nullable=False),
            sa.Column("agent_version_id", sa.String(length=36), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("temporal_workflow_id", sa.String(length=200), nullable=True),
        ),
    )
    _tenant_table(
        "plans",
        (
            sa.Column("run_id", sa.String(length=36), sa.ForeignKey("runs.id"), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("definition", sa.JSON(), nullable=False),
        ),
    )
    _tenant_table(
        "tasks",
        (
            sa.Column("run_id", sa.String(length=36), sa.ForeignKey("runs.id"), nullable=False),
            sa.Column("plan_id", sa.String(length=36), sa.ForeignKey("plans.id"), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("definition", sa.JSON(), nullable=False),
        ),
    )
    _tenant_table(
        "actions",
        (
            sa.Column("run_id", sa.String(length=36), sa.ForeignKey("runs.id"), nullable=False),
            sa.Column("task_id", sa.String(length=36), sa.ForeignKey("tasks.id"), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("idempotency_key", sa.String(length=300), nullable=False),
            sa.Column("definition", sa.JSON(), nullable=False),
        ),
    )
    _tenant_table(
        "approvals",
        (
            sa.Column(
                "action_id", sa.String(length=36), sa.ForeignKey("actions.id"), nullable=False
            ),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("action_digest", sa.String(length=64), nullable=False),
            sa.Column("decision", sa.JSON(), nullable=True),
        ),
    )
    _tenant_table(
        "context_snapshots",
        (
            sa.Column("goal_id", sa.String(length=36), sa.ForeignKey("goals.id"), nullable=False),
            sa.Column("run_id", sa.String(length=36), sa.ForeignKey("runs.id"), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("content_digest", sa.String(length=64), nullable=False),
        ),
    )
    _tenant_table(
        "evidence",
        (
            sa.Column("run_id", sa.String(length=36), sa.ForeignKey("runs.id"), nullable=False),
            sa.Column("source", sa.String(length=300), nullable=False),
            sa.Column("artifact_uri", sa.String(length=1000), nullable=False),
            sa.Column("content_digest", sa.String(length=64), nullable=False),
        ),
    )
    _tenant_table(
        "outcomes",
        (
            sa.Column("goal_id", sa.String(length=36), sa.ForeignKey("goals.id"), nullable=False),
            sa.Column("run_id", sa.String(length=36), sa.ForeignKey("runs.id"), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("result", sa.JSON(), nullable=False),
        ),
    )
    _tenant_table(
        "budget_ledger",
        (
            sa.Column("run_id", sa.String(length=36), sa.ForeignKey("runs.id"), nullable=False),
            sa.Column("category", sa.String(length=64), nullable=False),
            sa.Column("units", sa.BigInteger(), nullable=False),
            sa.Column("reference", sa.String(length=300), nullable=False),
        ),
    )
    _tenant_table(
        "evaluation_trials",
        (
            sa.Column("suite_id", sa.String(length=200), nullable=False),
            sa.Column("subject_version_id", sa.String(length=36), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("result", sa.JSON(), nullable=True),
        ),
    )
    _tenant_table(
        "improvement_proposals",
        (
            sa.Column("target_type", sa.String(length=64), nullable=False),
            sa.Column("target_version_id", sa.String(length=36), nullable=False),
            sa.Column("proposal", sa.JSON(), nullable=False),
        ),
    )
    _tenant_table(
        "candidates",
        (
            sa.Column(
                "proposal_id",
                sa.String(length=36),
                sa.ForeignKey("improvement_proposals.id"),
                nullable=False,
            ),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("artifact_uri", sa.String(length=1000), nullable=False),
        ),
    )
    _tenant_table(
        "releases",
        (
            sa.Column(
                "candidate_id", sa.String(length=36), sa.ForeignKey("candidates.id"), nullable=False
            ),
            sa.Column("stable_version_id", sa.String(length=36), nullable=False),
            sa.Column("previous_stable_version_id", sa.String(length=36), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
        ),
    )
    _tenant_table(
        "audit_events",
        (
            sa.Column("actor_id", sa.String(length=36), nullable=False),
            sa.Column("principal_id", sa.String(length=36), nullable=False),
            sa.Column("event_type", sa.String(length=200), nullable=False),
            sa.Column("object_type", sa.String(length=100), nullable=False),
            sa.Column("object_id", sa.String(length=200), nullable=False),
            sa.Column("correlation_id", sa.String(length=36), nullable=False),
            sa.Column("details", sa.JSON(), nullable=False),
        ),
    )
    _tenant_table(
        "kill_switches",
        (
            sa.Column("dimension", sa.String(length=32), nullable=False),
            sa.Column("target", sa.String(length=300), nullable=False),
            sa.Column("reason", sa.String(length=1000), nullable=False),
            sa.Column("activated_by", sa.String(length=300), nullable=False),
            sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        ),
    )
    _tenant_table(
        "outbox",
        (
            sa.Column("schema", sa.String(length=200), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        ),
    )
    _tenant_table(
        "inbox",
        (
            sa.Column("message_id", sa.String(length=36), nullable=False, unique=True),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        ),
    )
    _tenant_table(
        "idempotency_records",
        (
            sa.Column("idempotency_key", sa.String(length=300), nullable=False),
            sa.Column("request_digest", sa.String(length=64), nullable=False),
            sa.Column("external_id", sa.String(length=300), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("response", sa.JSON(), nullable=True),
        ),
    )
    op.create_unique_constraint(
        "uq_actions_tenant_idempotency_key", "actions", ["tenant_id", "idempotency_key"]
    )
    op.create_unique_constraint(
        "uq_idempotency_records_tenant_key",
        "idempotency_records",
        ["tenant_id", "idempotency_key"],
    )
    for table in TENANT_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_isolation ON "{table}" '
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )


def downgrade() -> None:
    for table in reversed(TENANT_TABLES):
        op.drop_table(table)
    op.drop_table("tenants")
