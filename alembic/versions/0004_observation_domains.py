"""Keep independent observation domains without rewriting graph history."""

import sqlalchemy as sa

from alembic import op

revision = "0004_observation_domains"
down_revision = "0003_pipeline"
branch_labels = None
depends_on = None

INDEXES = (
    (
        "observations_member_unique",
        ["household_id", "member_id"],
        "member_id IS NOT NULL",
    ),
    ("observations_asset_unique", ["household_id", "asset_id"], "asset_id IS NOT NULL"),
    (
        "observations_household_unique",
        ["household_id"],
        "member_id IS NULL AND asset_id IS NULL",
    ),
)


def indexes(*, domains: bool) -> None:
    for name, columns, condition in INDEXES:
        op.drop_index(name, table_name="observations")
        op.create_index(
            name,
            "observations",
            [*columns, sa.text("COALESCE(attributes->>'domain', '')")]
            if domains
            else columns,
            unique=True,
            postgresql_where=sa.text(condition),
        )


def upgrade() -> None:
    indexes(domains=True)


def downgrade() -> None:
    tagged = op.get_bind().scalar(
        sa.text("""
        SELECT EXISTS (
            SELECT 1 FROM observations WHERE attributes->>'domain' IS NOT NULL
            UNION ALL
            SELECT 1 FROM observation_history WHERE attributes->>'domain' IS NOT NULL
        )
    """)
    )
    if tagged:
        raise ValueError(
            "Cannot downgrade tagged observation data; history is preserved."
        )
    indexes(domains=False)
