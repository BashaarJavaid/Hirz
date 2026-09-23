"""Audited constraint history; downgrade refuses evidence loss."""

import sqlalchemy as sa

from alembic import op

revision = "0006_coordinator_constraints"
down_revision = "0005_execution_attempt"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "\nCREATE TABLE constraints (\n\thousehold_id UUID NOT NULL, \n\tid UUID NOT NULL, \n\tmember_id UUID NOT NULL, \n\tasset_id UUID NOT NULL, \n\tdecision_seq BIGINT NOT NULL, \n\trecorded_seq BIGINT NOT NULL, \n\twithdrawn_seq BIGINT, \n\twithdrawal_decision_seq BIGINT, \n\tattributes JSONB DEFAULT '{}'::jsonb NOT NULL, \n\tvalid_from TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tvalid_to TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY (household_id, id), \n\tFOREIGN KEY(household_id) REFERENCES households (id), \n\tFOREIGN KEY(household_id, member_id) REFERENCES members (household_id, id), \n\tFOREIGN KEY(household_id, asset_id) REFERENCES assets (household_id, id), \n\tFOREIGN KEY(household_id, decision_seq) REFERENCES audit_log (household_id, seq), \n\tFOREIGN KEY(household_id, recorded_seq) REFERENCES audit_log (household_id, seq), \n\tFOREIGN KEY(household_id, withdrawn_seq) REFERENCES audit_log (household_id, seq), \n\tFOREIGN KEY(household_id, withdrawal_decision_seq) REFERENCES audit_log (household_id, seq), \n\tCONSTRAINT constraints_current_open CHECK (valid_to IS NULL), \n\tCONSTRAINT constraints_attributes_object CHECK (jsonb_typeof(attributes) = 'object')\n)\n\n"
    )
    op.execute(
        "\nCREATE TABLE constraints_history (\n\thousehold_id UUID NOT NULL, \n\tid UUID NOT NULL, \n\tmember_id UUID NOT NULL, \n\tasset_id UUID NOT NULL, \n\tdecision_seq BIGINT NOT NULL, \n\trecorded_seq BIGINT NOT NULL, \n\twithdrawn_seq BIGINT, \n\twithdrawal_decision_seq BIGINT, \n\tattributes JSONB NOT NULL, \n\tvalid_from TIMESTAMP WITH TIME ZONE NOT NULL, \n\tvalid_to TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (household_id, id, valid_from), \n\tCONSTRAINT constraints_history_interval CHECK (valid_to > valid_from)\n)\n\n"
    )
    op.execute("DROP MATERIALIZED VIEW household_context")
    op.execute(
        "CREATE MATERIALIZED VIEW household_context AS  SELECT h.id AS household_id, jsonb_build_object('households', COALESCE((SELECT jsonb_agg(((to_jsonb(x) - 'attributes') || x.attributes) - 'safe_word_hash' - 'value_hash' ORDER BY x.id)\n            FROM households x WHERE x.id = h.id), '[]'::jsonb), 'members', COALESCE((SELECT jsonb_agg(((to_jsonb(x) - 'attributes') || x.attributes) - 'safe_word_hash' - 'value_hash' ORDER BY x.household_id, x.id)\n            FROM members x WHERE x.household_id = h.id), '[]'::jsonb), 'trusted_contacts', COALESCE((SELECT jsonb_agg(((to_jsonb(x) - 'attributes') || x.attributes) - 'safe_word_hash' - 'value_hash' ORDER BY x.household_id, x.id)\n            FROM trusted_contacts x WHERE x.household_id = h.id), '[]'::jsonb), 'contact_channels', COALESCE((SELECT jsonb_agg(((to_jsonb(x) - 'attributes') || x.attributes) - 'safe_word_hash' - 'value_hash' ORDER BY x.household_id, x.id)\n            FROM contact_channels x WHERE x.household_id = h.id), '[]'::jsonb), 'assets', COALESCE((SELECT jsonb_agg(((to_jsonb(x) - 'attributes') || x.attributes) - 'safe_word_hash' - 'value_hash' ORDER BY x.household_id, x.id)\n            FROM assets x WHERE x.household_id = h.id), '[]'::jsonb), 'asset_bindings', COALESCE((SELECT jsonb_agg(((to_jsonb(x) - 'attributes') || x.attributes) - 'safe_word_hash' - 'value_hash' ORDER BY x.household_id, x.id)\n            FROM asset_bindings x WHERE x.household_id = h.id), '[]'::jsonb), 'asset_policies', COALESCE((SELECT jsonb_agg(((to_jsonb(x) - 'attributes') || x.attributes) - 'safe_word_hash' - 'value_hash' ORDER BY x.household_id, x.id)\n            FROM asset_policies x WHERE x.household_id = h.id), '[]'::jsonb), 'schedules', COALESCE((SELECT jsonb_agg(((to_jsonb(x) - 'attributes') || x.attributes) - 'safe_word_hash' - 'value_hash' ORDER BY x.household_id, x.id)\n            FROM schedules x WHERE x.household_id = h.id), '[]'::jsonb), 'schedule_events', COALESCE((SELECT jsonb_agg(((to_jsonb(x) - 'attributes') || x.attributes) - 'safe_word_hash' - 'value_hash' ORDER BY x.household_id, x.id)\n            FROM schedule_events x WHERE x.household_id = h.id), '[]'::jsonb), 'routines', COALESCE((SELECT jsonb_agg(((to_jsonb(x) - 'attributes') || x.attributes) - 'safe_word_hash' - 'value_hash' ORDER BY x.household_id, x.id)\n            FROM routines x WHERE x.household_id = h.id), '[]'::jsonb), 'preferences', COALESCE((SELECT jsonb_agg(((to_jsonb(x) - 'attributes') || x.attributes) - 'safe_word_hash' - 'value_hash' ORDER BY x.household_id, x.id)\n            FROM preferences x WHERE x.household_id = h.id), '[]'::jsonb), 'observations', COALESCE((SELECT jsonb_agg(((to_jsonb(x) - 'attributes') || x.attributes) - 'safe_word_hash' - 'value_hash' ORDER BY x.household_id, x.id)\n            FROM observations x WHERE x.household_id = h.id), '[]'::jsonb), 'constraints', COALESCE((SELECT jsonb_agg(((to_jsonb(x) - 'attributes') || x.attributes) - 'safe_word_hash' - 'value_hash' ORDER BY x.household_id, x.id)\n            FROM constraints x WHERE x.household_id = h.id), '[]'::jsonb)) AS data FROM households h"
    )
    op.execute(
        "CREATE UNIQUE INDEX household_context_household_id ON household_context (household_id)"
    )


