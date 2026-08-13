"""Add authoritative enterprise identities, delegation, and emergency reviews."""

import sqlalchemy as sa
from alembic import op

revision = "0007_enterprise_identity"
down_revision = "0006_tenant_isolation"
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
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name=f"uq_{name}_tenant_id_id"),
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
    _tenant_table(
        "enterprise_identities",
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("principal_id", sa.String(length=36), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("service_id", sa.String(length=300), nullable=True),
        sa.Column("agent_id", sa.String(length=300), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        constraints=(
            sa.UniqueConstraint("tenant_id", "subject", name="uq_identity_tenant_subject"),
            sa.CheckConstraint("kind IN ('human', 'service', 'agent')", name="ck_identity_kind"),
        ),
    )
    _tenant_table(
        "delegations",
        sa.Column("grantor_principal_id", sa.String(length=36), nullable=False),
        sa.Column("delegate_principal_id", sa.String(length=36), nullable=False),
        sa.Column("tool_name", sa.String(length=300), nullable=False),
        sa.Column("resource_prefix", sa.String(length=1000), nullable=False),
        sa.Column("purpose", sa.String(length=500), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        constraints=(
            sa.CheckConstraint(
                "grantor_principal_id <> delegate_principal_id",
                name="ck_delegation_no_self_delegation",
            ),
            sa.CheckConstraint("expires_at > created_at", name="ck_delegation_future_expiry"),
        ),
    )
    _tenant_table(
        "temporary_authorizations",
        sa.Column("principal_id", sa.String(length=36), nullable=False),
        sa.Column("scope", sa.String(length=500), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_by", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        constraints=(
            sa.CheckConstraint("expires_at > created_at", name="ck_temporary_auth_future_expiry"),
            sa.CheckConstraint(
                "reviewed_by IS NULL OR reviewed_by <> principal_id",
                name="ck_temporary_auth_independent_review",
            ),
        ),
    )
    op.create_table(
        "breakglass_alerts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("authorization_id", sa.String(length=36), nullable=False),
        sa.Column("principal_id", sa.String(length=36), nullable=False),
        sa.Column("ticket", sa.String(length=300), nullable=False),
        sa.Column("event_type", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_by", sa.String(length=36), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autonoesis_app') THEN
            GRANT SELECT, INSERT, UPDATE ON enterprise_identities, delegations,
                temporary_authorizations TO autonoesis_app;
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autonoesis_breakglass') THEN
            GRANT SELECT, INSERT, UPDATE ON temporary_authorizations TO autonoesis_breakglass;
            GRANT SELECT, INSERT, UPDATE ON breakglass_alerts TO autonoesis_breakglass;
        END IF;
        END $$"""
    )


def downgrade() -> None:
    raise RuntimeError(
        "P1-02 stores security authority and review evidence; restore a backup instead of "
        "dropping identity records"
    )
