"""Establish tenant-safe authoritative state and deployment persistence."""

from collections.abc import Iterable

import sqlalchemy as sa
from alembic import op

revision = "0002_authoritative_state"
down_revision = "0001_initial_platform"
branch_labels = None
depends_on = None


LEGACY_TENANT_TABLES = (
    "capability_packs",
    "agent_versions",
    "skill_versions",
    "tool_versions",
    "goals",
    "runs",
    "plans",
    "tasks",
    "actions",
    "approvals",
    "context_snapshots",
    "evidence",
    "outcomes",
    "budget_ledger",
    "evaluation_trials",
    "improvement_proposals",
    "candidates",
    "releases",
    "audit_events",
    "kill_switches",
    "outbox",
    "inbox",
    "idempotency_records",
)
NEW_TENANT_TABLES = ("policy_versions", "budgets", "deployments")


def _tenant_table(
    name: str,
    columns: Iterable[sa.Column[object]],
    *constraints: sa.Constraint,
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
        sa.Column("optimistic_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "id", name=f"uq_{name}_tenant_id_id"),
        sa.CheckConstraint("optimistic_version > 0", name=f"ck_{name}_positive_optimistic_version"),
        *constraints,
    )
    op.create_index(f"ix_{name}_tenant_id", name, ["tenant_id"])


def _add_column(
    table: str,
    column: sa.Column[object],
    *,
    remove_default: bool = True,
) -> None:
    op.add_column(table, column)
    if remove_default and column.server_default is not None:
        op.alter_column(table, column.name, server_default=None)


def _status_check(table: str, values: tuple[str, ...]) -> None:
    allowed = ", ".join(f"'{value}'" for value in values)
    op.create_check_constraint(f"ck_{table}_legal_status", table, f"status IN ({allowed})")


def _tenant_fk(table: str) -> None:
    op.create_foreign_key(
        f"fk_{table}_tenant_authority",
        table,
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(f"uq_{table}_tenant_id_id", table, ["tenant_id", "id"])
    op.create_check_constraint(
        f"ck_{table}_positive_optimistic_version", table, "optimistic_version > 0"
    )


def _tenant_reference(table: str, local_column: str, target: str) -> None:
    op.create_foreign_key(
        f"fk_{table}_tenant_{local_column}_{target}",
        table,
        target,
        ["tenant_id", local_column],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    # Preserve preview data while making every tenant reference resolvable by the
    # Tenant Authority. The generated names are intentionally conspicuous so an
    # operator can rename them after reconciling against the external directory.
    for table in LEGACY_TENANT_TABLES:
        op.execute(
            sa.text(
                f"""INSERT INTO tenants (id, name, created_at)
                SELECT DISTINCT tenant_id, 'legacy-' || tenant_id, CURRENT_TIMESTAMP
                FROM {table}
                ON CONFLICT (id) DO NOTHING"""
            )
        )
    for table in LEGACY_TENANT_TABLES:
        _tenant_fk(table)

    _tenant_table(
        "policy_versions",
        (
            sa.Column("policy_id", sa.String(length=200), nullable=False),
            sa.Column("version", sa.String(length=64), nullable=False),
            sa.Column("definition", sa.JSON(), nullable=False),
        ),
        sa.UniqueConstraint("tenant_id", "policy_id", "version", name="uq_policy_asset_version"),
    )
    _tenant_table(
        "budgets",
        (
            sa.Column("budget_id", sa.String(length=200), nullable=False),
            sa.Column("version", sa.String(length=64), nullable=False),
            sa.Column("definition", sa.JSON(), nullable=False),
        ),
        sa.UniqueConstraint("tenant_id", "budget_id", "version", name="uq_budget_asset_version"),
    )

    _add_column(
        "agent_versions",
        sa.Column("name", sa.String(length=120), nullable=False, server_default="legacy-agent"),
    )
    op.create_unique_constraint(
        "uq_capability_pack_version",
        "capability_packs",
        ["tenant_id", "pack_id", "version"],
    )
    op.create_unique_constraint(
        "uq_agent_asset_version", "agent_versions", ["tenant_id", "agent_id", "version"]
    )
    op.create_unique_constraint(
        "uq_agent_name_version", "agent_versions", ["tenant_id", "name", "version"]
    )
    op.create_unique_constraint(
        "uq_skill_asset_version", "skill_versions", ["tenant_id", "skill_id", "version"]
    )
    op.create_unique_constraint(
        "uq_tool_asset_version", "tool_versions", ["tenant_id", "tool_id", "version"]
    )
    op.create_check_constraint(
        "ck_agent_versions_legal_stage",
        "agent_versions",
        "stage IN ('candidate', 'stable', 'retired')",
    )
    _status_check("goals", ("draft", "active", "paused", "satisfied", "failed", "cancelled"))

    _add_column(
        "runs", sa.Column("definition", sa.JSON(), nullable=False, server_default=sa.text("'{}'"))
    )
    op.create_unique_constraint("uq_run_workflow_id", "runs", ["tenant_id", "temporal_workflow_id"])
    _tenant_reference("runs", "goal_id", "goals")
    _status_check(
        "runs",
        (
            "pending",
            "running",
            "blocked",
            "awaiting_evidence",
            "succeeded",
            "failed",
            "cancelled",
        ),
    )

    _add_column(
        "plans", sa.Column("goal_id", sa.String(length=36), nullable=True), remove_default=False
    )
    op.execute(
        "UPDATE plans SET goal_id = runs.goal_id FROM runs "
        "WHERE plans.run_id = runs.id AND plans.tenant_id = runs.tenant_id"
    )
    op.alter_column("plans", "goal_id", nullable=False)
    _tenant_reference("plans", "goal_id", "goals")
    _tenant_reference("plans", "run_id", "runs")
    op.create_unique_constraint("uq_plan_run_version", "plans", ["tenant_id", "run_id", "version"])
    _tenant_reference("tasks", "run_id", "runs")
    _tenant_reference("tasks", "plan_id", "plans")
    _status_check("tasks", ("pending", "ready", "running", "blocked", "succeeded", "failed"))

    _add_column(
        "actions",
        sa.Column(
            "action_digest",
            sa.String(length=64),
            nullable=False,
            server_default="0000000000000000000000000000000000000000000000000000000000000000",
        ),
    )
    _tenant_reference("actions", "run_id", "runs")
    _tenant_reference("actions", "task_id", "tasks")
    op.create_unique_constraint("uq_action_run_id", "actions", ["tenant_id", "run_id", "id"])
    _status_check(
        "actions",
        (
            "proposed",
            "awaiting_approval",
            "authorized",
            "executing",
            "succeeded",
            "failed",
            "denied",
            "unknown",
        ),
    )

    _add_column(
        "approvals", sa.Column("run_id", sa.String(length=36), nullable=True), remove_default=False
    )
    op.execute(
        "UPDATE approvals SET run_id = actions.run_id FROM actions "
        "WHERE approvals.action_id = actions.id AND approvals.tenant_id = actions.tenant_id"
    )
    op.alter_column("approvals", "run_id", nullable=False)
    _add_column(
        "approvals",
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP + INTERVAL '1 day'"),
        ),
    )
    _add_column(
        "approvals",
        sa.Column("definition", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    _tenant_reference("approvals", "run_id", "runs")
    _tenant_reference("approvals", "action_id", "actions")
    op.create_foreign_key(
        "fk_approvals_action_run",
        "approvals",
        "actions",
        ["tenant_id", "run_id", "action_id"],
        ["tenant_id", "run_id", "id"],
    )
    _status_check("approvals", ("pending", "approved", "rejected", "expired"))
    _tenant_reference("context_snapshots", "goal_id", "goals")
    _tenant_reference("context_snapshots", "run_id", "runs")

    _add_column(
        "evidence",
        sa.Column("action_id", sa.String(length=36), nullable=True),
        remove_default=False,
    )
    _add_column(
        "evidence",
        sa.Column(
            "source_identity", sa.String(length=300), nullable=False, server_default="legacy"
        ),
    )
    _add_column(
        "evidence",
        sa.Column(
            "capture_method", sa.String(length=64), nullable=False, server_default="system_query"
        ),
    )
    _add_column(
        "evidence",
        sa.Column(
            "classification", sa.String(length=32), nullable=False, server_default="internal"
        ),
    )
    _add_column(
        "evidence",
        sa.Column(
            "valid_from",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    _add_column(
        "evidence",
        sa.Column(
            "valid_until",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP + INTERVAL '100 years'"),
        ),
    )
    _add_column(
        "evidence",
        sa.Column("integrity", sa.String(length=32), nullable=False, server_default="unverified"),
    )
    _add_column(
        "evidence",
        sa.Column("definition", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.execute(
        "DO $$ BEGIN IF EXISTS ("
        "SELECT evidence.id FROM evidence LEFT JOIN actions "
        "ON evidence.run_id = actions.run_id AND evidence.tenant_id = actions.tenant_id "
        "GROUP BY evidence.id HAVING count(actions.id) > 1"
        ") THEN RAISE EXCEPTION "
        "'legacy evidence matches multiple Actions; reconcile before P0-03'; "
        "END IF; END $$"
    )
    op.execute(
        "UPDATE evidence SET action_id = actions.id FROM actions "
        "WHERE evidence.run_id = actions.run_id AND evidence.tenant_id = actions.tenant_id "
        "AND evidence.action_id IS NULL"
    )
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM evidence WHERE action_id IS NULL) THEN "
        "RAISE EXCEPTION 'legacy evidence has no matching Action; reconcile before P0-03'; "
        "END IF; END $$"
    )
    op.alter_column("evidence", "action_id", nullable=False)
    _tenant_reference("evidence", "run_id", "runs")
    _tenant_reference("evidence", "action_id", "actions")
    op.create_foreign_key(
        "fk_evidence_action_run",
        "evidence",
        "actions",
        ["tenant_id", "run_id", "action_id"],
        ["tenant_id", "run_id", "id"],
    )
    op.create_check_constraint(
        "ck_evidence_content_digest_length", "evidence", "length(content_digest) = 64"
    )
    op.create_check_constraint(
        "ck_evidence_validity_interval", "evidence", "valid_until >= valid_from"
    )

    _add_column(
        "outcomes",
        sa.Column("criterion_id", sa.String(length=200), nullable=False, server_default="legacy"),
    )
    _add_column(
        "outcomes",
        sa.Column(
            "verifier_version", sa.String(length=200), nullable=False, server_default="legacy@1"
        ),
    )
    _tenant_reference("outcomes", "goal_id", "goals")
    _tenant_reference("outcomes", "run_id", "runs")
    op.create_unique_constraint(
        "uq_outcome_criterion", "outcomes", ["tenant_id", "run_id", "criterion_id"]
    )
    _status_check("outcomes", ("verified", "not_met", "unknown"))

    op.alter_column("budget_ledger", "units", new_column_name="amount")
    _add_column(
        "budget_ledger",
        sa.Column("unit", sa.String(length=32), nullable=False, server_default="cost_units"),
    )
    _tenant_reference("budget_ledger", "run_id", "runs")
    op.create_unique_constraint(
        "uq_budget_entry_reference",
        "budget_ledger",
        ["tenant_id", "run_id", "reference"],
    )
    op.create_check_constraint("ck_budget_ledger_positive_amount", "budget_ledger", "amount > 0")

    _add_column(
        "evaluation_trials",
        sa.Column("suite_version", sa.String(length=64), nullable=False, server_default="legacy"),
    )
    _add_column(
        "evaluation_trials",
        sa.Column(
            "harness_version", sa.String(length=200), nullable=False, server_default="legacy"
        ),
    )
    op.execute("UPDATE evaluation_trials SET result = '{}' WHERE result IS NULL")
    op.alter_column("evaluation_trials", "result", nullable=False)
    op.create_unique_constraint(
        "uq_trial_fixed_conditions",
        "evaluation_trials",
        [
            "tenant_id",
            "suite_id",
            "suite_version",
            "subject_version_id",
            "harness_version",
        ],
    )
    _status_check("evaluation_trials", ("pending", "running", "passed", "failed", "invalid"))

    op.execute(
        "UPDATE candidates SET status = 'approved' WHERE status IN ('stable', 'rolled_back')"
    )
    _add_column(
        "candidates",
        sa.Column(
            "baseline_version_id",
            sa.String(length=36),
            nullable=False,
            server_default="00000000-0000-0000-0000-000000000000",
        ),
    )
    _add_column(
        "candidates",
        sa.Column("generator_id", sa.String(length=300), nullable=False, server_default="legacy"),
    )
    _add_column(
        "candidates",
        sa.Column("definition", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    _tenant_reference("candidates", "proposal_id", "improvement_proposals")
    op.create_unique_constraint(
        "uq_candidate_artifact", "candidates", ["tenant_id", "proposal_id", "artifact_uri"]
    )
    _status_check(
        "candidates", ("draft", "evaluating", "awaiting_approval", "approved", "rejected")
    )

    _tenant_table(
        "deployments",
        (
            sa.Column("candidate_id", sa.String(length=36), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("definition", sa.JSON(), nullable=False),
            sa.ForeignKeyConstraint(
                ["tenant_id", "candidate_id"],
                ["candidates.tenant_id", "candidates.id"],
                name="fk_deployments_tenant_candidate_id_candidates",
            ),
            sa.CheckConstraint(
                "status IN ('shadow', 'canary', 'stable', 'failed', 'rolled_back')",
                name="ck_deployments_legal_status",
            ),
        ),
    )
    op.execute(
        """INSERT INTO deployments
        (id, tenant_id, candidate_id, status, definition, optimistic_version, created_at)
        SELECT substr(md5(id),1,8) || '-' || substr(md5(id),9,4) || '-' ||
               substr(md5(id),13,4) || '-' || substr(md5(id),17,4) || '-' || substr(md5(id),21,12),
               tenant_id, candidate_id,
               CASE WHEN status = 'rolled_back' THEN 'rolled_back' ELSE 'stable' END,
               '{}', 1, created_at
        FROM releases"""
    )
    _add_column(
        "releases",
        sa.Column("deployment_id", sa.String(length=36), nullable=True),
        remove_default=False,
    )
    op.execute(
        "UPDATE releases SET deployment_id = substr(md5(id),1,8) || '-' || "
        "substr(md5(id),9,4) || '-' || substr(md5(id),13,4) || '-' || "
        "substr(md5(id),17,4) || '-' || substr(md5(id),21,12)"
    )
    op.alter_column("releases", "deployment_id", nullable=False)
    _add_column(
        "releases",
        sa.Column("stable_slot", sa.String(length=200), nullable=False, server_default="default"),
    )
    _add_column(
        "releases",
        sa.Column(
            "approved_by",
            sa.String(length=36),
            nullable=False,
            server_default="00000000-0000-0000-0000-000000000000",
        ),
    )
    _add_column(
        "releases", sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    _add_column(
        "releases",
        sa.Column("definition", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    _tenant_reference("releases", "candidate_id", "candidates")
    _tenant_reference("releases", "deployment_id", "deployments")
    op.create_index(
        "uq_releases_active_stable_slot",
        "releases",
        ["tenant_id", "stable_slot"],
        unique=True,
        postgresql_where=sa.text("active"),
    )
    op.drop_column("releases", "status")

    op.create_unique_constraint("uq_inbox_message", "inbox", ["tenant_id", "message_id"])
    _status_check("idempotency_records", ("pending", "completed", "failed", "unknown"))

    for table in NEW_TENANT_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_isolation ON "{table}" '
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )
    op.execute(
        """DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autonoesis_app') THEN
            GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO autonoesis_app;
            REVOKE INSERT, UPDATE ON tenants FROM autonoesis_app;
            REVOKE UPDATE ON audit_events FROM autonoesis_app;
            GRANT INSERT ON audit_events, outbox TO autonoesis_app;
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autonoesis_relay') THEN
            GRANT SELECT, UPDATE ON outbox TO autonoesis_relay;
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autonoesis_audit') THEN
            GRANT SELECT ON audit_events, evidence, outcomes, releases TO autonoesis_audit;
        END IF;
        END $$"""
    )


def downgrade() -> None:
    raise RuntimeError(
        "P0-03 introduces authoritative facts that the preview schema cannot represent; "
        "restore the pre-upgrade backup instead of performing an in-place downgrade"
    )
