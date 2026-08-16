"""Pin candidate fixed references and retire digest-less legacy candidates."""

import sqlalchemy as sa
from alembic import op

revision = "0010_fixed_candidate_references"
down_revision = "0009_fixed_evaluation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "candidates",
        sa.Column("artifact_digest", sa.String(64), nullable=False, server_default=""),
    )
    op.add_column(
        "candidates",
        sa.Column("suite_id", sa.String(200), nullable=False, server_default=""),
    )
    op.add_column(
        "candidates",
        sa.Column("suite_version", sa.String(64), nullable=False, server_default="0"),
    )
    # Legacy candidates were created without an immutable artifact digest or the fixed Suite they
    # must be graded against. They cannot invent that evidence after the fact, so they are retired
    # as rejected terminal records. The placeholder digest is a deterministic function of the row
    # identity solely to satisfy the non-null shape; rejected candidates can never re-enter the
    # evaluation pipeline, and every new candidate carries a real digest.
    op.execute(
        """
        UPDATE candidates
        SET status = 'rejected',
            artifact_digest = encode(sha256(('legacy-candidate:' || id)::bytea), 'hex'),
            suite_id = 'legacy-unknown',
            suite_version = '0',
            definition = definition::jsonb
                || '{"legacy_fixed_reference_retired": true}'::jsonb
        WHERE artifact_digest = ''
        """
    )
    op.alter_column("candidates", "artifact_digest", server_default=None)
    op.alter_column("candidates", "suite_id", server_default=None)
    op.alter_column("candidates", "suite_version", server_default=None)
    op.create_index(
        "ix_candidates_fixed_suite",
        "candidates",
        ["tenant_id", "suite_id", "suite_version"],
        unique=False,
    )


def downgrade() -> None:
    # Reinstating candidates without immutable digests or fixed Suites would restore release
    # claims that were never backed by verifiable artifacts, so this migration is one-way.
    raise RuntimeError("fixed candidate references cannot be removed after adoption")
