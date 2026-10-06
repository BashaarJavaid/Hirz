"""Encrypted push endpoints and durable bounded delivery attempts."""

import sqlalchemy as sa

from alembic import op

revision = "0016_companion_push"
down_revision = "0015_companion_policy"
branch_labels = None
depends_on = None
metadata = sa.MetaData()
sa.Table(
    "members",
    metadata,
    sa.Column("household_id", sa.UUID, primary_key=True),
    sa.Column("id", sa.UUID, primary_key=True),
)

companion_push = sa.Table(
    "companion_push",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("household_id", sa.UUID, nullable=False),
    sa.Column("member_id", sa.UUID, nullable=False),
    sa.Column("endpoint_hash", sa.Text, nullable=False),
    sa.Column("ciphertext", sa.LargeBinary, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("disabled_at", sa.DateTime(timezone=True)),
    sa.ForeignKeyConstraint(
        ["household_id", "member_id"], ["members.household_id", "members.id"]
    ),
    sa.UniqueConstraint("household_id", "endpoint_hash", name="push_endpoint_unique"),
)
companion_delivery = sa.Table(
    "companion_delivery",
    metadata,
    sa.Column(
        "subscription_id", sa.Text, sa.ForeignKey("companion_push.id"), primary_key=True
    ),
    sa.Column("reference", sa.Text, primary_key=True),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("next_attempt", sa.DateTime(timezone=True), nullable=False),
    sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
    sa.Column("status", sa.Text, nullable=False, server_default="pending"),
    sa.CheckConstraint("attempts BETWEEN 0 AND 3", name="push_attempt_limit"),
    sa.CheckConstraint(
        "status IN ('pending', 'sending', 'sent', 'failed')",
        name="push_delivery_status",
    ),
)


def upgrade() -> None:
    companion_push.create(op.get_bind())
    companion_delivery.create(op.get_bind())


def downgrade() -> None:
    companion_delivery.drop(op.get_bind())
    companion_push.drop(op.get_bind())
