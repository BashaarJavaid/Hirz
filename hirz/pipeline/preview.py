"""Explicit simulated, fill-only graph facts for the read-only decision preview."""

from copy import deepcopy
from typing import Self
from uuid import UUID

from pydantic import model_validator

from hirz.graph.context import ContextSnapshot
from hirz.graph.models import (
    Asset,
    Model,
    Observation,
    RoomKind,
    observation_subject,
    validate_observation_scope,
)
from hirz.pipeline.context import ContextError
from hirz.pipeline.models import SupplementalEvidence


class AssetRoom(Model):
    asset_id: UUID
    room_kind: RoomKind


class PreviewEvidence(Model):
    observations: tuple[Observation, ...] = ()
    asset_rooms: tuple[AssetRoom, ...] = ()
    scam_pattern: SupplementalEvidence | None = None

    @model_validator(mode="after")
    def explicit_simulation(self) -> Self:
        if any(o.domain is None or o.source != "twin" for o in self.observations):
            raise ValueError("Preview observations require domain and source=twin")
        if self.scam_pattern is not None and self.scam_pattern.source != "twin":
            raise ValueError("Preview evidence must be simulated")
        keys = {(observation_subject(o), o.domain) for o in self.observations}
        if len(keys) != len(self.observations) or len(
            {o.id for o in self.observations}
        ) != len(self.observations):
            raise ValueError("Duplicate preview observations")
        if len({r.asset_id for r in self.asset_rooms}) != len(self.asset_rooms):
            raise ValueError("Duplicate preview room metadata")
        return self


def overlay(snapshot: ContextSnapshot, supplied: PreviewEvidence) -> ContextSnapshot:
    preview = PreviewEvidence.model_validate(supplied.model_dump())
    data = deepcopy(snapshot.data)
    assets = {
        Asset.model_validate(
            {k: v for k, v in r.items() if k not in {"valid_from", "valid_to"}}
        ).id: r
        for r in data["assets"]
    }
    kinds = {
        identity: Asset.model_validate(
            {k: v for k, v in row.items() if k not in {"valid_from", "valid_to"}}
        ).kind
        for identity, row in assets.items()
    }
    members = {UUID(str(row["id"])) for row in data["members"]}
    existing = [
        Observation.model_validate(
            {
                k: v
                for k, v in row.items()
                if k not in {"valid_from", "valid_to", "staleness_seconds"}
            }
        )
        for row in data["observations"]
    ]
    for observation in preview.observations:
        validate_observation_scope(
            observation, snapshot.household_id, members, kinds, snapshot.as_of
        )
        matches = [
            old
            for old in existing
            if (observation_subject(old), old.domain)
            == (observation_subject(observation), observation.domain)
            or old.id == observation.id
        ]
        if matches:
            if len(matches) != 1 or matches[0] != observation:
                raise ContextError("Preview observation conflicts with the graph")
        else:
            data["observations"].append(
                observation.model_dump(mode="json", exclude_none=True)
            )
    for room in preview.asset_rooms:
        row = assets.get(room.asset_id)
        if row is None or row.get("room_kind") not in (None, room.room_kind):
            raise ContextError("Preview room metadata conflicts with the graph")
        row["room_kind"] = room.room_kind
    if item := preview.scam_pattern:
        if (
            item.household_id != snapshot.household_id
            or item.observed_at > snapshot.as_of
        ):
            raise ContextError("Invalid preview evidence scope or time")
    return snapshot.model_copy(update={"data": data})
