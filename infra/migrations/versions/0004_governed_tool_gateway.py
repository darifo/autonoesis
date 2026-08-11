"""Make governed tool reservations authoritative and replay-safe."""

import sqlalchemy as sa
from alembic import op

revision = "0004_governed_tool_gateway"
down_revision = "0003_application_use_cases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in (
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("action_id", sa.String(length=36), nullable=True),
        sa.Column("tool_name", sa.String(length=200), nullable=True),
        sa.Column("tool_version", sa.String(length=64), nullable=True),
        sa.Column("cost_units", sa.BigInteger(), nullable=True),
    ):
        op.add_column("idempotency_records", column)
    op.create_foreign_key(
        "fk_idempotency_records_tenant_run_id_runs",
        "idempotency_records",
        "runs",
        ["tenant_id", "run_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_idempotency_records_tenant_action_id_actions",
        "idempotency_records",
        "actions",
        ["tenant_id", "action_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint("ck_idempotency_records_legal_status", "idempotency_records", type_="check")
    op.create_check_constraint(
        "ck_idempotency_records_legal_status",
        "idempotency_records",
        "status IN ('pending', 'accepted', 'completed', 'failed', 'unknown')",
    )
    op.create_check_constraint(
        "ck_idempotency_records_positive_cost",
        "idempotency_records",
        "cost_units IS NULL OR cost_units > 0",
    )
    op.create_index(
        "ix_idempotency_records_execution_identity",
        "idempotency_records",
        ["tenant_id", "tool_version", "idempotency_key", "request_digest"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "P0-05 reservations are durable execution facts; restore a pre-upgrade backup "
        "instead of deleting them in place"
    )
