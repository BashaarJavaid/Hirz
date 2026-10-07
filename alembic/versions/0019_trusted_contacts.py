"""Private contact channels, safe words, delivery jobs and scoped receipts."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0019_trusted_contacts"
down_revision = "0018_companion_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contact_secrets",
        sa.Column("household_id", sa.UUID, primary_key=True),
        sa.Column("contact_id", sa.UUID, primary_key=True),
        sa.Column("word_hash", JSONB),
        sa.Column("guesses", JSONB, nullable=False),
        sa.Column("decision_seq", sa.BigInteger, nullable=False),
        sa.ForeignKeyConstraint(
            ["household_id", "decision_seq"],
            ["audit_log.household_id", "audit_log.seq"],
        ),
    )
    op.create_table(
        "contact_links",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("household_id", sa.UUID, nullable=False),
        sa.Column("contact_id", sa.UUID, nullable=False),
        sa.Column("owner_id", sa.UUID, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("token_digest", sa.Text, nullable=False, unique=True),
        sa.Column("ciphertext", sa.LargeBinary),
        sa.Column("recipient_household", sa.UUID),
        sa.Column("recipient_member", sa.UUID),
        sa.Column("proof", JSONB),
        sa.Column("delivery_attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("delivery_status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("next_attempt", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "delivery_attempts BETWEEN 0 AND 3", name="enrollment_attempt_limit"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision_seq", sa.BigInteger, nullable=False),
        sa.ForeignKeyConstraint(
            ["household_id", "owner_id"], ["members.household_id", "members.id"]
        ),
        sa.ForeignKeyConstraint(
            ["recipient_household", "recipient_member"],
            ["members.household_id", "members.id"],
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "decision_seq"],
            ["audit_log.household_id", "audit_log.seq"],
        ),
        sa.CheckConstraint("kind IN ('app', 'email')", name="contact_link_kind"),
        sa.CheckConstraint(
            "status IN ('pending', 'confirmed', 'active', 'revoked')",
            name="contact_link_status",
        ),
    )
    op.create_table(
        "checkin_jobs",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("household_id", sa.UUID, nullable=False),
        sa.Column("member_id", sa.UUID, nullable=False),
        sa.Column(
            "link_id", sa.Text, sa.ForeignKey("contact_links.id"), nullable=False
        ),
        sa.Column("case_id", sa.Text, nullable=False),
        sa.Column("action_id", sa.Text, nullable=False),
        sa.Column("request_hash", sa.Text, nullable=False),
        sa.Column("principal", JSONB, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("token_digest", sa.Text, unique=True),
        sa.Column("ciphertext", sa.LargeBinary),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("next_attempt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision_seq", sa.BigInteger, nullable=False),
        sa.ForeignKeyConstraint(
            ["household_id", "case_id"],
            ["verification_cases.household_id", "verification_cases.id"],
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "member_id"], ["members.household_id", "members.id"]
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "decision_seq"],
            ["audit_log.household_id", "audit_log.seq"],
        ),
        sa.UniqueConstraint("household_id", "case_id"),
        sa.CheckConstraint("attempts BETWEEN 0 AND 3", name="checkin_attempt_limit"),
        sa.CheckConstraint(
            "status IN ('approval', 'pending', 'sending', 'sent', 'closed')",
            name="checkin_job_status",
        ),
    )
    op.create_table(
        "checkin_receipts",
        sa.Column(
            "job_id", sa.Text, sa.ForeignKey("checkin_jobs.id"), primary_key=True
        ),
        sa.Column("household_id", sa.UUID, nullable=False),
        sa.Column("member_id", sa.UUID),
        sa.Column("answer", sa.Text, nullable=False),
        sa.Column("proof", sa.Text, nullable=False),
        sa.Column("request_hash", sa.Text, nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision_seq", sa.BigInteger, nullable=False),
        sa.ForeignKeyConstraint(
            ["household_id", "member_id"], ["members.household_id", "members.id"]
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "decision_seq"],
            ["audit_log.household_id", "audit_log.seq"],
        ),
        sa.CheckConstraint(
            "answer IN ('genuine', 'not_genuine', 'will_call')", name="checkin_answer"
        ),
        sa.CheckConstraint("proof IN ('passkey', 'mailbox')", name="checkin_proof"),
    )


def downgrade() -> None:
    for name in (
        "checkin_receipts",
        "checkin_jobs",
        "contact_links",
        "contact_secrets",
    ):
        op.drop_table(name)
