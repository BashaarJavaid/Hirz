"""Durable isolated Twin controls and last published scenario snapshot."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0018_companion_runs"
down_revision = "0017_rule_drafting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "companion_runs",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("household_id", sa.UUID, nullable=False),
        sa.Column("member_id", sa.UUID, nullable=False),
        sa.Column("principal", JSONB, nullable=False),
        sa.Column("scenario", sa.Text, nullable=False),
        sa.Column("controls", JSONB, nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("published_revision", sa.Integer),
        sa.Column("snapshot", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["household_id", "member_id"], ["members.household_id", "members.id"]
        ),
        sa.CheckConstraint("revision > 0", name="run_revision_positive"),
    )


def downgrade() -> None:
    op.drop_table("companion_runs")
