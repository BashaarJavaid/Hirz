"""Private graph persistence. Only demo bootstrap/tests write before items 9–10."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from hirz import db
from hirz.graph.models import (
    MODELS,
    Asset,
    ContactChannel,
    GraphError,
    Model,
    Observation,
    now,
    utc,
    validate_observation_scope,
)


# Every interpolated identifier below comes from this module's closed table mapping.
def snapshot_sql(*, historical: bool = False, private: bool = False) -> str:
    ctes = []
    if historical:
        for name, table in db.GRAPH_TABLES.items():
            columns = ", ".join(table.c.keys())
            history = db.HISTORY_TABLES[name].name
            ctes.append(f"""{name}_at AS (
                SELECT {columns} FROM {name}
                WHERE valid_from <= :as_of
                UNION ALL SELECT {columns} FROM {history}
                WHERE valid_from <= :as_of AND :as_of < valid_to
            )""")
    pairs = []
    for name, table in db.GRAPH_TABLES.items():
        if name == "member_accounts" and not private:
            continue
        source = name + "_at" if historical else name
        scope_column = "id" if name == "households" else "household_id"
        projection = "(to_jsonb(x) - 'attributes') || x.attributes"
        if not private:
            # Strip after merging so JSONB cannot smuggle private fields back in.
            projection = f"({projection}) - 'safe_word_hash' - 'value_hash'"
        order = ", ".join("x." + c.name for c in table.primary_key)
        pairs.append(f"""'{name}', COALESCE((SELECT jsonb_agg({projection} ORDER BY {order})
            FROM {source} x WHERE x.{scope_column} = h.id), '[]'::jsonb)""")
    source = "households_at" if historical else "households"
    prefix = "WITH " + ", ".join(ctes) if ctes else ""
    return f"{prefix} SELECT h.id AS household_id, jsonb_build_object({', '.join(pairs)}) AS data FROM {source} h"


def row_values(name: str, model: Model) -> dict[str, Any]:
    table = db.GRAPH_TABLES[name]
    native = model.model_dump(mode="python")
    serialized = model.model_dump(mode="json", exclude_none=True)
    values = {key: value for key, value in native.items() if key in table.c}
    values["attributes"] = {
        key: value for key, value in serialized.items() if key not in table.c
    }
    return values


def row_model(name: str, row: dict[str, Any]) -> Model:
    values = {
        key: value
        for key, value in row.items()
        if key not in {"attributes", "valid_from", "valid_to"}
    }
    return MODELS[name].model_validate(values | row.get("attributes", {}))


class GraphRepository:
    def __init__(self, connection: AsyncConnection, household_id: UUID):
        self.connection = connection
        self.household_id = household_id
        self._at: datetime | None = None
        self._changed = False
        self._revision = 0

    @asynccontextmanager
    async def write(self, clock: Callable[[], datetime] = now) -> AsyncIterator[None]:
        """Own one transaction; a connection with an existing transaction is refused."""
        if self._at is not None:
            raise GraphError("Nested graph writes are not supported.")
        async with self.connection.begin():
            # Two-key locks do not overlap the workers' one-key session locks.
            await self.connection.execute(
                sa.text("SELECT pg_advisory_xact_lock(:namespace, :household_key)"),
                {
                    "namespace": 1,
                    "household_key": int.from_bytes(
                        self.household_id.bytes[:4], "big", signed=True
                    ),
                },
            )
            self._at = utc(clock())
            self._revision += 1
            self._changed = False
            try:
                yield
                if self._changed:
                    # ponytail: whole-view refresh measured 5.4 ms warm / 14.2 ms
                    # first call with one home; grows with household count. Item 38c
                    # must re-measure many throwaway homes and use per-home
                    # projections if the item 26 latency budget is exceeded.
                    await self.connection.execute(
                        sa.text("REFRESH MATERIALIZED VIEW household_context")
                    )
            finally:
                self._at = None
                self._revision += 1
                self._changed = False

    def _where(self, name: str, key: dict[str, Any]) -> sa.ColumnElement[bool]:
        table = db.GRAPH_TABLES[name]
        scoped = "id" if name == "households" else "household_id"
        allowed = {c.name for c in table.primary_key} - {scoped}
        if set(key) != allowed:
            raise GraphError("An exact entity key is required.")
        return sa.and_(
            table.c[scoped] == self.household_id,
            *(table.c[k] == v for k, v in key.items()),
        )

    async def get(
        self,
        name: str,
        key: dict[str, Any],
        *,
        as_of: datetime | None = None,
        clock: Callable[[], datetime] = now,
    ) -> dict[str, Any] | None:
        if name not in MODELS:
            raise GraphError("Unknown graph entity.")
        table = db.GRAPH_TABLES[name]
        where = self._where(name, key)
        query = sa.select(table).where(where)
        statement: sa.Select[Any] | sa.CompoundSelect[Any]
        if as_of is not None:
            at = utc(as_of)
            if at > utc(clock()):
                raise GraphError("Future historical reads are not supported.")
            history = db.HISTORY_TABLES[name]
            scoped = "id" if name == "households" else "household_id"
            past = sa.select(history).where(
                history.c[scoped] == self.household_id,
                *(history.c[k] == v for k, v in key.items()),
                history.c.valid_from <= at,
                history.c.valid_to > at,
            )
            statement = query.where(table.c.valid_from <= at).union_all(past)
        else:
            statement = query
        row = (await self.connection.execute(statement)).mappings().one_or_none()
        return dict(row) if row is not None else None

    async def put(
        self, name: str, model: Model, *, expected_version: datetime | None = None
    ) -> bool:
        if self._at is None:
            raise GraphError("Graph writes require a graph transaction.")
        if name not in MODELS or type(model) is not MODELS[name]:
            raise GraphError("Wrong graph model.")
        # Revalidate even model_construct/model_copy inputs, including nested state.
        model = MODELS[name].model_validate(model.model_dump(mode="python"))
        if isinstance(model, Observation) and model.domain is None:
            raise GraphError("New observation writes require a domain.")
        values = row_values(name, model)
        scoped = "id" if name == "households" else "household_id"
        if values[scoped] != self.household_id:
            raise GraphError("Entity does not belong to this household.")
        table = db.GRAPH_TABLES[name]
        key = {c.name: values[c.name] for c in table.primary_key if c.name != scoped}
        current = await self.get(name, key)
        if expected_version is not None:
            expected_version = utc(expected_version)
        if (current is None and expected_version is not None) or (
            current is not None and current["valid_from"] != expected_version
        ):
            raise GraphError("Row version conflict.")
        if current is not None and row_model(name, current) == model:
            return False
        if current is not None and self._at <= current["valid_from"]:
            raise GraphError("Changed versions require a later timestamp.")
        # Inserts and updates must not rewrite any earlier household snapshot, even
        # when a different entity was the household's most recent mutation.
        latest = []
        for candidate in db.GRAPH_TABLES.values():
            household_column = "id" if candidate is db.households else "household_id"
            latest.append(
                sa.select(sa.func.max(candidate.c.valid_from))
                .where(candidate.c[household_column] == self.household_id)
                .scalar_subquery()
            )
        last_write = await self.connection.scalar(sa.select(sa.func.greatest(*latest)))
        if last_write is not None and self._at < last_write:
            raise GraphError("Backdated household writes are not accepted.")
        if (
            isinstance(model, ContactChannel)
            and model.verified_at is not None
            and model.verified_at > self._at
        ):
            raise GraphError("Future channel verification is not accepted.")
        if isinstance(model, Observation):
            if model.observed_at > self._at:
                raise GraphError("Future observations are not accepted.")
            if current is not None:
                previous = Observation.model_validate(
                    row_model(name, current).model_dump()
                )
                if model.observed_at < previous.observed_at:
                    raise GraphError("Out-of-order observations are not accepted.")
                if (model.member_id, model.asset_id) != (
                    previous.member_id,
                    previous.asset_id,
                ):
                    raise GraphError("An observation's subject cannot change.")
                if model.domain != previous.domain:
                    raise GraphError("An observation's domain cannot change.")
            members = set()
            if (
                model.member_id is not None
                and await self.get("members", {"id": model.member_id}) is not None
            ):
                members.add(model.member_id)
            assets = {}
            for identity in {model.asset_id, model.state.zone_id} - {None}:
                row = await self.get("assets", {"id": identity})
                if row is not None:
                    asset = Asset.model_validate(row_model("assets", row).model_dump())
                    assets[asset.id] = asset.kind
            validate_observation_scope(
                model, self.household_id, members, assets, self._at
            )
        if name == "schedule_events" and values.get("zone_id") is not None:
            await self._require_zone(values["zone_id"])
        if current is None:
            await self.connection.execute(
                table.insert().values(**values, valid_from=self._at)
            )
        else:
            await self.connection.execute(
                db.HISTORY_TABLES[name]
                .insert()
                .values(**(current | {"valid_to": self._at}))
            )
            await self.connection.execute(
                table.update()
                .where(self._where(name, key))
                .values(**values, valid_from=self._at)
            )
        self._changed = True
        self._revision += 1
        return True

    async def _require_zone(self, zone_id: UUID) -> None:
        zone = await self.get("assets", {"id": zone_id})
        if zone is None or zone["attributes"].get("kind") != "hvac_zone":
            raise GraphError("Zone must be an HVAC asset in this household.")
