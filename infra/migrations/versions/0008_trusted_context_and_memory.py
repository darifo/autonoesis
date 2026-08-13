"""Persist trusted context facts, Memory ledger, deletion graph, and projections."""

import sqlalchemy as sa
from alembic import op

revision = "0008_trusted_context"
down_revision = "0007_enterprise_identity"
branch_labels = None
depends_on = None


def _tenant_table(
    name: str, *columns: sa.Column, constraints: tuple[sa.Constraint, ...] = ()
) -> None:
    op.create_table(
        name,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(length=36),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        *columns,
        sa.Column("optimistic_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "id", name=f"uq_{name}_tenant_id_id"),
        sa.CheckConstraint("optimistic_version > 0", name=f"ck_{name}_positive_version"),
        *constraints,
    )
    op.create_index(f"ix_{name}_tenant_id", name, ["tenant_id"])
    op.execute(f'ALTER TABLE "{name}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{name}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'CREATE POLICY tenant_isolation ON "{name}" '
        "USING (tenant_id = current_setting('app.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
    )


def upgrade() -> None:
    op.add_column(
        "memory_records",
        sa.Column("status", sa.String(length=32), nullable=False, server_default="stable"),
    )
    op.add_column(
        "memory_records", sa.Column("definition", sa.JSON(), nullable=False, server_default="{}")
    )
    op.add_column(
        "memory_records", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        "ck_memory_records_status", "memory_records", "status IN ('proposed', 'stable', 'deleted')"
    )
    op.alter_column("memory_records", "status", server_default=None)
    op.alter_column("memory_records", "definition", server_default=None)

    _tenant_table(
        "environment_facts",
        sa.Column("fact_key", sa.String(length=300), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("source", sa.String(length=500), nullable=False),
        sa.Column("source_authority", sa.String(length=500), nullable=False),
        sa.Column("classification", sa.String(length=32), nullable=False),
        sa.Column("freshness_policy", sa.String(length=32), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("acl", sa.JSON(), nullable=False),
        constraints=(
            sa.CheckConstraint(
                "classification IN ('public', 'internal', 'confidential', 'restricted')",
                name="ck_environment_fact_classification",
            ),
            sa.CheckConstraint(
                "freshness_policy IN ('strict', 'warn', 'lax')",
                name="ck_environment_fact_freshness",
            ),
        ),
    )
    _tenant_table(
        "memory_ledger",
        sa.Column("memory_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        constraints=(
            sa.CheckConstraint(
                "kind IN ('write', 'merge', 'delete')", name="ck_memory_ledger_kind"
            ),
        ),
    )
    _tenant_table(
        "memory_deletion_edges",
        sa.Column("parent_memory_id", sa.String(length=36), nullable=False),
        sa.Column("child_memory_id", sa.String(length=36), nullable=False),
        constraints=(
            sa.UniqueConstraint(
                "tenant_id",
                "parent_memory_id",
                "child_memory_id",
                name="uq_memory_deletion_edge",
            ),
        ),
    )
    _tenant_table(
        "vector_index_projections",
        sa.Column("memory_id", sa.String(length=36), nullable=False),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        sa.Column("index_version", sa.String(length=200), nullable=False),
        constraints=(
            sa.UniqueConstraint("tenant_id", "memory_id", name="uq_vector_projection_memory"),
        ),
    )
    op.execute(
        """DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autonoesis_app') THEN
            GRANT SELECT, INSERT, UPDATE ON environment_facts, memory_ledger,
                memory_deletion_edges, vector_index_projections TO autonoesis_app;
            GRANT DELETE ON vector_index_projections TO autonoesis_app;
            REVOKE UPDATE, DELETE ON memory_ledger FROM autonoesis_app;
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autonoesis_audit') THEN
            GRANT SELECT ON environment_facts, memory_ledger, memory_deletion_edges,
                vector_index_projections TO autonoesis_audit;
        END IF;
        END $$"""
    )


def downgrade() -> None:
    raise RuntimeError(
        "P1-03 contains Memory authority and deletion evidence; restore a backup instead of "
        "dropping trusted context records"
    )
