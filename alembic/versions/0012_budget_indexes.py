"""Index scoped budget ledger reads without changing retained evidence."""

import sqlalchemy as sa

from alembic import op

revision = "0012_budget_indexes"
down_revision = "0011_planning_objective"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "actions_grant_lookup",
        "actions",
        ["household_id", "grant_seq"],
        postgresql_where=sa.text("grant_seq IS NOT NULL"),
    )
    op.create_index(
        "audit_budget_usage",
        "audit_log",
        [
            "household_id",
            sa.text("(payload['budget'] ->> 'class')"),
            sa.text("(payload['budget'] ->> 'local_date')"),
        ],
    )
    op.create_index(
        "audit_budget_adjustments",
        "audit_log",
        [
            "household_id",
            "event_type",
            sa.text("(payload ->> 'class')"),
            sa.text("(payload ->> 'local_date')"),
        ],
    )


def downgrade() -> None:
    op.drop_index("audit_budget_adjustments", table_name="audit_log")
    op.drop_index("audit_budget_usage", table_name="audit_log")
    op.drop_index("actions_grant_lookup", table_name="actions")
