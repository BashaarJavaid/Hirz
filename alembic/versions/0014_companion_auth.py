"""Durable credential and authentication bookkeeping; no enrollment or activation."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0014_companion_auth"
down_revision = "0013_bounded_reads"
branch_labels = None
depends_on = None

metadata = sa.MetaData()
# Resolve foreign keys against existing tables without creating them.
sa.Table(
    "members",
    metadata,
    sa.Column("household_id", sa.UUID, primary_key=True),
    sa.Column("id", sa.UUID, primary_key=True),
)

# Companion authentication bookkeeping; private tokens are stored only as digests.
member_passkeys = sa.Table(
    "member_passkeys",
    metadata,
    sa.Column("credential_id", sa.Text, primary_key=True),
    sa.Column("household_id", sa.UUID, nullable=False),
    sa.Column("member_id", sa.UUID, nullable=False),
    sa.Column("public_key", sa.LargeBinary, nullable=False),
    sa.Column("sign_count", sa.BigInteger, nullable=False),
    sa.Column("label", sa.Text, nullable=False),
    sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("revoked_at", sa.DateTime(timezone=True)),
    sa.ForeignKeyConstraint(
        ["household_id", "member_id"], ["members.household_id", "members.id"]
    ),
    sa.CheckConstraint("sign_count >= 0", name="passkey_counter_nonnegative"),
    sa.CheckConstraint("length(label) BETWEEN 1 AND 100", name="passkey_label_length"),
)
companion_enrollment = sa.Table(
    "companion_enrollment",
    metadata,
    sa.Column("digest", sa.Text, primary_key=True),
    sa.Column("household_id", sa.UUID, nullable=False),
    sa.Column("member_id", sa.UUID, nullable=False),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True)),
    sa.Column("used_at", sa.DateTime(timezone=True)),
    sa.ForeignKeyConstraint(
        ["household_id", "member_id"], ["members.household_id", "members.id"]
    ),
    sa.CheckConstraint(
        "kind IN ('invitation', 'recovery', 'reinvite')", name="enrollment_kind"
    ),
    sa.CheckConstraint(
        "kind = 'recovery' OR expires_at IS NOT NULL", name="invitation_expiry"
    ),
)
companion_sessions = sa.Table(
    "companion_sessions",
    metadata,
    sa.Column("digest", sa.Text, primary_key=True),
    sa.Column(
        "credential_id",
        sa.Text,
        sa.ForeignKey("member_passkeys.credential_id"),
        nullable=False,
    ),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
)
companion_ceremonies = sa.Table(
    "companion_ceremonies",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("browser_digest", sa.Text, nullable=False),
    sa.Column("session_digest", sa.Text),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("challenge", sa.LargeBinary, nullable=False),
    sa.Column("binding", JSONB, nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("used_at", sa.DateTime(timezone=True)),
    sa.CheckConstraint(
        "kind IN ('register', 'login', 'confirm')", name="ceremony_kind"
    ),
)


def upgrade() -> None:
    for table in (
        member_passkeys,
        companion_enrollment,
        companion_sessions,
        companion_ceremonies,
    ):
        table.create(op.get_bind())


def downgrade() -> None:
    for table in (
        companion_ceremonies,
        companion_sessions,
        companion_enrollment,
        member_passkeys,
    ):
        table.drop(op.get_bind())
