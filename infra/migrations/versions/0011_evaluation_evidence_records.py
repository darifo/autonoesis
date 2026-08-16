"""Link Trials to Candidates and persist evaluation evidence records."""

import sqlalchemy as sa
from alembic import op

revision = "0011_evaluation_evidence_records"
down_revision = "0010_fixed_candidate_references"
branch_labels = None
depends_on = None


def _rls(name: str) -> None:
    op.execute(f'ALTER TABLE "{name}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{name}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'CREATE POLICY tenant_isolation ON "{name}" '
        "USING (tenant_id = current_setting('app.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
    )


def upgrade() -> None:
    op.add_column(
        "evaluation_trials",
        sa.Column("candidate_id", sa.String(36), nullable=True),
    )
    op.create_index(
        "ix_evaluation_trials_candidate",
        "evaluation_trials",
        ["tenant_id", "candidate_id"],
        unique=False,
    )
    op.create_table(
        "candidate_evaluations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("trial_ids", sa.JSON, nullable=False),
        sa.Column("assessment", sa.JSON, nullable=False),
        sa.Column("grader_principal_id", sa.String(300), nullable=False),
        sa.Column("optimistic_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id", "candidate_id"],
            ["candidates.tenant_id", "candidates.id"],
            name="fk_candidate_evaluations_candidate",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_candidate_evaluations_tenant_id_id"),
        sa.CheckConstraint(
            "optimistic_version > 0", name="ck_candidate_evaluations_positive_version"
        ),
        sa.CheckConstraint(
            "decision in ('met', 'not_met', 'insufficient_sample')",
            name="candidates_evaluation_decision_check",
        ),
    )
    op.create_index("ix_candidate_evaluations_tenant_id", "candidate_evaluations", ["tenant_id"])
    op.create_index(
        "ix_candidate_evaluations_candidate",
        "candidate_evaluations",
        ["tenant_id", "candidate_id"],
        unique=False,
    )
    _rls("candidate_evaluations")


def downgrade() -> None:
    # Dropping evaluation evidence records would detach Candidates from the
    # Trials that justified their promotion, so this migration is one-way.
    raise RuntimeError("evaluation evidence records cannot be removed after adoption")
