"""Enforce multi-dimensional tenant namespaces and isolation projections."""

import sqlalchemy as sa
from alembic import op

revision = "0006_tenant_isolation"
down_revision = "0005_trusted_evidence_chain"
branch_labels = None
depends_on = None


def _authority_columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("optimistic_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


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
        *_authority_columns(),
        sa.UniqueConstraint("tenant_id", "id", name=f"uq_{name}_tenant_id_id"),
        sa.CheckConstraint("optimistic_version > 0", name=f"ck_{name}_positive_optimistic_version"),
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
    op.execute(
        "UPDATE runs SET temporal_workflow_id = "
        "'tenant-' || replace(tenant_id, '-', '') || '-goal-run-' || id "
        "WHERE temporal_workflow_id IS NULL OR temporal_workflow_id = 'goal-run-' || id"
    )
    op.create_table(
        "platform_kill_switches",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("target", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column("activated_by", sa.String(length=36), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("target = 'platform'", name="ck_platform_kill_switch_target"),
    )
    op.create_index(
        "uq_active_platform_kill_switch",
        "platform_kill_switches",
        ["target"],
        unique=True,
        postgresql_where=sa.text("deactivated_at IS NULL"),
    )
    op.create_table(
        "platform_audit_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("principal_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=200), nullable=False),
        sa.Column("object_id", sa.String(length=200), nullable=False),
        sa.Column("correlation_id", sa.String(length=36), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    _tenant_table(
        "memory_records",
        sa.Column("scope", sa.String(length=300), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_by", sa.String(length=36), nullable=False),
        constraints=(
            sa.CheckConstraint(
                "confidence >= 0 AND confidence <= 1",
                name="ck_memory_records_confidence_range",
            ),
        ),
    )
    _tenant_table(
        "telemetry_records",
        sa.Column("signal_type", sa.String(length=32), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        constraints=(
            sa.CheckConstraint(
                "signal_type IN ('trace', 'log', 'metric')",
                name="ck_telemetry_records_signal_type",
            ),
        ),
    )
    _tenant_table(
        "tenant_resource_namespaces",
        sa.Column("resource_kind", sa.String(length=32), nullable=False),
        sa.Column("logical_name", sa.String(length=200), nullable=False),
        sa.Column("physical_namespace", sa.String(length=500), nullable=False),
        constraints=(
            sa.UniqueConstraint(
                "tenant_id",
                "resource_kind",
                "logical_name",
                name="uq_tenant_resource_logical_name",
            ),
            sa.UniqueConstraint(
                "resource_kind",
                "physical_namespace",
                name="uq_tenant_resource_physical_namespace",
            ),
            sa.CheckConstraint(
                "resource_kind IN ('object', 'cache', 'search', 'vector', 'topic', "
                "'workflow', 'telemetry', 'evaluation_dataset', 'audit_export')",
                name="ck_tenant_resource_namespaces_kind",
            ),
        ),
    )

    # Migrations must fail closed if any table carrying tenant_id was accidentally
    # introduced without both RLS and FORCE RLS.
    op.execute(
        """DO $$
        DECLARE unsafe_table text;
        BEGIN
          SELECT c.relname INTO unsafe_table
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
          JOIN pg_attribute a ON a.attrelid = c.oid
          WHERE n.nspname = 'public'
            AND c.relkind = 'r'
            AND a.attname = 'tenant_id'
            AND a.attnum > 0
            AND NOT a.attisdropped
            AND (NOT c.relrowsecurity OR NOT c.relforcerowsecurity)
          LIMIT 1;
          IF unsafe_table IS NOT NULL THEN
            RAISE EXCEPTION 'tenant table % is missing forced RLS', unsafe_table;
          END IF;
        END $$"""
    )
    op.execute(
        """DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autonoesis_app') THEN
            GRANT SELECT, INSERT, UPDATE ON
                memory_records, telemetry_records, tenant_resource_namespaces
                TO autonoesis_app;
            GRANT SELECT ON platform_kill_switches TO autonoesis_app;
            REVOKE INSERT, UPDATE, DELETE ON
                platform_kill_switches, platform_audit_events FROM autonoesis_app;
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autonoesis_audit') THEN
            GRANT SELECT ON memory_records, telemetry_records, tenant_resource_namespaces
                TO autonoesis_audit;
            REVOKE INSERT, UPDATE, DELETE ON
                platform_kill_switches, platform_audit_events FROM autonoesis_audit;
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autonoesis_relay') THEN
            REVOKE INSERT, UPDATE, DELETE ON
                platform_kill_switches, platform_audit_events FROM autonoesis_relay;
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autonoesis_breakglass') THEN
            GRANT SELECT, INSERT, UPDATE ON platform_kill_switches
                TO autonoesis_breakglass;
            GRANT SELECT, INSERT ON platform_audit_events TO autonoesis_breakglass;
        END IF;
        END $$"""
    )


def downgrade() -> None:
    raise RuntimeError(
        "P1-01 stores tenant security boundaries; restore a pre-upgrade backup instead of "
        "dropping isolation facts"
    )
