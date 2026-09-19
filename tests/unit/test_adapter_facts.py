"""Graph-derived risk/policy facts and fill-only hypothetical observations."""

from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from hirz.constitution.conditions import evaluate, parse
from hirz.graph.models import Observation
from hirz.pipeline.context import extract
from hirz.pipeline.preview import PreviewEvidence, overlay
from tests.unit.test_pipeline import (
    AT,
    HOME,
    POLICY,
    action,
    evidence,
    ident,
    policy_edit,
    snapshot,
)


def context(at=AT):
    s = snapshot().model_copy(update={"as_of": at, "read_at": at})
    for row in s.data["observations"]:
        row["observed_at"] = at.isoformat()
    return s


def member(s, name="mom"):
    return next(
        r
        for r in s.data["observations"]
        if r.get("member_id") == str(ident("members", name))
    )


def bell(s):
    return next(r for r in s.data["observations"] if r.get("domain") == "doorbell")


def facts(s, name="energy.hvac_adjust", policy=POLICY):
    return extract(s, policy, action(name), (), Decimal(0))


def test_presence_wearable_coexistence_and_absence():
    s = context()
    row = member(s)
    wearable = dict(
        row, id=str(uuid4()), domain="wearable", state={"recovery_score": 90}
    )
    s.data["observations"].append(wearable)
    row["state"] = {"present": False}
    f = facts(s)
    assert f.risk.sleeping_any is False and f.risk.sleeping_in_target_zone is False
    assert (
        str(ident("members", "mom"))
        not in f.policy.values["occupancy"]["present_members"]
    )
    assert not evaluate(
        parse(f'occupancy.sleeping_in("{ident("assets", "hvac.living_room")}")'),
        f.policy.values,
        f.policy,
    )
    assert all(o["domain"] != "wearable" for o in f.policy.values["observations"])
    # A wearable is never an implicit presence reading.
    s.data["observations"].remove(row)
    assert facts(s).risk.sleeping_any is None
    assert "members" not in facts(s).policy.values["occupancy"]


@pytest.mark.parametrize(
    "state,expected",
    [
        ({"present": True, "sleeping": False}, False),
        ({"present": True, "sleeping": True}, True),
        ({"present": False}, False),
        ({"present": True, "available": False}, None),
        ({}, None),
        ({"sleeping": True}, None),
    ],
)
def test_occupancy_and_guests(state, expected):
    s = context()
    row = member(s)
    row["state"] = state
    for person in s.data["members"]:
        if person["id"] == row["member_id"]:
            person["role"] = "guest"
    f = facts(s, "security.door_unlock")
    assert f.risk.guest_present is (None if expected is None else state["present"])
    assert f.risk.sleeping_any is expected


def test_stale_presence_whole_readings_legacy_and_conflicts():
    s = context()
    member(s)["observed_at"] = (AT - timedelta(seconds=301)).isoformat()
    assert 301 in facts(s).risk.observation_ages_seconds
    assert facts(s).risk.sleeping_any is False
    old = deepcopy(member(s))
    member(s)["state"] = {"present": True}
    member(s)["observed_at"] = AT.isoformat()
    s.data["observations"].append(old)
    assert facts(s).risk.sleeping_any is None  # No backfill from the older reading.
    conflict = deepcopy(member(s))
    conflict["state"]["sleeping"] = True
    s.data["observations"].append(conflict)
    with pytest.raises(ValueError, match="Conflicting"):
        facts(s)
    s = context()
    member(s).pop("domain")
    assert facts(s).risk.sleeping_any is None


@pytest.mark.parametrize(
    "kind,expected", [(None, None), ("other", False), ("bedroom", True)]
)
def test_explicit_bedroom_metadata(kind, expected):
    s = context()
    for asset in s.data["assets"]:
        if asset["id"] == str(ident("assets", "light.living_room")):
            asset["room_kind"] = kind
    f = facts(s, "environment.lights")
    assert f.risk.target_is_bedroom is expected
    assert f.policy.values["asset"]["room_kind"] == kind


@pytest.mark.parametrize(
    "stamp,expected",
    [
        ("2026-10-13T18:44:59-05:00", True),
        ("2026-10-13T18:45:00-05:00", False),
        ("2026-10-13T19:04:00-05:00", False),
        ("2026-10-13T19:15:00-05:00", True),
    ],
)
def test_arrival_boundaries_and_stranger(stamp, expected):
    at = datetime.fromisoformat(stamp)
    s = context(at)
    bell(s)["state"]["last_press_at"] = stamp
    f = facts(s, "security.door_unlock")
    assert f.policy.values["context"]["unexpected_visitor"] is expected
    assert f.risk.doorbell_online is True
    assert f.policy.values["schedule"]["arrival_windows"]
    # No claimed identity participates in this classification.
    assert "visitor_identity" not in f.policy.values["context"]


@pytest.mark.parametrize(
    "age,known", [(0, True), (60, True), (60.001, False), (86400, False)]
)
def test_press_lifetime(age, known):
    s = context()
    bell(s)["state"]["last_press_at"] = (AT - timedelta(seconds=age)).isoformat()
    assert (
        "unexpected_visitor"
        in facts(s, "security.door_unlock").policy.values["context"]
    ) is known


