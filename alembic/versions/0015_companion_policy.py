"""Policy activation states and separate immutable review candidates."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0015_companion_policy"
down_revision = "0014_companion_auth"
branch_labels = None
depends_on = None
metadata = sa.MetaData()
sa.Table(
    "members",
    metadata,
    sa.Column("household_id", sa.UUID, primary_key=True),
    sa.Column("id", sa.UUID, primary_key=True),
)

companion_drafts = sa.Table(
    "companion_drafts",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("household_id", sa.UUID, nullable=False),
    sa.Column("member_id", sa.UUID, nullable=False),
    sa.Column("base_version", sa.Integer, nullable=False),
    sa.Column("base_hash", sa.Text, nullable=False),
    sa.Column("candidate", sa.Text, nullable=False),
    sa.Column("candidate_hash", sa.Text, nullable=False),
    sa.Column("sentence", sa.Text, nullable=False),
    sa.Column("review", JSONB, nullable=False),
    sa.Column("reviewed_session", sa.Text),
    sa.Column("status", sa.Text, nullable=False, server_default="ready"),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["household_id", "member_id"], ["members.household_id", "members.id"]
    ),
    sa.CheckConstraint(
        "status IN ('ready', 'dismissed', 'activated')", name="draft_status"
    ),
)


def upgrade() -> None:
    op.drop_constraint(
        "constitution_unvalidated_only", "constitution_versions", type_="check"
    )
    op.create_check_constraint(
        "constitution_status",
        "constitution_versions",
        "status IN ('unvalidated', 'active', 'superseded')",
    )
    op.create_check_constraint(
        "constitution_artifacts",
        "constitution_versions",
        "(status = 'unvalidated' AND compiled_cedar IS NULL AND activated_at IS NULL) OR (status IN ('active', 'superseded') AND compiled_cedar IS NOT NULL AND activated_at IS NOT NULL)",
    )
    op.create_index(
        "constitution_one_active",
        "constitution_versions",
        ["household_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    companion_drafts.create(op.get_bind())


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM constitution_versions WHERE status != 'unvalidated')"
        )
    ):
        raise ValueError("Activated policy history cannot be downgraded")
    companion_drafts.drop(op.get_bind())
    op.drop_index("constitution_one_active", table_name="constitution_versions")
    op.drop_constraint("constitution_artifacts", "constitution_versions", type_="check")
    op.drop_constraint("constitution_status", "constitution_versions", type_="check")
    op.create_check_constraint(
        "constitution_unvalidated_only",
        "constitution_versions",
        "status = 'unvalidated' AND compiled_cedar IS NULL AND activated_at IS NULL",
    )
