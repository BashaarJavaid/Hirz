"""Durable household tool requests, proposals, plan preparation and private checks."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0010_household_tools"
down_revision = "0009_memory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tool_requests",
        sa.Column("household_id", sa.UUID, primary_key=True),
        sa.Column("principal_hash", sa.Text, primary_key=True),
        sa.Column("request_id", sa.Text, primary_key=True),
        sa.Column("fingerprint", sa.Text, nullable=False),
        sa.Column("result", JSONB, nullable=False),
        sa.Column("decision_seq", sa.BigInteger, nullable=False),
        sa.ForeignKeyConstraint(
            ["household_id", "decision_seq"],
            ["audit_log.household_id", "audit_log.seq"],
        ),
        sa.CheckConstraint("length(request_id) BETWEEN 1 AND 128"),
    )
    op.create_table(
        "rule_proposals",
        sa.Column("household_id", sa.UUID, primary_key=True),
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("member_id", sa.UUID, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("surface", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision_seq", sa.BigInteger, nullable=False),
        sa.ForeignKeyConstraint(
            ["household_id", "member_id"], ["members.household_id", "members.id"]
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "decision_seq"],
            ["audit_log.household_id", "audit_log.seq"],
        ),
        sa.CheckConstraint("length(text) BETWEEN 1 AND 2000"),
    )
    op.create_table(
        "plan_requests",
        sa.Column("household_id", sa.UUID, primary_key=True),
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("principal", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("horizon_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("plan_id", sa.Text),
        sa.Column("decision_seq", sa.BigInteger, nullable=False),
        sa.ForeignKeyConstraint(
            ["household_id", "decision_seq"],
            ["audit_log.household_id", "audit_log.seq"],
        ),
        sa.CheckConstraint("status IN ('pending','ready','failed')"),
        sa.CheckConstraint("horizon_end > created_at"),
    )
    op.create_table(
        "verification_cases",
        sa.Column("household_id", sa.UUID, primary_key=True),
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("member_id", sa.UUID, nullable=False),
        sa.Column("document", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision_seq", sa.BigInteger, nullable=False),
        sa.ForeignKeyConstraint(
            ["household_id", "member_id"], ["members.household_id", "members.id"]
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "decision_seq"],
            ["audit_log.household_id", "audit_log.seq"],
        ),
    )


def downgrade() -> None:
    names = ("tool_requests", "rule_proposals", "plan_requests", "verification_cases")
    op.execute(
        "LOCK TABLE tool_requests, rule_proposals, plan_requests, verification_cases IN ACCESS EXCLUSIVE MODE"
    )
    for name in names:
        if op.get_bind().scalar(sa.text(f"SELECT count(*) FROM {name}")):
            raise RuntimeError("Household tool evidence prevents downgrade")
    for name in reversed(names):
        op.drop_table(name)