def downgrade() -> None:
    op.execute(
        "LOCK TABLE constraints, constraints_history, audit_log IN ACCESS EXCLUSIVE MODE"
    )
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM constraints) OR EXISTS (SELECT 1 FROM constraints_history) OR EXISTS (SELECT 1 FROM audit_log WHERE event_type IN ('CONSTRAINT_RECORDED', 'CONSTRAINT_WITHDRAWN'))"
        )
    ):
        raise RuntimeError("Constraint evidence prevents downgrade")
    op.execute("DROP MATERIALIZED VIEW household_context")
    op.execute(
        "CREATE MATERIALIZED VIEW household_context AS  SELECT h.id AS household_id, jsonb_build_object('households', COALESCE((SELECT jsonb_agg(((to_jsonb(x) - 'attributes') || x.attributes) - 'safe_word_hash' - 'value_hash' ORDER BY x.id)\n            FROM households x WHERE x.id = h.id), '[]'::jsonb), 'members', COALESCE((SELECT jsonb_agg(((to_jsonb(x) - 'attributes') || x.attributes) - 'safe_word_hash' - 'value_hash' ORDER BY x.household_id, x.id)\n            FROM members x WHERE x.household_id = h.id), '[]'::jsonb), 'trusted_contacts', COALESCE((SELECT jsonb_agg(((to_jsonb(x) - 'attributes') || x.attributes) - 'safe_word_hash' - 'value_hash' ORDER BY x.household_id, x.id)\n            FROM trusted_contacts x WHERE x.household_id = h.id), '[]'::jsonb), 'contact_channels', COALESCE((SELECT jsonb_agg(((to_jsonb(x) - 'attributes') || x.attributes) - 'safe_word_hash' - 'value_hash' ORDER BY x.household_id, x.id)\n            FROM contact_channels x WHERE x.household_id = h.id), '[]'::jsonb), 'assets', COALESCE((SELECT jsonb_agg(((to_jsonb(x) - 'attributes') || x.attributes) - 'safe_word_hash' - 'value_hash' ORDER BY x.household_id, x.id)\n            FROM assets x WHERE x.household_id = h.id), '[]'::jsonb), 'asset_bindings', COALESCE((SELECT jsonb_agg(((to_jsonb(x) - 'attributes') || x.attributes) - 'safe_word_hash' - 'value_hash' ORDER BY x.household_id, x.id)\n            FROM asset_bindings x WHERE x.household_id = h.id), '[]'::jsonb), 'asset_policies', COALESCE((SELECT jsonb_agg(((to_jsonb(x) - 'attributes') || x.attributes) - 'safe_word_hash' - 'value_hash' ORDER BY x.household_id, x.id)\n            FROM asset_policies x WHERE x.household_id = h.id), '[]'::jsonb), 'schedules', COALESCE((SELECT jsonb_agg(((to_jsonb(x) - 'attributes') || x.attributes) - 'safe_word_hash' - 'value_hash' ORDER BY x.household_id, x.id)\n            FROM schedules x WHERE x.household_id = h.id), '[]'::jsonb), 'schedule_events', COALESCE((SELECT jsonb_agg(((to_jsonb(x) - 'attributes') || x.attributes) - 'safe_word_hash' - 'value_hash' ORDER BY x.household_id, x.id)\n            FROM schedule_events x WHERE x.household_id = h.id), '[]'::jsonb), 'routines', COALESCE((SELECT jsonb_agg(((to_jsonb(x) - 'attributes') || x.attributes) - 'safe_word_hash' - 'value_hash' ORDER BY x.household_id, x.id)\n            FROM routines x WHERE x.household_id = h.id), '[]'::jsonb), 'preferences', COALESCE((SELECT jsonb_agg(((to_jsonb(x) - 'attributes') || x.attributes) - 'safe_word_hash' - 'value_hash' ORDER BY x.household_id, x.id)\n            FROM preferences x WHERE x.household_id = h.id), '[]'::jsonb), 'observations', COALESCE((SELECT jsonb_agg(((to_jsonb(x) - 'attributes') || x.attributes) - 'safe_word_hash' - 'value_hash' ORDER BY x.household_id, x.id)\n            FROM observations x WHERE x.household_id = h.id), '[]'::jsonb)) AS data FROM households h"
    )
    op.execute(
        "CREATE UNIQUE INDEX household_context_household_id ON household_context (household_id)"
    )
    op.drop_table("constraints_history")
    op.drop_table("constraints")
