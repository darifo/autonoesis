"""Create the Goal-driven platform authority schema."""

from alembic import op
from autonoesis_adapters.persistence import metadata

revision = "0001_initial_platform"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    metadata.create_all(bind=bind)
    tenant_tables = [table for table in metadata.sorted_tables if "tenant_id" in table.c]
    for table in tenant_tables:
        op.execute(f'ALTER TABLE "{table.name}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table.name}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_isolation ON "{table.name}" '
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )


def downgrade() -> None:
    metadata.drop_all(bind=op.get_bind())
