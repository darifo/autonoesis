"""Add recoverable Evidence artifacts, deletion proofs, and append-only audit digests."""

import sqlalchemy as sa
from alembic import op

revision = "0005_trusted_evidence_chain"
down_revision = "0004_governed_tool_gateway"
branch_labels = None
depends_on = None


def _tenant_columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(length=36),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
    )


def _authority_columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("optimistic_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def _enable_tenant_authority(table: str) -> None:
    op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'CREATE POLICY tenant_isolation ON "{table}" '
        "USING (tenant_id = current_setting('app.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
    )


def upgrade() -> None:
    op.create_table(
        "evidence_capture_sagas",
        *_tenant_columns(),
        sa.Column("evidence_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("action_id", sa.String(length=36), nullable=False),
        sa.Column("criterion_id", sa.String(length=200), nullable=False),
        sa.Column("source", sa.String(length=300), nullable=False),
        sa.Column("artifact_uri", sa.String(length=1000), nullable=False),
        sa.Column("expected_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("failure_reason", sa.String(length=1000), nullable=True),
        *_authority_columns(),
        sa.UniqueConstraint("tenant_id", "id", name="uq_evidence_capture_sagas_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "evidence_id", name="uq_evidence_capture_saga_evidence"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "run_id"],
            ["runs.tenant_id", "runs.id"],
            name="fk_evidence_capture_sagas_tenant_run_id_runs",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "action_id"],
            ["actions.tenant_id", "actions.id"],
            name="fk_evidence_capture_sagas_tenant_action_id_actions",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'committed', 'failed')",
            name="ck_evidence_capture_sagas_legal_status",
        ),
        sa.CheckConstraint(
            "length(expected_digest) = 64",
            name="ck_evidence_capture_sagas_expected_digest_length",
        ),
        sa.CheckConstraint(
            "optimistic_version > 0",
            name="ck_evidence_capture_sagas_positive_optimistic_version",
        ),
    )
    op.create_table(
        "evidence_deletions",
        *_tenant_columns(),
        sa.Column("evidence_id", sa.String(length=36), nullable=False),
        sa.Column("artifact_uri", sa.String(length=1000), nullable=False),
        sa.Column("requested_by", sa.String(length=36), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_version_id", sa.String(length=300), nullable=True),
        sa.Column("proof_digest", sa.String(length=64), nullable=True),
        sa.Column("failure_reason", sa.String(length=1000), nullable=True),
        *_authority_columns(),
        sa.UniqueConstraint("tenant_id", "id", name="uq_evidence_deletions_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "evidence_id", name="uq_evidence_deletion_evidence"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "evidence_id"],
            ["evidence.tenant_id", "evidence.id"],
            name="fk_evidence_deletions_tenant_evidence_id_evidence",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('requested', 'retention_blocked', 'deleted', 'failed')",
            name="ck_evidence_deletions_legal_status",
        ),
        sa.CheckConstraint(
            "proof_digest IS NULL OR length(proof_digest) = 64",
            name="ck_evidence_deletions_proof_digest_length",
        ),
        sa.CheckConstraint(
            "optimistic_version > 0",
            name="ck_evidence_deletions_positive_optimistic_version",
        ),
    )
    for table in ("evidence_capture_sagas", "evidence_deletions"):
        _enable_tenant_authority(table)

    op.add_column("audit_events", sa.Column("sequence", sa.BigInteger(), nullable=True))
    op.add_column("audit_events", sa.Column("previous_digest", sa.String(length=64), nullable=True))
    op.add_column("audit_events", sa.Column("event_digest", sa.String(length=64), nullable=True))
    op.create_unique_constraint(
        "uq_audit_event_tenant_sequence", "audit_events", ["tenant_id", "sequence"]
    )
    op.create_unique_constraint(
        "uq_audit_event_tenant_digest", "audit_events", ["tenant_id", "event_digest"]
    )
    op.execute(
        """DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autonoesis_app') THEN
            GRANT SELECT, INSERT, UPDATE ON evidence_capture_sagas, evidence_deletions
                TO autonoesis_app;
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autonoesis_audit') THEN
            GRANT SELECT ON evidence_capture_sagas, evidence_deletions TO autonoesis_audit;
        END IF;
        END $$"""
    )


def downgrade() -> None:
    raise RuntimeError(
        "P0-07 records compliance Evidence and audit proofs; restore a pre-upgrade backup "
        "instead of deleting those facts in place"
    )
