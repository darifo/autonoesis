"""Capability Pack supply-chain evidence and tenant stable channels."""

import sqlalchemy as sa
from alembic import op

revision = "0015_pack_supply_chain"
down_revision = "0014_shadow_comparisons"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("capability_packs", sa.Column("artifact_digest", sa.String(64), nullable=True))
    op.add_column("capability_packs", sa.Column("signature", sa.Text(), nullable=True))
    op.add_column("capability_packs", sa.Column("sbom_ref", sa.String(500), nullable=True))
    op.add_column("capability_packs", sa.Column("sbom_digest", sa.String(64), nullable=True))
    op.add_column(
        "capability_packs",
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("capability_packs", sa.Column("revoked_reason", sa.String(1000), nullable=True))
    op.create_table(
        "capability_pack_channels",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("pack_id", sa.String(200), nullable=False),
        sa.Column("stable_version", sa.String(64), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=False),
        sa.Column("optimistic_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "pack_id", name="uq_capability_pack_channel"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_capability_pack_channel_tenant_id_id"),
    )
    op.create_index(
        "ix_capability_pack_channels_tenant_id", "capability_pack_channels", ["tenant_id"]
    )
    op.execute('ALTER TABLE "capability_pack_channels" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "capability_pack_channels" FORCE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY tenant_isolation ON "capability_pack_channels" '
        "USING (tenant_id = current_setting('app.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
    )


def downgrade() -> None:
    raise RuntimeError("pack supply-chain evidence and channels cannot be removed after adoption")
