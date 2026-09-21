"""One-query redacted context; stale copies are opt-in and never decision inputs."""

from collections.abc import Callable
from copy import deepcopy
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import sqlalchemy as sa
from pydantic import AwareDatetime, JsonValue
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from hirz.graph.models import (
    MODELS,
    SCOPES,
    Entity,
    GraphError,
    Model,
    Scope,
    Source,
    now,
    utc,
)
from hirz.graph.repository import snapshot_sql


class ChannelSummary(Entity):
    contact_id: UUID
    kind: Literal["phone", "email", "hirz_app"]
    verified_at: AwareDatetime | None = None
    source: Source


class ContextSnapshot(Model):
    household_id: UUID
    scope: Scope
    as_of: AwareDatetime
    read_at: AwareDatetime
    stale: bool
    staleness_seconds: float
    policy_status: Literal["unvalidated", "missing"]
    data: dict[str, list[dict[str, JsonValue]]]


def validate_snapshot(
    raw: dict[str, Any], household_id: UUID, at: datetime | None = None
) -> dict[str, list[dict[str, Any]]]:
    if set(raw) != set(MODELS) - {"member_accounts"}:
        raise GraphError("Malformed household context.")
    output: dict[str, list[dict[str, Any]]] = {}
    for name, rows in raw.items():
        output[name] = []
        if not isinstance(rows, list):
            raise GraphError("Malformed household context.")
        for row in rows:
            if (
                not isinstance(row, dict)
                or "valid_from" not in row
                or "valid_to" not in row
            ):
                raise GraphError("Malformed household context.")
            if {"safe_word_hash", "value_hash", "sub", "provider"} & row.keys():
                raise GraphError("Private fields in household context.")
            values = {
                k: v for k, v in row.items() if k not in {"valid_from", "valid_to"}
            }
            model = ChannelSummary if name == "contact_channels" else MODELS[name]
            parsed = model.model_validate(values)
            scoped = "id" if name == "households" else "household_id"
            if getattr(parsed, scoped) != household_id:
                raise GraphError("Malformed household scope.")
            start = utc(datetime.fromisoformat(row["valid_from"]))
            end = (
                utc(datetime.fromisoformat(row["valid_to"]))
                if row["valid_to"]
                else None
            )
            if end is not None and end <= start:
                raise GraphError("Malformed history interval.")
            if at is not None and not (start <= at and (end is None or at < end)):
                raise GraphError("Context version lies outside the requested instant.")
            observed_at = getattr(parsed, "observed_at", None)
            if observed_at is not None and observed_at > start:
                raise GraphError("Observation was recorded before it was observed.")
            verified_at = getattr(parsed, "verified_at", None)
            if verified_at is not None and verified_at > start:
                raise GraphError(
                    "Channel verification lies after its recorded version."
                )
            output[name].append(
                parsed.model_dump(mode="json", exclude_none=True)
                | {
                    "valid_from": start.isoformat(),
                    "valid_to": end.isoformat() if end else None,
                }
            )
    if len(output["households"]) != 1:
        raise GraphError("Malformed household context.")
    return output


