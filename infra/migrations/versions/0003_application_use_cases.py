"""Persist Application context and Action execution attempts."""

import sqlalchemy as sa
from alembic import op

revision = "0003_application_use_cases"
down_revision = "0002_authoritative_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS ("
        "SELECT tenant_id, run_id FROM context_snapshots "
        "GROUP BY tenant_id, run_id HAVING count(*) > 1"
        ") THEN RAISE EXCEPTION "
        "'a Run has multiple Context Snapshots; reconcile before P0-04'; "
        "END IF; END $$"
    )
    op.create_unique_constraint(
        "uq_context_snapshot_run", "context_snapshots", ["tenant_id", "run_id"]
    )
    op.create_table(
        "action_attempts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(length=36),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("action_id", sa.String(length=36), nullable=False),
        sa.Column("invocation_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=300), nullable=False),
        sa.Column("receipt_ref", sa.String(length=1000), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("optimistic_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "id", name="uq_action_attempts_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "invocation_id",
            "status",
            name="uq_action_attempt_invocation_status",
        ),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_action_attempt_idempotency"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["runs.tenant_id", "runs.id"],
            name="fk_action_attempts_tenant_run_id_runs",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "action_id"],
            ["actions.tenant_id", "actions.id"],
            name="fk_action_attempts_tenant_action_id_actions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id", "action_id"],
            ["actions.tenant_id", "actions.run_id", "actions.id"],
            name="fk_action_attempts_action_run",
        ),
        sa.CheckConstraint(
            "status IN ('started', 'succeeded', 'failed', 'unknown')",
            name="ck_action_attempts_legal_status",
        ),
        sa.CheckConstraint(
            "optimistic_version > 0",
            name="ck_action_attempts_positive_optimistic_version",
        ),
    )
    op.create_index("ix_action_attempts_tenant_id", "action_attempts", ["tenant_id"])
    op.execute('ALTER TABLE "action_attempts" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "action_attempts" FORCE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY tenant_isolation ON "action_attempts" '
        "USING (tenant_id = current_setting('app.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
    )
    op.execute(
        """DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autonoesis_app') THEN
            GRANT SELECT, INSERT, UPDATE ON action_attempts TO autonoesis_app;
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autonoesis_audit') THEN
            GRANT SELECT ON action_attempts TO autonoesis_audit;
        END IF;
        END $$"""
    )


def downgrade() -> None:
    raise RuntimeError(
        "P0-04 records durable execution attempts; restore the pre-upgrade backup "
        "instead of deleting those facts in place"
    )
