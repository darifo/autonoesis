"""Add kill_switches table for multi-dimensional emergency circuit-breaking.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_kill_switches"
down_revision: str | None = "0001_initial_platform"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kill_switches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("dimension", sa.String(32), nullable=False),
        sa.Column("target", sa.String(300), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("activated_by", sa.String(300), nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("optimistic_version", sa.Integer, nullable=False, default=1),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("kill_switches")
