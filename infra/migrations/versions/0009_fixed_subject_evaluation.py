"""Invalidate synthetic trials and permit repeated fixed-condition evaluation."""

from alembic import op

revision = "0009_fixed_evaluation"
down_revision = "0008_trusted_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Previous builds could mark a Trial passed or failed without executing a Subject. Preserve the
    # record, but remove the unsupported release claim instead of fabricating missing evidence.
    op.execute(
        """
        UPDATE evaluation_trials
        SET status = 'invalid',
            result = json_build_object(
                'random_seed', NULL,
                'case_results', json_build_array(),
                'total_cost_microunits', 0,
                'failure_reason', 'legacy trial has no recorded subject execution',
                'started_at', NULL,
                'completed_at', NULL
            )
        WHERE status IN ('passed', 'failed')
          AND (result IS NULL OR result::jsonb = '{}'::jsonb)
        """
    )
    # Repeated Trials intentionally share fixed conditions and differ by seed/run evidence. The
    # primary key remains their identity; this constraint incorrectly prohibited repetition.
    op.drop_constraint("uq_trial_fixed_conditions", "evaluation_trials", type_="unique")
    op.create_index(
        "ix_evaluation_trials_fixed_conditions",
        "evaluation_trials",
        [
            "tenant_id",
            "suite_id",
            "suite_version",
            "subject_version_id",
            "harness_version",
        ],
        unique=False,
    )


def downgrade() -> None:
    raise RuntimeError(
        "P1-04 invalidates unsupported release evidence; restore a backup instead of recreating "
        "synthetic Trial claims"
    )
