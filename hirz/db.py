"""SQLAlchemy Core schema and local async connections; no audit writer."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from hirz.local import LocalError

metadata = sa.MetaData()
households = sa.Table(
    "households",
    metadata,
    sa.Column("id", sa.UUID, primary_key=True),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("timezone", sa.Text, nullable=False),
    sa.Column("locale", sa.Text, nullable=False),
    sa.CheckConstraint("length(name) > 0", name="households_name_nonempty"),
    sa.CheckConstraint("length(timezone) > 0", name="households_timezone_nonempty"),
    sa.CheckConstraint("length(locale) > 0", name="households_locale_nonempty"),
)
members = sa.Table(
    "members",
    metadata,
    sa.Column(
        "household_id", sa.UUID, sa.ForeignKey("households.id"), primary_key=True
    ),
    sa.Column("id", sa.UUID, primary_key=True),
    sa.Column("display_name", sa.Text, nullable=False),
    sa.Column("role", sa.Text, nullable=False),
    sa.CheckConstraint(
        "length(display_name) > 0", name="members_display_name_nonempty"
    ),
    sa.CheckConstraint(
        "role IN ('owner', 'adult', 'teen', 'child', 'guest', 'caregiver')",
        name="members_role_allowed",
    ),
)
member_accounts = sa.Table(
    "member_accounts",
    metadata,
    sa.Column("household_id", sa.UUID, primary_key=True),
    sa.Column("provider", sa.Text, primary_key=True),
    sa.Column("sub", sa.Text, primary_key=True),
    sa.Column("member_id", sa.UUID, nullable=False),
    sa.ForeignKeyConstraint(
        ["household_id", "member_id"], ["members.household_id", "members.id"]
    ),
    sa.CheckConstraint(
        "length(provider) > 0", name="member_accounts_provider_nonempty"
    ),
    sa.CheckConstraint("length(sub) > 0", name="member_accounts_sub_nonempty"),
)
audit_log = sa.Table(
    "audit_log",
    metadata,
    sa.Column(
        "household_id", sa.UUID, sa.ForeignKey("households.id"), primary_key=True
    ),
    sa.Column("seq", sa.BigInteger, primary_key=True, autoincrement=False),
    sa.Column("event_type", sa.Text, nullable=False),
    sa.Column("payload", JSONB, nullable=False),
    sa.Column("prev_hash", sa.Text, nullable=False),
    sa.Column("curr_hash", sa.Text, nullable=False),
    sa.Column("key_fingerprint", sa.Text, nullable=False),
    sa.Column("signature", sa.LargeBinary, nullable=False),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.CheckConstraint("seq > 0", name="audit_log_seq_positive"),
    sa.CheckConstraint("length(event_type) > 0", name="audit_log_event_type_nonempty"),
    sa.CheckConstraint(
        "jsonb_typeof(payload) = 'object'", name="audit_log_payload_object"
    ),
    sa.CheckConstraint(
        "octet_length(signature) > 0", name="audit_log_signature_nonempty"
    ),
    *(
        sa.CheckConstraint(
            f"{column} ~ '^[0-9a-f]{{64}}$'", name=f"audit_log_{column}_hex"
        )
        for column in ("prev_hash", "curr_hash", "key_fingerprint")
    ),
)
audit_pointer = sa.Table(
    "audit_pointer",
    metadata,
    sa.Column(
        "household_id", sa.UUID, sa.ForeignKey("households.id"), primary_key=True
    ),
    sa.Column("seq", sa.BigInteger, nullable=False, server_default="0"),
    sa.Column("curr_hash", sa.Text, nullable=False, server_default="0" * 64),
    sa.CheckConstraint("seq >= 0", name="audit_pointer_seq_nonnegative"),
    sa.CheckConstraint(
        "curr_hash ~ '^[0-9a-f]{64}$'", name="audit_pointer_curr_hash_hex"
    ),
)


# Graph identities stay stable; mutable attributes have current and archived versions.
households.append_column(sa.Column("rate_plan", sa.Text))
households.append_column(sa.Column("constitution_version", sa.Integer))
households.append_constraint(
    sa.CheckConstraint(
        "rate_plan IS NULL OR rate_plan IN ('comed_time_of_day', 'comed_hourly', 'twin')",
        name="households_rate_plan_allowed",
    )
)


def graph_table(name: str, references: dict[str, str]) -> sa.Table:
    table = sa.Table(
        name,
        metadata,
        sa.Column(
            "household_id", sa.UUID, sa.ForeignKey("households.id"), primary_key=True
        ),
        sa.Column("id", sa.UUID, primary_key=True),
    )
    required = {
        "contact_channels": {"contact_id"},
        "asset_bindings": {"asset_id"},
        "asset_policies": {"asset_id"},
        "schedule_events": {"schedule_id"},
        "preferences": {"member_id"},
        "constraints": {"member_id", "asset_id"},
    }
    for column, target in references.items():
        table.append_column(
            sa.Column(column, sa.UUID, nullable=column not in required.get(name, set()))
        )
        table.append_constraint(
            sa.ForeignKeyConstraint(
                ["household_id", column],
                [f"{target}.household_id", f"{target}.id"],
            )
        )
    return table


trusted_contacts = graph_table("trusted_contacts", {"member_id": "members"})
contact_channels = graph_table("contact_channels", {"contact_id": "trusted_contacts"})
assets = graph_table("assets", {"owner_member_id": "members"})
asset_bindings = graph_table("asset_bindings", {"asset_id": "assets"})
asset_policies = graph_table("asset_policies", {"asset_id": "assets"})
schedules = graph_table("schedules", {"member_id": "members"})
schedule_events = graph_table(
    "schedule_events",
    {
        "schedule_id": "schedules",
        "member_id": "members",
        "zone_id": "assets",
    },
)
routines = graph_table("routines", {"member_id": "members"})
preferences = graph_table("preferences", {"member_id": "members"})
observations = graph_table(
    "observations", {"member_id": "members", "asset_id": "assets"}
)
observations.append_constraint(
    sa.CheckConstraint(
        "member_id IS NULL OR asset_id IS NULL",
        name="observations_one_subject",
    )
)
for name, table, columns, condition in (
    (
        "observations_member_unique",
        observations,
        ["household_id", "member_id"],
        "member_id IS NOT NULL",
    ),
    (
        "observations_asset_unique",
        observations,
        ["household_id", "asset_id"],
        "asset_id IS NOT NULL",
    ),
    (
        "observations_household_unique",
        observations,
        ["household_id"],
        "member_id IS NULL AND asset_id IS NULL",
    ),
):
    sa.Index(
        name,
        *(table.c[c] for c in columns),
        sa.text("COALESCE(attributes->>'domain', '')"),
        unique=True,
        postgresql_where=sa.text(condition),
    )
for table in (asset_bindings, asset_policies):
    table.append_constraint(sa.UniqueConstraint("household_id", "asset_id"))

constraints = graph_table("constraints", {"member_id": "members", "asset_id": "assets"})
for column in (
    "decision_seq",
    "recorded_seq",
    "withdrawn_seq",
    "withdrawal_decision_seq",
):
    constraints.append_column(
        sa.Column(column, sa.BigInteger, nullable=column.startswith("withdraw"))
    )
    constraints.append_constraint(
        sa.ForeignKeyConstraint(
            ["household_id", column], ["audit_log.household_id", "audit_log.seq"]
        )
    )

GRAPH_TABLES = {
    table.name: table
    for table in (
        households,
        members,
        member_accounts,
        trusted_contacts,
        contact_channels,
        assets,
        asset_bindings,
        asset_policies,
        schedules,
        schedule_events,
        routines,
        preferences,
        observations,
        constraints,
    )
}
HISTORY_TABLES: dict[str, sa.Table] = {}
for table in GRAPH_TABLES.values():
    table.append_column(
        sa.Column(
            "attributes", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        )
    )
    table.append_column(
        sa.Column(
            "valid_from",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        )
    )
    table.append_column(sa.Column("valid_to", sa.DateTime(timezone=True)))
    table.append_constraint(
        sa.CheckConstraint("valid_to IS NULL", name=f"{table.name}_current_open")
    )
    table.append_constraint(
        sa.CheckConstraint(
            "jsonb_typeof(attributes) = 'object'",
            name=f"{table.name}_attributes_object",
        )
    )
    history_name = (
        "observation_history" if table is observations else table.name + "_history"
    )
    history = sa.Table(
        history_name,
        metadata,
        *(
            sa.Column(
                column.name,
                column.type,
                primary_key=column.primary_key or column.name == "valid_from",
                nullable=False if column.name == "valid_to" else column.nullable,
            )
            for column in table.columns
        ),
        sa.CheckConstraint("valid_to > valid_from", name=f"{history_name}_interval"),
    )
    HISTORY_TABLES[table.name] = history

constitution_versions = sa.Table(
    "constitution_versions",
    metadata,
    sa.Column(
        "household_id", sa.UUID, sa.ForeignKey("households.id"), primary_key=True
    ),
    sa.Column("version", sa.Integer, primary_key=True),
    sa.Column("yaml", sa.Text, nullable=False),
    sa.Column("hash", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False, server_default="unvalidated"),
    sa.Column("compiled_cedar", sa.Text),
    sa.Column("analysis_report", JSONB),
    sa.Column("activated_at", sa.DateTime(timezone=True)),
    sa.CheckConstraint("version > 0", name="constitution_version_positive"),
    sa.CheckConstraint("hash ~ '^[0-9a-f]{64}$'", name="constitution_hash_hex"),
    sa.CheckConstraint(
        "status = 'unvalidated' AND compiled_cedar IS NULL AND activated_at IS NULL",
        name="constitution_unvalidated_only",
    ),
)
households.append_constraint(
    sa.ForeignKeyConstraint(
        ["id", "constitution_version"],
        ["constitution_versions.household_id", "constitution_versions.version"],
        name="households_constitution_version_fk",
        use_alter=True,
        deferrable=True,
        initially="DEFERRED",
    )
)


def database_url(values: dict[str, str]) -> sa.URL:
    password = values.get("POSTGRES_PASSWORD")
    if not password:
        raise LocalError("POSTGRES_PASSWORD is missing; restore .env.")
    return sa.URL.create(
        "postgresql+psycopg",
        username="hirz",
        password=password,
        host="127.0.0.1",
        port=5432,
        database="hirz",
    )


@asynccontextmanager
async def connect_database(
    values: dict[str, str], *, database: str = "hirz"
) -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(
        database_url(values).set(database=database),
        poolclass=sa.pool.NullPool,
        connect_args={"connect_timeout": 10},
        hide_parameters=True,
    )
    try:
        async with engine.connect() as connection:
            yield connection
    finally:
        await engine.dispose()


def migration_config() -> Config:
    return Config("alembic.ini")


def require_current(connection: sa.Connection) -> None:
    heads = ScriptDirectory.from_config(migration_config()).get_heads()
    current = MigrationContext.configure(connection).get_current_heads()
    tables = set(sa.inspect(connection).get_table_names())
    if (
        len(heads) != 1
        or set(current) != set(heads)
        or not metadata.tables.keys() <= tables
        or "household_context"
        not in sa.inspect(connection).get_materialized_view_names()
    ):
        raise LocalError(
            "Migrations are missing, inconsistent, or behind; "
            "run uv run alembic upgrade head from the checkout root."
        )


def require_empty_audit(connection: sa.Connection) -> None:
    tables = set(sa.inspect(connection).get_table_names())
    if not tables:
        return
    require_current(connection)
    context = MigrationContext.configure(
        connection, opts={"compare_server_default": True}
    )
    if compare_metadata(context, metadata):
        raise LocalError(
            "Schema is inconsistent; restore the database before key setup."
        )
    if connection.scalar(sa.select(sa.exists().select_from(audit_log))):
        raise LocalError("Audit rows exist; restore the original AUDIT_SIGNING_KEY.")


# Item 9 stores proposals and votes; Decisions and reservations live in audit_log.
actions = sa.Table(
    "actions",
    metadata,
    sa.Column(
        "household_id", sa.UUID, sa.ForeignKey("households.id"), primary_key=True
    ),
    sa.Column("action_id", sa.Text, primary_key=True),
    sa.Column("proposal", JSONB, nullable=False),
    sa.Column("principal", JSONB, nullable=False),
    sa.Column("cost", sa.Text),
    sa.Column("grant_seq", sa.BigInteger),
    sa.Column("execution_attempt_seq", sa.BigInteger),
    sa.Column("lifecycle", JSONB),
    sa.Column("due_at", sa.DateTime(timezone=True)),
    sa.Column("execution_status", sa.Text),
    sa.Column("lifecycle_seq", sa.BigInteger),
    sa.ForeignKeyConstraint(
        ["household_id", "lifecycle_seq"],
        ["audit_log.household_id", "audit_log.seq"],
        name="actions_lifecycle_fk",
    ),
    sa.ForeignKeyConstraint(
        ["household_id", "execution_attempt_seq"],
        ["audit_log.household_id", "audit_log.seq"],
        name="actions_execution_attempt_fk",
    ),
    sa.ForeignKeyConstraint(
        ["household_id", "grant_seq"], ["audit_log.household_id", "audit_log.seq"]
    ),
    sa.CheckConstraint(
        "execution_status IS NULL OR execution_status IN ('scheduled','executing','dispatched','verified','failed','held','cancelled','skipped')",
        name="actions_execution_status",
    ),
    sa.CheckConstraint(
        "lifecycle IS NULL OR (jsonb_typeof(lifecycle) = 'object' AND due_at IS NOT NULL AND execution_status IS NOT NULL)",
        name="actions_lifecycle_object",
    ),
    sa.CheckConstraint("length(action_id) > 0", name="actions_id_nonempty"),
    sa.CheckConstraint(
        "jsonb_typeof(proposal) = 'object' AND jsonb_typeof(principal) = 'object'",
        name="actions_objects",
    ),
    sa.CheckConstraint(
        "cost IS NULL OR cost ~ '^[0-9]+([.][0-9]+)?$'", name="actions_cost_nonnegative"
    ),
)
approvals = sa.Table(
    "approvals",
    metadata,
    sa.Column("household_id", sa.UUID, primary_key=True),
    sa.Column("approval_id", sa.Text, primary_key=True),
    sa.Column("action_id", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("binding", JSONB, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["household_id", "action_id"], ["actions.household_id", "actions.action_id"]
    ),
    sa.CheckConstraint(
        "approval_id ~ '^apr_[0-9a-f]{32}$'", name="approvals_id_format"
    ),
    sa.CheckConstraint(
        "status IN ('pending','approved','rejected','expired','redeemed')",
        name="approvals_status",
    ),
    sa.CheckConstraint("expires_at > created_at", name="approvals_ttl"),
)
sa.Index(
    "approvals_one_pending",
    approvals.c.household_id,
    approvals.c.action_id,
    unique=True,
    postgresql_where=sa.text("status IN ('pending', 'approved')"),
)
approval_votes = sa.Table(
    "approval_votes",
    metadata,
    sa.Column("household_id", sa.UUID, primary_key=True),
    sa.Column("approval_id", sa.Text, primary_key=True),
    sa.Column("member_id", sa.UUID, primary_key=True),
    sa.Column("approved", sa.Boolean, nullable=False),
    sa.Column("principal", JSONB, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["household_id", "approval_id"],
        ["approvals.household_id", "approvals.approval_id"],
    ),
    sa.ForeignKeyConstraint(
        ["household_id", "member_id"], ["members.household_id", "members.id"]
    ),
)


# Canonical plans and local recovery records; all references are household scoped.
plans = sa.Table(
    "plans",
    metadata,
    sa.Column(
        "household_id", sa.UUID, sa.ForeignKey("households.id"), primary_key=True
    ),
    sa.Column("plan_id", sa.Text, primary_key=True),
    sa.Column("document", JSONB, nullable=False),
    sa.Column("runtime", JSONB),
    sa.Column("reservation", JSONB),
    sa.Column("requester", JSONB),
    sa.Column("lineage_id", sa.Text),
    sa.Column("accepted_at", sa.DateTime(timezone=True)),
    sa.Column("approver", JSONB),
    sa.Column("member_id", sa.UUID),
    sa.Column("audit_seq", sa.BigInteger, nullable=False),
    sa.ForeignKeyConstraint(
        ["household_id", "member_id"], ["members.household_id", "members.id"]
    ),
    sa.ForeignKeyConstraint(
        ["household_id", "audit_seq"], ["audit_log.household_id", "audit_log.seq"]
    ),
)
plan_refresh_jobs = sa.Table(
    "plan_refresh_jobs",
    metadata,
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
    sa.CheckConstraint("state IN ('queued','running','blocked','idle','cancelled')"),
    sa.CheckConstraint("requested_generation >= 0 AND attempts >= 0"),
)
plan_actions = sa.Table(
    "plan_actions",
    metadata,
    sa.Column("household_id", sa.UUID, primary_key=True),
    sa.Column("plan_id", sa.Text, primary_key=True),
    sa.Column("action_id", sa.Text, primary_key=True),
    sa.ForeignKeyConstraint(
        ["household_id", "plan_id"], ["plans.household_id", "plans.plan_id"]
    ),
    sa.ForeignKeyConstraint(
        ["household_id", "action_id"], ["actions.household_id", "actions.action_id"]
    ),
)
pending_notifications = sa.Table(
    "pending_notifications",
    metadata,
    sa.Column("household_id", sa.UUID, primary_key=True),
    sa.Column("audit_seq", sa.BigInteger, primary_key=True),
    sa.Column("member_id", sa.UUID, nullable=False),
    sa.Column("message", sa.Text, nullable=False),
    sa.ForeignKeyConstraint(
        ["household_id", "member_id"], ["members.household_id", "members.id"]
    ),
    sa.ForeignKeyConstraint(
        ["household_id", "audit_seq"], ["audit_log.household_id", "audit_log.seq"]
    ),
)
twin_checkpoints = sa.Table(
    "twin_checkpoints",
    metadata,
    sa.Column(
        "household_id", sa.UUID, sa.ForeignKey("households.id"), primary_key=True
    ),
    sa.Column("config_hash", sa.Text, nullable=False),
    sa.Column("state", JSONB, nullable=False),
    sa.Column("at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("audit_seq", sa.BigInteger, nullable=False),
    sa.ForeignKeyConstraint(
        ["household_id", "audit_seq"], ["audit_log.household_id", "audit_log.seq"]
    ),
)
