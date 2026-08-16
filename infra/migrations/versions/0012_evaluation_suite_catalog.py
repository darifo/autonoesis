"""Persist tenant-scoped evaluation suite catalogs."""

import sqlalchemy as sa
from alembic import op

revision = "0012_evaluation_suite_catalog"
down_revision = "0011_evaluation_evidence_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evaluation_suites",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("suite_id", sa.String(200), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("definition", sa.JSON, nullable=False),
        sa.Column("optimistic_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "tenant_id", "suite_id", "version", name="uq_evaluation_suites_version"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_evaluation_suites_tenant_id_id"),
        sa.CheckConstraint("optimistic_version > 0", name="ck_evaluation_suites_positive_version"),
    )
    op.create_index("ix_evaluation_suites_tenant_id", "evaluation_suites", ["tenant_id"])
    op.execute('ALTER TABLE "evaluation_suites" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "evaluation_suites" FORCE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY tenant_isolation ON "evaluation_suites" '
        "USING (tenant_id = current_setting('app.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
    )


def downgrade() -> None:
    # Suites are the fixed grading references Candidates pin to; removing the
    # catalog would orphan those references, so this migration is one-way.
    raise RuntimeError("evaluation suite catalog cannot be removed after adoption")
