"""Durable voice proposal lifecycle; candidate drafts remain separate."""

import sqlalchemy as sa

from alembic import op

revision = "0017_rule_drafting"
down_revision = "0016_companion_push"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rule_proposals",
        sa.Column("status", sa.Text, nullable=False, server_default="queued"),
    )
    op.add_column(
        "rule_proposals",
        sa.Column(
            "draft_id",
            sa.Text,
            sa.ForeignKey("companion_drafts.id", name="proposal_draft_fk"),
        ),
    )
    op.add_column("rule_proposals", sa.Column("failure", sa.Text))
    op.create_check_constraint(
        "proposal_status",
        "rule_proposals",
        "status IN ('queued','ready','failed','dismissed','activated')",
    )


def downgrade() -> None:
    op.drop_constraint("proposal_status", "rule_proposals", type_="check")
    op.drop_column("rule_proposals", "failure")
    op.drop_column("rule_proposals", "draft_id")
    op.drop_column("rule_proposals", "status")
