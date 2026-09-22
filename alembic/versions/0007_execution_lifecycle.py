"""Durable local execution, plans, pending notices and twin checkpoints."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0007_execution_lifecycle"
down_revision = "0006_coordinator_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("actions", sa.Column("lifecycle", JSONB))
    op.add_column("actions", sa.Column("due_at", sa.DateTime(timezone=True)))
    op.add_column("actions", sa.Column("execution_status", sa.Text))
    op.add_column("actions", sa.Column("lifecycle_seq", sa.BigInteger))
    op.create_foreign_key(
        "actions_lifecycle_fk",
        "actions",
        "audit_log",
        ["household_id", "lifecycle_seq"],
        ["household_id", "seq"],
    )
    op.execute(
        "\nCREATE TABLE plans (\n\thousehold_id UUID NOT NULL, \n\tplan_id TEXT NOT NULL, \n\tdocument JSONB NOT NULL, \n\tapprover JSONB, \n\tmember_id UUID, \n\taudit_seq BIGINT NOT NULL, \n\tPRIMARY KEY (household_id, plan_id), \n\tFOREIGN KEY(household_id, member_id) REFERENCES members (household_id, id), \n\tFOREIGN KEY(household_id, audit_seq) REFERENCES audit_log (household_id, seq), \n\tFOREIGN KEY(household_id) REFERENCES households (id)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE plan_actions (\n\thousehold_id UUID NOT NULL, \n\tplan_id TEXT NOT NULL, \n\taction_id TEXT NOT NULL, \n\tPRIMARY KEY (household_id, plan_id, action_id), \n\tFOREIGN KEY(household_id, plan_id) REFERENCES plans (household_id, plan_id), \n\tFOREIGN KEY(household_id, action_id) REFERENCES actions (household_id, action_id)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE pending_notifications (\n\thousehold_id UUID NOT NULL, \n\taudit_seq BIGINT NOT NULL, \n\tmember_id UUID NOT NULL, \n\tmessage TEXT NOT NULL, \n\tPRIMARY KEY (household_id, audit_seq), \n\tFOREIGN KEY(household_id, member_id) REFERENCES members (household_id, id), \n\tFOREIGN KEY(household_id, audit_seq) REFERENCES audit_log (household_id, seq)\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE twin_checkpoints (\n\thousehold_id UUID NOT NULL, \n\tconfig_hash TEXT NOT NULL, \n\tstate JSONB NOT NULL, \n\tat TIMESTAMP WITH TIME ZONE NOT NULL, \n\taudit_seq BIGINT NOT NULL, \n\tPRIMARY KEY (household_id), \n\tFOREIGN KEY(household_id, audit_seq) REFERENCES audit_log (household_id, seq), \n\tFOREIGN KEY(household_id) REFERENCES households (id)\n)\n\n"
    )
    op.create_check_constraint(
        "actions_execution_status",
        "actions",
        "execution_status IS NULL OR execution_status IN ('scheduled','executing','dispatched','verified','failed','held','cancelled','skipped')",
    )
    op.create_check_constraint(
        "actions_lifecycle_object",
        "actions",
        "lifecycle IS NULL OR (jsonb_typeof(lifecycle) = 'object' AND due_at IS NOT NULL AND execution_status IS NOT NULL)",
    )


def downgrade() -> None:
    op.execute(
        "LOCK TABLE actions, plans, plan_actions, pending_notifications, twin_checkpoints, audit_log IN ACCESS EXCLUSIVE MODE"
    )
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM actions WHERE lifecycle IS NOT NULL) OR EXISTS (SELECT 1 FROM plans) OR EXISTS (SELECT 1 FROM pending_notifications) OR EXISTS (SELECT 1 FROM twin_checkpoints) OR EXISTS (SELECT 1 FROM audit_log WHERE event_type IN ('TWIN_CHECKPOINT','EXECUTION_HELD','EXECUTION_CANCELLED','SCHEDULED','ENDING_AUTHORIZED','PLAN_CREATED','PLAN_APPROVED','PLAN_REVISED','PLAN_CANCELLED','OBSERVATIONS_RECORDED','NOTICE_PENDING'))"
        )
    ):
        raise RuntimeError("Execution lifecycle evidence prevents downgrade")
    for table in ("twin_checkpoints", "pending_notifications", "plan_actions", "plans"):
        op.drop_table(table)
    op.drop_constraint("actions_execution_status", "actions", type_="check")
    op.drop_constraint("actions_lifecycle_object", "actions", type_="check")
    op.drop_constraint("actions_lifecycle_fk", "actions", type_="foreignkey")
    for column in ("lifecycle", "due_at", "execution_status", "lifecycle_seq"):
        op.drop_column("actions", column)
