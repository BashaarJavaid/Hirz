"""Durable policy publication, engine readiness and Gateway sessions."""

from alembic import op
from hirz.db import gateway_sessions, policy_engines, policy_publications

revision = "0020_agentcore_policy"
down_revision = "0019_trusted_contacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in (policy_engines, policy_publications, gateway_sessions):
        table.create(op.get_bind())


def downgrade() -> None:
    for table in (gateway_sessions, policy_publications, policy_engines):
        table.drop(op.get_bind())
