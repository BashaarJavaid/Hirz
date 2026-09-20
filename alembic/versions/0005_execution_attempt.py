"""Durable local execution claims.

Revision ID: 0005_execution_attempt
Revises: 0004_observation_domains
"""

import sqlalchemy as sa

from alembic import op

revision = "0005_execution_attempt"
down_revision = "0004_observation_domains"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("actions", sa.Column("execution_attempt_seq", sa.BigInteger))
    op.create_foreign_key(
        "actions_execution_attempt_fk",
        "actions",
        "audit_log",
        ["household_id", "execution_attempt_seq"],
        ["household_id", "seq"],
    )


def downgrade() -> None:
    op.execute("LOCK TABLE actions, audit_log IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM actions WHERE execution_attempt_seq IS NOT NULL) "
            "OR EXISTS (SELECT 1 FROM audit_log WHERE event_type = 'EXECUTION_ATTEMPTED')"
        )
    ):
        raise RuntimeError("Execution-attempt evidence prevents downgrade")
    op.drop_constraint("actions_execution_attempt_fk", "actions", type_="foreignkey")
    op.drop_column("actions", "execution_attempt_seq")
