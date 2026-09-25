"""Bound device attribution and active-plan reads without changing retained rows."""

import sqlalchemy as sa

from alembic import op

revision = "0013_bounded_reads"
down_revision = "0012_budget_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "actions_verified_target",
        "actions",
        [
            "household_id",
            sa.text("(proposal['target'] ->> 'adapter')"),
            sa.text("(proposal['target'] ->> 'entity')"),
            sa.text("execution_attempt_seq DESC"),
        ],
        postgresql_where=sa.text("execution_status = 'verified'"),
    )
    op.create_index(
        "plans_active_latest",
        "plans",
        ["household_id", sa.text("audit_seq DESC")],
        postgresql_where=sa.text(
            "(document ->> 'status') NOT IN ('superseded', 'completed', 'abandoned')"
        ),
    )


def downgrade() -> None:
    op.drop_index("plans_active_latest", table_name="plans")
    op.drop_index("actions_verified_target", table_name="actions")
