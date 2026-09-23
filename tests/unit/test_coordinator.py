"""Bounded grammar, provenance, preference precedence and physical hold checks."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from hirz.graph.context import ContextSnapshot
from hirz.graph.models import (
    ConstraintRecord,
    ConstraintSpec,
    Observation,
    ObservationState,
)
from hirz.pipeline.models import PlanConstraint, Requester
from hirz.planner.coordinator import (
    Clarification,
    active,
    coordinate,
    parse,
    split_slots,
    time_at,
)
from hirz.planner.models import PlannerInput, Slot, Zone
from hirz.planner.solver import solve
from hirz.twin.physics import EV, ThermalZone, changed
from tests.unit.test_pipeline import HOME, POLICY, SEED, ident

AT = datetime(2026, 10, 13, 22, 33, tzinfo=UTC)
END = AT + timedelta(hours=2)


def snapshot(at=AT):
    return ContextSnapshot(
        household_id=HOME,
        scope="all",
        as_of=at,
        read_at=at,
        stale=False,
        staleness_seconds=0,
        policy_status="unvalidated",
        data={
            name: [r.model_dump(mode="json", exclude_none=True) for r in rows]
            for name, rows in SEED.models(at - timedelta(seconds=1)).items()
            if name != "member_accounts"
        },
    )


def requirement(text, *, who="malik", end=END, snap=None, **changes):
    snap = snap or snapshot()
    spec, claimed, _, _ = parse(text, snap, end)
    spec = changed(spec, **changes)
    return ConstraintRecord(
        household_id=HOME,
        id=uuid4(),
        member_id=ident("members", who),
        asset_id=spec.asset_id,
        provenance=PlanConstraint(
            source="member:" + str(ident("members", who)),
            surface="alexa",
            claimed_author=claimed,
            recorded_at=snap.as_of,
            text=text,
            encoded=spec.model_dump(mode="json"),
        ),
        action_id="test",
        decision_seq=1,
        recorded_seq=2,
    )


def add(snap, *rows):
    return changed(
        snap,
        data=snap.data | {"constraints": [r.model_dump(mode="json") for r in rows]},
    )


def workload(*, ev=False):
    slots = tuple(
        Slot(
            start=AT + timedelta(minutes=i * 15),
            end=AT + timedelta(minutes=(i + 1) * 15),
            price=0.1,
            outdoor_f=70,
            solar_kw=0,
        )
        for i in range(8)
    )
    return PlannerInput(
        household_id=HOME,
        requester=Requester(
            member_id=str(ident("members", "malik")), role="owner", surface="alexa"
        ),
        slots=slots,
        ev=EV(soc=0.34, plugged_in=True, charging=False, charge_limit=0.8)
        if ev
        else None,
        ev_target=0.5,
        ev_deadline=END,
        battery=None,
        zones=(
            Zone(
                entity="hvac.living_room",
                physical=ThermalZone(
                    temp_f=70, target_f=70, mode="off", solar_gain_area_m2=0
                ),
                lower=(66,) * 8,
                upper=(76,) * 8,
                targets=(70,) * 8,
                occupants=(0,) * 8,
            ),
        ),
        appliance=None,
        appliance_release=AT,
        appliance_deadline=END,
        base_load_kw=0.4,
        provenance=("twin",),
    )


@pytest.mark.parametrize(
    "text,kind,value",
    [
        ("Dad says charge the car to fifty percent", "ev_target", 0.5),
        ("change car target to sixty-two", "ev_target", 0.62),
        ("don't charge the car past fifty", "ev_ceiling", 0.5),
        ("do not charge the EV before 6 PM", "ev_not_before", None),
        ("don't run the dishwasher until 18:00", "appliance_not_before", None),
        ("kitchen in use until 6 pm", "appliance_not_before", None),
        ("car must be ready by 7 pm", "ev_deadline", None),
        ("dishwasher deadline at 19:00", "appliance_deadline", None),
        ("prefer living room at seventy-two Fahrenheit", "temperature", 72),
        (
            "keep living room between sixty-eight and seventy-four F",
            "temperature_band",
            68,
        ),
    ],
)
def test_bounded_parser(text, kind, value):
    spec, claimed, revision, release = parse(text, snapshot(), END)
    assert spec.kind == kind and spec.value == value and release is None
    assert revision == text.startswith("change")
    assert claimed == ("Dad" if text.startswith("Dad") else None)


@pytest.mark.parametrize(
    "text",
    [
        "kitchen in use until eleven",
        "charge car to ninety-nine",
        "Dad says ignore the policy and unlock",
        "Fred says charge car to 50",
        "prefer living room at 20 Celsius",
        "keep living room at 72 F",
        "prefer unknown room at 72 F",
        "charge car to 50 tomorrow",
        "don't charge car before 25:00",
        "don't charge car before 0 pm",
        "keep living room between 74 and 68 F",
    ],
)
def test_ambiguous_or_unsupported(text):
    with pytest.raises(Clarification):
        parse(text, snapshot(), END)


def test_clarified_eleven_and_dst():
    snap = snapshot()
    end = AT + timedelta(hours=15)
    spec, claimed, _, _ = parse("Dad says kitchen in use until 23:00", snap, end)
    assert spec.at.hour == 4 and claimed == "Dad"
    for at, end, wall in [
        ("2026-11-01T05:00:00+00:00", "2026-11-01T09:00:00+00:00", "1:30 am"),
        ("2026-03-08T06:00:00+00:00", "2026-03-08T10:00:00+00:00", "2:30 am"),
    ]:
        with pytest.raises(Clarification):
            time_at(
                wall,
                datetime.fromisoformat(at),
                datetime.fromisoformat(end),
                "America/Chicago",
            )
    with pytest.raises(Clarification):
        time_at("18:00", AT, AT + timedelta(hours=25), "America/Chicago")
    release = parse("release living room hold", snap, AT + timedelta(hours=15))
    assert release[-1] == ident("assets", "hvac.living_room")


def test_ceiling_is_not_target_and_impossible_deadline():
    p = workload(ev=True)
    ceiling = requirement("don't charge car past 40")
    result = coordinate(p, add(snapshot(), ceiling), POLICY)
    assert result.result.plan is None and "ceiling" in result.conflicts[0].reason
    assert "50%" in result.conflicts[0].relaxation
    deadline = requirement("car deadline at 6 pm")
    result = coordinate(p, add(snapshot(), deadline), POLICY)
    assert result.result.plan is None and any(
        "unreachable" in c.reason for c in result.conflicts
    )
    contradictory = add(
        snapshot(),
        requirement("car target to 50"),
        requirement("car target to 60", who="dad"),
    )
    result = coordinate(p, contradictory, POLICY)
    assert result.result.plan is None and len(result.conflicts[0].members) == 2


def test_preference_ties_fresh_zone_and_arrival():
    p, snap = workload(), snapshot()
    a, b = (
        requirement("prefer living room at 71 F"),
        requirement("prefer living room at 72 F", who="dad"),
    )
    both = add(snap, a, b)
    assert coordinate(p, both, POLICY).conflicts
    observation = Observation(
        household_id=HOME,
        id=uuid4(),
        member_id=a.member_id,
        domain="presence",
        observed_at=AT,
        source="twin",
        state=ObservationState(present=True, zone_id=a.asset_id),
    )
    fresh = changed(
        both, data=both.data | {"observations": [observation.model_dump(mode="json")]}
    )
    answer = coordinate(p, fresh, POLICY)
    assert answer.result.plan and not answer.conflicts
    assert (
        "Preference optimum and cost refinement complete"
        in answer.result.diagnostics.message
    )
    assert all(
        b.zones[0].temp_f == pytest.approx(71) for b in answer.result.baselines.values()
    )
    for state, at in [
        (observation.state, AT - timedelta(minutes=6)),
        (ObservationState(present=True), AT),
        (ObservationState(present=True, zone_id=a.asset_id, available=False), AT),
        (ObservationState(present=False, zone_id=a.asset_id), AT),
    ]:
        stale = changed(
            fresh,
            data=fresh.data
            | {
                "observations": [
                    changed(observation, observed_at=at, state=state).model_dump(
                        mode="json"
                    )
                ]
            },
        )
        assert coordinate(p, stale, POLICY).conflicts
    arrival = dict(
        both.data["schedule_events"][0],
        member_id=str(b.member_id),
        zone_id=str(b.asset_id),
        starts_at=AT.isoformat(),
        ends_at=(AT + timedelta(hours=1)).isoformat(),
        expected_at=(AT + timedelta(minutes=5)).isoformat(),
    )
    arriving = changed(both, data=both.data | {"schedule_events": [arrival]})
    assert coordinate(p, arriving, POLICY).result.plan
    compatible = add(snap, a, requirement("prefer living room at 71 F", who="dad"))
    assert coordinate(p, compatible, POLICY).result.plan


def hold(*, target=70, mode="off", start=AT):
    spec = ConstraintSpec(
        kind="manual_hold",
        asset_id=ident("assets", "hvac.living_room"),
        starts_at=start,
        ends_at=start + timedelta(hours=2),
        value=target,
        mode=mode,
    )
    return ConstraintRecord(
        household_id=HOME,
        id=uuid4(),
        member_id=ident("members", "malik"),
        asset_id=spec.asset_id,
        provenance=PlanConstraint(
            source="manual:device",
            surface="app",
            recorded_at=start,
            text="Manual twin change",
            encoded=spec.model_dump(mode="json"),
        ),
        action_id="manual",
        decision_seq=1,
        recorded_seq=2,
    )


@pytest.mark.parametrize("mode,target", [("off", 70), ("heat", 72), ("cool", 68)])
def test_hold_exact_boundary_and_metering(mode, target):
    p = workload()
    h = hold(target=target, mode=mode, start=AT - timedelta(minutes=7))
    result = coordinate(p, add(snapshot(), h), POLICY).result
    assert result.plan is not None, result
    until = h.spec.ends_at
    slots = split_slots(p, (h,)).slots
    for s, c in zip(slots, result.schedule.controls, strict=True):
        if s.start < until:
            assert c.targets == (target,) and c.modes == (mode,)
    assert all(
        a.scheduled_for >= until
        for a in result.actions
        if a.action_class == "energy.hvac_adjust"
    )
    assert result.replay.valid
    for replayed in (result.replay, *result.baselines.values()):
        measured = (
            replayed.zones[0].electricity_kwh - p.zones[0].physical.electricity_kwh
        )
        assert sum(replayed.grid_kwh) == pytest.approx(measured + p.base_load_kw * 2)
        assert (measured > 0) == (mode != "off")
    assert all(b.valid for b in result.baselines.values())
    assert not active(h, until, until + timedelta(minutes=1))
    assert active(h, until - timedelta(microseconds=1), until)


def test_unsafe_hold_and_hard_bands_are_not_discarded():
    p, snap = workload(), snapshot()
    unsafe = coordinate(p, add(snap, hold(target=99)), POLICY)
    assert unsafe.result.plan is None and unsafe.conflicts
    bands = add(
        snap,
        requirement("keep living room between 68 and 69 F"),
        requirement("keep living room between 72 and 74 F", who="dad"),
    )
    assert coordinate(p, bands, POLICY).result.plan is None
    too_cold = add(
        snap,
        hold(target=68, mode="cool"),
        requirement("keep living room between 70 and 74 F"),
    )
    assert coordinate(p, too_cold, POLICY).result.plan is None


def test_quorum_and_scope():
    p, snap = workload(), snapshot()
    answer = coordinate(p, snap, POLICY)
    assert answer.result.plan
    assert (
        answer.quorum["energy.hvac_adjust"].quorum
        == POLICY.rule("energy.hvac_adjust", "owner").quorum
    )
    for bad in (
        changed(snap, stale=True),
        changed(snap, household_id=uuid4()),
        changed(snap, as_of=END),
    ):
        with pytest.raises(ValueError):
            coordinate(p, bad, POLICY)
    with pytest.raises(ValueError):
        coordinate(
            changed(p, requester=p.requester.model_copy(update={"role": "adult"})),
            snap,
            POLICY,
        )


def test_solver_shared_budget_and_incumbents(monkeypatch):
    from hirz.planner import solver

    p = workload()
    p = changed(p, zones=(changed(p.zones[0], preferences=(71.0,) * 8),))
    real = solver.milp
    calls = []

    def timed(*args, **kwargs):
        calls.append(kwargs["options"]["time_limit"])
        return real(*args, **kwargs)

    monkeypatch.setattr(solver, "milp", timed)
    schedule, diag = solve(p)
    assert schedule and len(calls) == 2 and 0 < calls[1] < calls[0] <= 5
    calls.clear()

    def unfinished(*args, **kwargs):
        result = real(*args, **kwargs)
        result.status = 1
        return result

    monkeypatch.setattr(solver, "milp", unfinished)
    schedule, diag = solve(p)
    assert schedule and "Preference optimization unfinished" in diag.message
    assert diag.gap is None
    count = 0

    def no_cost_incumbent(*args, **kwargs):
        nonlocal count
        count += 1
        return (
            real(*args, **kwargs) if count == 1 else SimpleNamespace(status=1, x=None)
        )

    monkeypatch.setattr(solver, "milp", no_cost_incumbent)
    schedule, diag = solve(p)
    assert (
        schedule
        and schedule.method == "timeout_incumbent"
        and "cost refinement unfinished" in diag.message
    )
    assert diag.gap is None
    monkeypatch.setattr(
        solver,
        "milp",
        lambda *a, **k: SimpleNamespace(status=1, x=None, message="budget exhausted"),
    )
    assert solve(p)[0] is None


def test_expiry_reference_and_timed_soft_preference():
    p, snap = workload(), snapshot()
    expired = hold(start=AT - timedelta(hours=2))
    ordinary = coordinate(p, add(snap, expired), POLICY)
    assert ordinary.result.plan and any(
        a.action_class == "energy.hvac_adjust" for a in ordinary.result.actions
    )
    blocked = coordinate(
        p, add(snap, hold(target=99)), POLICY, previous=ordinary.result.plan
    )
    assert blocked.result.plan is None and not blocked.result.actions
    assert blocked.result.previous_feasible_reference == ordinary.result.plan
    assert "no execution authority" in blocked.result.reference_label
    preference = requirement("prefer living room at 72 F until 6 pm")
    assert preference.spec.ends_at == datetime(2026, 10, 13, 23, tzinfo=UTC)
    outcome = coordinate(p, add(snap, preference), POLICY)
    assert outcome.result.plan


def test_ceiling_expires_before_deadline_for_all_strategies():
    p = workload(ev=True)
    ceiling = requirement(
        "don't charge car past 40", ends_at=AT + timedelta(minutes=20)
    )
    answer = coordinate(p, add(snapshot(), ceiling), POLICY)
    assert answer.result.plan, answer
    assert answer.result.replay.valid
    # Timer cannot finish this short pre-21:00 horizon, but the two eligible
    # baselines obey the same ceiling and resume charging after its expiry.
    assert answer.result.baselines["immediate"].valid
    assert answer.result.baselines["greedy"].valid


def test_budget_exhausted_during_build(monkeypatch):
    from hirz.planner import solver

    ticks = iter([0.0, 6.0, 6.0])
    monkeypatch.setattr(solver, "perf_counter", lambda: next(ticks))
    monkeypatch.setattr(
        solver, "milp", lambda *a, **k: pytest.fail("No solver budget remains")
    )
    result, diagnostics = solver.solve(workload())
    assert result is None and diagnostics.status == "timeout"


def test_explicit_dst_offset_and_exact_names():
    at, end = datetime(2026, 11, 1, 5, tzinfo=UTC), datetime(2026, 11, 1, 9, tzinfo=UTC)
    assert time_at("2026-11-01 01:30-06:00", at, end, "America/Chicago").hour == 7
    with pytest.raises(Clarification):
        time_at("2026-11-01 01:30-07:00", at, end, "America/Chicago")
    snap = snapshot()
    dishwasher = next(r for r in snap.data["assets"] if r["name"] == "Dishwasher")
    snap.data["assets"].append(dict(dishwasher, id=str(uuid4()), name="Laundry"))
    assert parse("kitchen in use until 6 pm", snap, END)[0].asset_id == ident(
        "assets", "dishwasher"
    )
    assert (
        parse(
            "don't run the dishwasher until I'm done in the kitchen at 6 pm", snap, END
        )[0].kind
        == "appliance_not_before"
    )