def test_missing_ambiguous_offline_and_invalid_bells():
    s = context()
    assert (
        "unexpected_visitor"
        not in facts(s, "security.door_unlock").policy.values["context"]
    )
    bell(s)["state"]["available"] = False
    assert facts(s, "security.door_unlock").risk.doorbell_online is False
    duplicate = next(deepcopy(a) for a in s.data["assets"] if a["kind"] == "doorbell")
    duplicate["id"] = str(uuid4())
    s.data["assets"].append(duplicate)
    assert facts(s, "security.door_unlock").risk.doorbell_online is None
    s.data["assets"] = [a for a in s.data["assets"] if a["kind"] != "doorbell"]
    s.data["observations"] = [
        o for o in s.data["observations"] if o["domain"] != "doorbell"
    ]
    assert facts(s, "security.door_unlock").risk.doorbell_online is None
    s = context()
    bell(s)["state"]["last_press_at"] = (AT + timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError):
        facts(s)


def test_tariff_is_scoped_and_only_used_when_referenced():
    s = context()
    tariff = Observation(
        id=uuid4(),
        household_id=HOME,
        domain="energy",
        observed_at=AT - timedelta(seconds=500),
        source="real",
        state={"price_band": "low"},
    )
    s.data["observations"].append(tariff.model_dump(mode="json", exclude_none=True))
    assert 500 not in facts(s).risk.observation_ages_seconds
    for policy in (
        policy_edit("energy.hvac_adjust", conditions=['context.price_band == "low"']),
        policy_edit(
            "energy.hvac_adjust",
            overrides=[{"when": 'context.price_band == "high"', "mode": "ask"}],
        ),
    ):
        f = facts(s, policy=policy)
        assert f.policy.values["context"]["price_band"] == "low"
        assert 500 in f.risk.observation_ages_seconds
        assert any(
            o["domain"] == "energy"
            and o["source"] == "real"
            and o["id"] == str(tariff.id)
            for o in f.policy.values["observations"]
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"domain": "wearable", "state": {"present": True}},
        {"domain": "presence", "state": {"recovery_score": 80}},
        {"domain": "presence", "state": {"last_press_at": AT}},
        {"domain": "presence", "state": {"price_band": "low"}},
        {"domain": "presence", "state": {"present": 1}},
    ],
)
def test_fact_locations_are_validated(changes):
    with pytest.raises(ValueError):
        Observation.model_validate(member(context()) | changes)


def test_overlay_fill_identity_conflict_and_immutability():
    s = context()
    before = deepcopy(s)
    row = Observation.model_validate(member(s))
    identical = PreviewEvidence(observations=(row,))
    assert overlay(s, identical) == s
    s.data["observations"].remove(member(s))
    filled = overlay(
        s,
        PreviewEvidence(
            observations=(row,),
            asset_rooms=(
                {
                    "asset_id": ident("assets", "light.living_room"),
                    "room_kind": "other",
                },
            ),
            scam_pattern=evidence(),
        ),
    )
    assert filled.data["observations"][-1] == row.model_dump(
        mode="json", exclude_none=True
    )
    assert facts(filled, "environment.lights").risk.target_is_bedroom is False
    assert "room_kind" not in s.data["assets"][0]
    assert len(s.data["observations"]) + 1 == len(before.data["observations"])
    for preview in (
        PreviewEvidence(
            observations=(
                row.model_copy(update={"observed_at": AT - timedelta(seconds=1)}),
            )
        ),
        PreviewEvidence(
            asset_rooms=(
                {
                    "asset_id": ident("assets", "light.living_room"),
                    "room_kind": "bedroom",
                },
            )
        ),
        PreviewEvidence(asset_rooms=({"asset_id": uuid4(), "room_kind": "other"},)),
        PreviewEvidence(scam_pattern=evidence(household_id=uuid4())),
        PreviewEvidence(observations=(row.model_copy(update={"member_id": uuid4()}),)),
    ):
        with pytest.raises(ValueError):
            overlay(filled, preview)


@pytest.mark.parametrize(
    "value",
    [
        [],
        {"occupancy_complete": True},
        {"observations": [{"source": "real"}]},
        {"members": []},
        {"scam_pattern": {"scam_pattern": True}},
    ],
)
def test_preview_rejects_legacy_or_arbitrary_graph_inputs(value):
    with pytest.raises(ValueError):
        PreviewEvidence.model_validate(value)


def test_preview_rejects_duplicate_and_non_twin_records():
    row = Observation.model_validate(member(context()))
    for records in (
        (row, row),
        (row.model_copy(update={"source": "real"}),),
        (row.model_copy(update={"domain": None}),),
    ):
        with pytest.raises(ValueError):
            PreviewEvidence(observations=records)
    with pytest.raises(ValueError):
        PreviewEvidence(
            asset_rooms=({"asset_id": row.member_id, "room_kind": "other"},) * 2
        )
    with pytest.raises(ValueError):
        PreviewEvidence(scam_pattern=evidence(source="real"))
