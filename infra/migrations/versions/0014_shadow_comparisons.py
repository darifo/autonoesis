"""Persist immutable Stable/Candidate Shadow comparison evidence."""

import sqlalchemy as sa
from alembic import op

revision = "0014_shadow_comparisons"
down_revision = "0013_deployment_observations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shadow_comparisons",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("deployment_id", sa.String(36), nullable=False),
        sa.Column("request_ref", sa.String(500), nullable=False),
        sa.Column("stable_version_id", sa.String(36), nullable=False),
        sa.Column("candidate_version_id", sa.String(36), nullable=False),
        sa.Column("stable_measurements", sa.JSON, nullable=False),
        sa.Column("candidate_measurements", sa.JSON, nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("optimistic_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id", "deployment_id"],
            ["deployments.tenant_id", "deployments.id"],
            name="fk_shadow_comparisons_deployment",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "deployment_id",
            "request_ref",
            name="uq_shadow_comparisons_request",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_shadow_comparisons_tenant_id_id"),
        sa.CheckConstraint("optimistic_version > 0", name="ck_shadow_comparisons_positive_version"),
    )
    op.create_index("ix_shadow_comparisons_tenant_id", "shadow_comparisons", ["tenant_id"])
    op.execute('ALTER TABLE "shadow_comparisons" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "shadow_comparisons" FORCE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY tenant_isolation ON "shadow_comparisons" '
        "USING (tenant_id = current_setting('app.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
    )


def downgrade() -> None:
    raise RuntimeError("shadow comparison evidence cannot be removed after adoption")
