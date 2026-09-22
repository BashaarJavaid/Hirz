"""Private session turns and immutable consent proposals."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0009_memory"
down_revision = "0008_plan_refresh"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "session_turns",
        sa.Column("household_id", sa.UUID, primary_key=True),
        sa.Column("id", sa.UUID, primary_key=True),
        sa.Column("member_id", sa.UUID, nullable=False),
        sa.Column("surface", sa.Text, nullable=False),
        sa.Column("session_id", sa.Text, nullable=False),
        sa.Column("sequence", sa.BigInteger, nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("references", JSONB, nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision_seq", sa.BigInteger, nullable=False),
        sa.UniqueConstraint(
            "household_id", "member_id", "surface", "session_id", "sequence"
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "member_id"], ["members.household_id", "members.id"]
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "decision_seq"],
            ["audit_log.household_id", "audit_log.seq"],
        ),
        sa.CheckConstraint(
            "length(session_id) BETWEEN 1 AND 256 AND length(text) BETWEEN 1 AND 8000"
        ),
        sa.CheckConstraint(
            "sequence > 0 AND role IN ('user','assistant') AND surface IN ('alexa','app','scheduler')"
        ),
    )
    op.create_table(
        "memory_proposals",
        sa.Column("household_id", sa.UUID, primary_key=True),
        sa.Column("id", sa.UUID, primary_key=True),
        sa.Column("member_id", sa.UUID, nullable=False),
        sa.Column("source_turn", sa.UUID, nullable=False),
        sa.Column("candidate", JSONB, nullable=False),
        sa.Column("preference_id", sa.UUID),
        sa.Column("preference_version", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision_seq", sa.BigInteger, nullable=False),
        sa.Column("audit_seq", sa.BigInteger, nullable=False),
        sa.Column("review_seq", sa.BigInteger),
        sa.ForeignKeyConstraint(
            ["household_id", "member_id"], ["members.household_id", "members.id"]
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "source_turn"],
            ["session_turns.household_id", "session_turns.id"],
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "preference_id"],
            ["preferences.household_id", "preferences.id"],
        ),
        *(
            sa.ForeignKeyConstraint(
                ["household_id", name], ["audit_log.household_id", "audit_log.seq"]
            )
            for name in ("decision_seq", "audit_seq", "review_seq")
        ),
        sa.CheckConstraint("status IN ('pending','accepted','rejected')"),
        sa.CheckConstraint("(preference_id IS NULL) = (preference_version IS NULL)"),
        sa.CheckConstraint("(status = 'pending') = (review_seq IS NULL)"),
    )


def downgrade() -> None:
    op.execute(
        "LOCK TABLE session_turns, memory_proposals, audit_log IN ACCESS EXCLUSIVE MODE"
    )
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM session_turns) OR EXISTS (SELECT 1 FROM memory_proposals) OR EXISTS (SELECT 1 FROM audit_log WHERE event_type IN ('MEMORY_PROPOSED','MEMORY_ACCEPTED','MEMORY_REJECTED'))"
        )
    ):
        raise RuntimeError("Memory evidence prevents downgrade")
    op.drop_table("memory_proposals")
    op.drop_table("session_turns")
