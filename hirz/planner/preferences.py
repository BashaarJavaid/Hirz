"""Read-only graph preferences mapped to bounded, unambiguous room evidence."""

from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from pydantic import AwareDatetime

from hirz.graph.context import ContextSnapshot
from hirz.graph.models import (
    ConstraintRecord,
    ConstraintSpec,
    Model,
    Observation,
    Preference,
    utc,
)
from hirz.pipeline.models import PlanConstraint
from hirz.planner.models import PlannerInput
from hirz.risk import CLASSES


class PreferenceWindow(Model):
    """Derived planner input, never a fabricated durable constraint/audit record."""

    id: UUID
    household_id: UUID
    member_id: UUID
    asset_id: UUID
    spec: ConstraintSpec
    provenance: PlanConstraint
    rank: tuple[int, float]
    withdrawn_at: AwareDatetime | None = None


def windows(
    p: PlannerInput, snapshot: ContextSnapshot, explicit: tuple[ConstraintRecord, ...]
) -> tuple[PreferenceWindow, ...]:
    from hirz.planner.coordinator import Clarification, active, clean

    begin, end = utc(p.slots[0].start), utc(p.slots[-1].end)
    threshold = timedelta(seconds=CLASSES["energy.hvac_adjust"]["freshness_seconds"])
    observations = tuple(
        Observation.model_validate(clean(r))
        for r in snapshot.data["observations"]
        if r.get("domain") == "presence"
    )
    arrivals = tuple(
        r
        for r in snapshot.data["schedule_events"]
        if r["kind"] == "arrival"
        and r.get("expected_at") is not None
        and r.get("zone_id") is not None
    )
    edges = {begin, end}
    for observation in observations:
        edges.update(
            (utc(observation.observed_at), utc(observation.observed_at) + threshold)
        )
    for event in arrivals:
        edges.update(
            datetime.fromisoformat(str(event[k])) for k in ("expected_at", "ends_at")
        )
    for record in explicit:
        edges.update(
            t
            for t in (record.spec.starts_at, record.spec.ends_at, record.withdrawn_at)
            if t is not None
        )
    ordered = sorted(t for t in edges if begin <= t <= end)
    assets = {
        str(r["asset_id"])
        for r in snapshot.data["asset_bindings"]
        if r["entity_id"] in {z.entity for z in p.zones}
    }
    result = []
    seen = set()
    for row in snapshot.data["preferences"]:
        preference = Preference.model_validate(clean(row))
        if preference.scope != "member" or preference.key != "temperature_target_f":
            continue
        if preference.member_id in seen:
            raise Clarification(
                "Multiple temperature preferences for one member require clarification."
            )
        seen.add(preference.member_id)
        for start, finish in zip(ordered, ordered[1:]):
            presence = [
                o
                for o in observations
                if o.member_id == preference.member_id
                and o.state.available is not False
                and utc(o.observed_at) <= start < utc(o.observed_at) + threshold
            ]
            # All current reports must agree. An absent report or another room
            # cannot silently be discarded in favor of a convenient arrival.
            states = {(o.state.present, o.state.zone_id) for o in presence}
            if len(states) > 1:
                raise Clarification(
                    "Conflicting current room presence requires clarification."
                )
            located = {
                (o.state.zone_id, (0, 0.0))
                for o in presence
                if o.state.present is True and o.state.zone_id is not None
            }
            if not presence:
                relevant = [
                    r
                    for r in arrivals
                    if str(r.get("member_id")) == str(preference.member_id)
                    and datetime.fromisoformat(str(r["expected_at"]))
                    <= start
                    < datetime.fromisoformat(str(r["ends_at"]))
                ]
                located = {
                    (
                        UUID(str(r["zone_id"])),
                        (1, datetime.fromisoformat(str(r["expected_at"])).timestamp()),
                    )
                    for r in relevant
                }
                if len({zone for zone, _ in located}) > 1:
                    raise Clarification(
                        "Overlapping expected rooms require clarification."
                    )
            if not located:
                continue
            asset, rank = min(located, key=lambda item: item[1])
            if str(asset) not in assets or any(
                r.member_id == preference.member_id
                and r.asset_id == asset
                and r.spec.kind in {"temperature", "temperature_band"}
                and active(r, start, finish)
                for r in explicit
            ):
                continue
            spec = ConstraintSpec(
                kind="temperature",
                asset_id=asset,
                starts_at=start,
                ends_at=finish,
                value=cast(float, preference.value),
            )
            version = str(row.get("valid_from") or snapshot.as_of.isoformat())
            provenance = PlanConstraint(
                member_id=preference.member_id,
                source=f"preference:{preference.id}@{version}",
                recorded_at=datetime.fromisoformat(version),
                text="Accepted graph temperature preference"
                if preference.source == "learned_accepted"
                else "Declared graph temperature preference",
                encoded=spec.model_dump(mode="json")
                | {
                    "preference_id": str(preference.id),
                    "preference_version": version,
                    "preference_source": preference.source,
                },
            )
            result.append(
                PreferenceWindow(
                    id=preference.id,
                    household_id=preference.household_id,
                    member_id=preference.member_id,
                    asset_id=asset,
                    spec=spec,
                    provenance=provenance,
                    rank=rank,
                )
            )
    return tuple(result)
