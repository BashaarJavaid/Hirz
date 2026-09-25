"""Retain explicit first-plan objective choices across worker restart."""

import sqlalchemy as sa

from alembic import op

revision = "0011_planning_objective"
down_revision = "0010_household_tools"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plan_requests", sa.Column("objective", sa.Text))
    op.create_check_constraint(
        "plan_requests_objective",
        "plan_requests",
        "objective IN ('cheapest','greenest','most_comfortable')",
    )


def downgrade() -> None:
    op.execute("LOCK TABLE plan_requests IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM plan_requests WHERE objective IS NOT NULL")
    ):
        raise RuntimeError("Planning objective evidence prevents downgrade")
    op.drop_constraint("plan_requests_objective", "plan_requests", type_="check")
    op.drop_column("plan_requests", "objective")
