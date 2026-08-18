"""Persist per-deployment guardrail observations."""

import sqlalchemy as sa
from alembic import op

revision = "0013_deployment_observations"
down_revision = "0012_evaluation_suite_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deployment_observations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("deployment_id", sa.String(36), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("metric", sa.String(300), nullable=False),
        sa.Column("sample_count", sa.Integer, nullable=False),
        sa.Column("breach_count", sa.Integer, nullable=False),
        sa.Column("last_value", sa.Float, nullable=True),
        sa.Column("first_sample_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sample_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("optimistic_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id", "deployment_id"],
            ["deployments.tenant_id", "deployments.id"],
            name="fk_deployment_observations_deployment",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "deployment_id",
            "stage",
            "metric",
            name="uq_deployment_observations_scope",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_deployment_observations_tenant_id_id"),
        sa.CheckConstraint(
            "optimistic_version > 0", name="ck_deployment_observations_positive_version"
        ),
        sa.CheckConstraint(
            "stage in ('shadow', 'canary', 'stable', 'failed', 'rolled_back')",
            name="ck_deployment_observations_stage",
        ),
    )
    op.create_index(
        "ix_deployment_observations_tenant_id", "deployment_observations", ["tenant_id"]
    )
    op.execute('ALTER TABLE "deployment_observations" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "deployment_observations" FORCE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY tenant_isolation ON "deployment_observations" '
        "USING (tenant_id = current_setting('app.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
    )


def downgrade() -> None:
    # Guardrail observations are the evidence behind promotion and rollback
    # decisions; dropping them would orphan those decisions, so this is one-way.
    raise RuntimeError("deployment observations cannot be removed after adoption")
