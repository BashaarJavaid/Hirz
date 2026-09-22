"""Durable refresh lineage and inputs; preserve legacy plans and signed evidence."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0008_plan_refresh"
down_revision = "0007_execution_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name, kind in (
        ("runtime", JSONB),
        ("reservation", JSONB),
        ("requester", JSONB),
        ("lineage_id", sa.Text),
        ("accepted_at", sa.DateTime(timezone=True)),
    ):
        op.add_column("plans", sa.Column(name, kind))
    op.create_table(
        "plan_refresh_jobs",
        sa.Column("household_id", sa.UUID, primary_key=True),
        sa.Column("lineage_id", sa.Text, primary_key=True),
        sa.Column("plan_id", sa.Text, nullable=False),
        sa.Column("state", sa.Text, nullable=False),
        sa.Column("requested_generation", sa.BigInteger, nullable=False),
        sa.Column("running_generation", sa.BigInteger),
        sa.Column("reasons", JSONB, nullable=False),
        sa.Column("explicit", sa.Boolean, nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("next_retry", sa.DateTime(timezone=True)),
        sa.Column("blocking_reason", sa.Text),
        sa.Column("fingerprint", JSONB, nullable=False),
        sa.Column("audit_seq", sa.BigInteger, nullable=False),
        sa.ForeignKeyConstraint(
            ["household_id", "plan_id"], ["plans.household_id", "plans.plan_id"]
        ),
        sa.ForeignKeyConstraint(
            ["household_id", "audit_seq"], ["audit_log.household_id", "audit_log.seq"]
        ),
        sa.CheckConstraint(
            "state IN ('queued','running','blocked','idle','cancelled')"
        ),
        sa.CheckConstraint("requested_generation >= 0 AND attempts >= 0"),
    )


def downgrade() -> None:
    op.execute(
        "LOCK TABLE plans, plan_refresh_jobs, audit_log IN ACCESS EXCLUSIVE MODE"
    )
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM plans WHERE runtime IS NOT NULL) OR EXISTS (SELECT 1 FROM plan_refresh_jobs) OR EXISTS (SELECT 1 FROM audit_log WHERE event_type IN ('PLAN_REFRESH','RESERVATION_ADJUSTED'))"
        )
    ):
        raise RuntimeError("Plan refresh evidence prevents downgrade")
    op.drop_table("plan_refresh_jobs")
    for name in ("runtime", "reservation", "requester", "lineage_id", "accepted_at"):
        op.drop_column("plans", name)