def project(
    data: dict[str, list[dict[str, Any]]], scope: Scope, member_id: UUID | None
) -> dict[str, list[dict[str, Any]]]:
    result = deepcopy(data)
    if scope == "all":
        return result
    keep = {"households"}
    if scope == "constraints":
        keep.add("constraints")
    elif scope in {"people", "member"}:
        keep |= {
            "members",
            "trusted_contacts",
            "contact_channels",
            "schedules",
            "schedule_events",
            "routines",
            "observations",
        }
        result["observations"] = [
            r for r in result["observations"] if r.get("member_id")
        ]
        if scope == "member":
            keep.add("preferences")
            for name in (
                "members",
                "trusted_contacts",
                "schedules",
                "schedule_events",
                "routines",
                "preferences",
                "observations",
            ):
                key = "id" if name == "members" else "member_id"
                result[name] = [r for r in result[name] if r.get(key) == str(member_id)]
            if not result["members"]:
                raise GraphError("Member not found in this household.")
            contacts = {r["id"] for r in result["trusted_contacts"]}
            result["contact_channels"] = [
                r for r in result["contact_channels"] if r["contact_id"] in contacts
            ]
    else:
        keep |= {"assets", "asset_bindings", "asset_policies", "observations"}
        energy = {"ev", "home_battery", "solar", "appliance"}
        result["assets"] = [
            r for r in result["assets"] if (r["kind"] in energy) == (scope == "energy")
        ]
        assets = {r["id"] for r in result["assets"]}
        for name in ("asset_bindings", "asset_policies", "observations"):
            result[name] = [
                r
                for r in result[name]
                if r.get("asset_id") in assets
                or (
                    name == "observations"
                    and scope == "energy"
                    and not r.get("member_id")
                    and not r.get("asset_id")
                    and r.get("domain") == "energy"
                )
                or (
                    name == "observations"
                    and scope == "environment"
                    and r.get("member_id")
                )
            ]
    return {k: v for k, v in result.items() if k in keep}


class ContextService:
    def __init__(
        self, connection: AsyncConnection, clock: Callable[[], datetime] = now
    ):
        self.connection = connection
        self.clock = clock
        self._cache: dict[UUID, tuple[datetime, dict[str, list[dict[str, Any]]]]] = {}

    async def get_household_context(
        self,
        household_id: UUID,
        scope: Scope = "all",
        as_of: datetime | None = None,
        member_id: UUID | None = None,
        allow_stale: bool = False,
    ) -> ContextSnapshot:
        if scope not in SCOPES or (scope == "member") != (member_id is not None):
            raise GraphError("Member UUID is required only for member scope.")
        instant = utc(self.clock())
        at = utc(as_of) if as_of is not None else instant
        if at > instant:
            raise GraphError("Future historical reads are not supported.")
        query = (
            (snapshot_sql(historical=True) + " WHERE h.id = :household_id")
            if as_of is not None
            else (
                "SELECT data FROM household_context WHERE household_id = :household_id"
            )
        )
        stale = False
        fetched_at = instant
        try:
            row = (
                (
                    await self.connection.execute(
                        sa.text(query),
                        {
                            "household_id": household_id,
                            "as_of": at,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
        except (DBAPIError, OSError, TimeoutError) as exc:
            # Integrity, malformed SQL/schema and invalid data are not availability failures.
            unavailable = (
                not isinstance(exc, DBAPIError)
                or exc.connection_invalidated
                or (getattr(exc.orig, "sqlstate", "") or "").startswith(
                    ("08", "53", "57P01", "57P02", "57P03")
                )
            )
            if (
                not unavailable
                or not allow_stale
                or as_of is not None
                or household_id not in self._cache
            ):
                raise
            fetched_at, data = self._cache[household_id]
            stale = True
        else:
            if row is None:
                self._cache.pop(household_id, None)
                raise GraphError("Household not found at the requested instant.")
            data = validate_snapshot(row["data"], household_id, at)
            if as_of is None:
                self._cache[household_id] = (instant, deepcopy(data))
        selected = project(data, scope, member_id)
        for observation in selected.get("observations", []):
            observed_at = utc(datetime.fromisoformat(observation["observed_at"]))
            if observed_at > at:
                raise GraphError("Observation lies after the requested instant.")
            observation["staleness_seconds"] = (at - observed_at).total_seconds()
        return ContextSnapshot(
            household_id=household_id,
            scope=scope,
            as_of=at,
            read_at=fetched_at,
            stale=stale,
            staleness_seconds=(instant - fetched_at).total_seconds(),
            policy_status="unvalidated"
            if data["households"][0].get("constitution_version")
            else "missing",
            data=selected,
        )
