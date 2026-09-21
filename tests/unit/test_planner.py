"""Item 17 physical, authority, comparison, and no-hindsight regression checks."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest

from hirz.adapters.energy.real.tariff import CHICAGO, load_tariff
from hirz.pipeline.hashing import action_hash
from hirz.pipeline.models import PlanConstraint, Requester
from hirz.planner import service, solver
from hirz.planner.heuristic import baseline
from hirz.planner.history import counterfactual_rate, hourly, persistence, read_raw
from hirz.planner.models import (
    Control,
    MemberConstraint,
    PlannerInput,
    Schedule,
    Slot,
    SolverDiagnostics,
    Zone,
    boundaries,
)
from hirz.planner.replay import replay
from hirz.planner.service import compare, plan
from hirz.twin.physics import EV, Appliance, Battery, ThermalZone, changed

AT = datetime(2025, 10, 13, 21, tzinfo=CHICAGO).astimezone(UTC)
HOME = UUID("413ef6f6-f221-4d32-aaee-c0b89e1846d7")


def tiny(prices=(0.4, 0.1), **kwargs):
    slots = tuple(
        Slot(
            start=AT + timedelta(minutes=15 * i),
            end=AT + timedelta(minutes=15 * (i + 1)),
            price=price,
            outdoor_f=70,
            solar_kw=0,
        )
        for i, price in enumerate(prices)
    )
    values = dict(
        household_id=HOME,
        requester=Requester(member_id="linked", role="owner", surface="alexa"),
        slots=slots,
        ev=EV(
            capacity_kwh=4,
            charger_kw=4,
            efficiency=1,
            soc=0.25,
            plugged_in=True,
            charging=False,
            charge_limit=0.5,
        ),
        ev_target=0.5,
        ev_deadline=slots[-1].end,
        battery=None,
        zones=(),
        appliance=None,
        appliance_release=AT,
        appliance_deadline=slots[-1].end,
        base_load_kw=0,
        provenance=("synthetic test",),
    )
    return PlannerInput(**(values | kwargs))


def constraint(kind="ev_not_before", at=None, value=None, recorded_at=AT):
    return MemberConstraint(
        kind=kind,
        at=at,
        value=value,
        provenance=PlanConstraint(
            source="member:linked",
            surface="alexa",
            claimed_author="Dad",
            recorded_at=recorded_at,
            text=kind,
            encoded={kind: at.isoformat() if at else value},
        ),
    )


def test_hand_computed_ev_optimum_negative_prices_and_hashes():
    p = tiny((0.4, -0.1))
    result = plan(p)
    assert result.plan is not None and result.replay.valid
    assert result.replay.electricity_usd == pytest.approx(-0.1)
    assert result.schedule.controls[0].ev_kwh == 0
    assert result.schedule.controls[1].ev_kwh == pytest.approx(1)
    assert result.replay.ev_delivered_kwh == pytest.approx(1)
    assert result.plan.summary.estimated_savings_usd == pytest.approx(0.5)
    assert result.plan.actions == tuple(a.action_id for a in result.actions)
    assert all(a.content_hash == action_hash(a) for a in result.actions)
    assert all(a.requested_by == p.requester for a in result.actions)
    assert plan(p).plan == result.plan
    other = plan(changed(p, household_id=UUID(int=1)))
    assert other.plan.plan_id != result.plan.plan_id
    assert set(other.plan.actions).isdisjoint(result.plan.actions)
    with pytest.raises(ValueError, match="another household"):
        plan(p, previous=other.plan)


def test_hand_computed_battery_optimum_and_conservation():
    p = tiny(
        (0.1, 0.4),
        ev=None,
        base_load_kw=4,
        battery=Battery(
            capacity_kwh=2,
            power_kw=4,
            efficiency=1,
            reserve_soc=0,
            soc=0.5,
            dispatch_kw=0,
        ),
    )
    schedule, diagnostic = solver.solve(p)
    r = replay(p, schedule)
    assert diagnostic.status == "optimal" and r.valid
    assert r.electricity_usd == pytest.approx(0.2)
    assert r.wear_usd == pytest.approx(0.02)
    assert r.battery_end_kwh == pytest.approx(1)
    assert r.throughput_kwh == pytest.approx(2)
    assert sum(r.export_kwh) == 0
    assert all(not (g > 1e-6 and e > 1e-6) for g, e in zip(r.grid_kwh, r.export_kwh))


def test_efficiency_loss_and_zero_export_credit():
    p = tiny(
        (-0.5, 0.5),
        ev=None,
        base_load_kw=2,
        battery=Battery(
            capacity_kwh=2,
            power_kw=2,
            efficiency=0.81,
            reserve_soc=0,
            soc=0.5,
            dispatch_kw=0,
        ),
    )
    result = plan(p)
    assert result.plan is not None
    assert result.replay.battery_loss_kwh > 0
    solar = changed(p, slots=tuple(changed(s, solar_kw=10) for s in p.slots))
    r = plan(solar).replay
    assert r.valid and sum(r.export_kwh) > 0
    assert r.electricity_usd == 0  # No simultaneous negative-price import/export.


def test_appliance_contiguity_deadline_and_hard_comfort():
    appliance = Appliance(cycle_minutes=30, cycle_kwh=1, noise_dba=50, running=False)
    z = Zone(
        entity="room",
        physical=ThermalZone(temp_f=70, target_f=70, mode="heat", solar_gain_area_m2=0),
        lower=(69, 69, 69, 69),
        upper=(71, 71, 71, 71),
        targets=(70, 70, 70, 70),
        occupants=(0, 0, 0, 0),
    )
    p = tiny((0.4, 0.1, 0.1, 0.4), ev=None, appliance=appliance, zones=(z,))
    result = plan(p)
    assert result.replay.valid and result.replay.appliance_completions == 1
    assert [c.appliance_start for c in result.schedule.controls] == [
        False,
        True,
        False,
        False,
    ]
    assert result.replay.appliance.energy_kwh == pytest.approx(1)
    assert result.replay.comfort_violations_minutes == 0


@pytest.mark.parametrize("change", ["ev", "battery", "comfort", "appliance"])
def test_replay_rejects_false_savings(change):
    p = tiny((0.1, 0.4), base_load_kw=4)
    if change == "battery":
        p = changed(p, battery=Battery(soc=0.55, dispatch_kw=0))
    if change == "comfort":
        z = Zone(
            entity="room",
            physical=ThermalZone(
                temp_f=70, target_f=70, mode="off", solar_gain_area_m2=0
            ),
            lower=(69, 69),
            upper=(71, 71),
            targets=(70, 70),
            occupants=(0, 0),
        )
        p = changed(p, zones=(z,))
    if change == "appliance":
        p = changed(
            p,
            appliance=Appliance(
                cycle_minutes=15, cycle_kwh=0.2, noise_dba=50, running=False
            ),
        )
    good = plan(p)
    controls = list(good.schedule.controls)
    if change == "ev":
        controls = [changed(c, ev_kwh=0) for c in controls]
    if change == "battery":
        controls[0] = changed(controls[0], battery_kw=1)
    if change == "comfort":
        controls = [changed(c, targets=(90,), modes=("heat",)) for c in controls]
    if change == "appliance":
        controls = [changed(c, appliance_start=False) for c in controls]
    bad = replay(p, changed(good.schedule, controls=tuple(controls)))
    assert not bad.valid
    valid, saving = compare(bad, good.replay)
    assert not valid.valid and saving is None


def test_infeasibility_newest_first_probes_and_reference(monkeypatch):
    p = tiny()
    previous = plan(p).plan
    bad = constraint(at=p.slots[-1].end)
    p = changed(p, constraints=(bad,))
    monkeypatch.setattr(
        service,
        "baseline",
        lambda *a: pytest.fail("No fallback for proven infeasibility"),
    )
    result = plan(p, previous=previous)
    assert result.plan is None and result.schedule is None
    assert result.blocking_constraints == (bad.provenance,)
    assert result.previous_feasible_reference == previous and result.reference_label
    assert result.previous_feasible_reference.summary.estimated_savings_usd is not None
    assert result.actions == ()


def test_conflicting_targets_do_not_silently_override():
    p = tiny()
    p = changed(
        p,
        constraints=(
            constraint("ev_target", value=0.5, recorded_at=AT - timedelta(minutes=1)),
            constraint("ev_target", value=0.4),
        ),
    )
    r = plan(p)
    assert r.plan is None
    assert len(r.blocking_constraints) == 2
    assert r.blocking_constraints[0].recorded_at == AT


def test_unresolved_infeasibility_and_invalid_taper():
    p = tiny(ev_deadline=AT)
    r = plan(p)
    assert r.plan is None and r.unresolved_conflict
    with pytest.raises(ValueError):
        changed(tiny(), ev_target=0.81)
    with pytest.raises(ValueError, match="Future constraints"):
        changed(
            tiny(),
            constraints=(constraint(at=AT, recorded_at=AT + timedelta(seconds=1)),),
        )


def test_timeout_incumbent_and_fallback(monkeypatch):
    p = tiny()
    schedule, _ = solver.solve(p)
    monkeypatch.setattr(
        service,
        "solve",
        lambda p: (
            changed(schedule, method="timeout_incumbent"),
            SolverDiagnostics(status="timeout", elapsed_seconds=5, gap=0.2),
        ),
    )
    r = plan(p)
    assert r.plan.method == "timeout_incumbent" and r.plan.optimality_gap == 0.2
    monkeypatch.setattr(
        service,
        "solve",
        lambda p: (None, SolverDiagnostics(status="timeout", elapsed_seconds=5)),
    )
    assert plan(p).plan.method == "greedy"
    assert plan(p, cold_start=True).plan.method == "greedy"
    broken = changed(
        schedule, controls=tuple(changed(c, ev_kwh=0) for c in schedule.controls)
    )
    monkeypatch.setattr(
        service,
        "solve",
        lambda p: (broken, SolverDiagnostics(status="timeout", elapsed_seconds=5)),
    )
    assert plan(p).plan is None


def test_solver_validates_incumbent(monkeypatch):
    def invalid(c, **kwargs):
        return SimpleNamespace(
            status=1, x=c * 0 + 100000, message="time limit", mip_gap=0.1
        )

    monkeypatch.setattr(solver, "milp", invalid)
    schedule, diag = solver.solve(tiny())
    assert schedule is None and diag.status == "invalid_incumbent"


@pytest.mark.parametrize(
    "day,count", [("2026-03-07", 92), ("2025-11-01", 100), ("2025-10-13", 96)]
)
def test_dst_and_partial_slots(day, count):
    start = datetime.fromisoformat(day).replace(hour=17, minute=30, tzinfo=CHICAGO)
    assert len(boundaries(start)) - 1 == count
    partial = boundaries(start + timedelta(minutes=3))
    assert len(partial) - 1 == count
    assert (partial[1] - partial[0]).total_seconds() == 12 * 60


def test_complete_hour_billing_and_persistence_cutoff():
    hour = AT.replace(minute=0)
    quotes = {hour + timedelta(minutes=i * 5): Decimal(i) for i in range(12)}
    assert hourly(quotes)[hour] == pytest.approx(0.055)
    del quotes[hour + timedelta(minutes=5)]
    assert hourly(quotes)[hour] is None
    history = {hour - timedelta(days=i): float(i) for i in range(8)}
    value, source = persistence(history, hour, AT)
    assert value == 2 and source + timedelta(hours=1) <= AT - timedelta(hours=24)
    history[hour] = 1000
    history[hour + timedelta(days=1)] = -1000
    assert persistence(history, hour, AT) == (value, source)
    with pytest.raises(ValueError, match="No eligible"):
        persistence({}, hour, AT)


def test_ambiguous_source_hours_excluded():
    source = datetime(2025, 11, 2, 1, tzinfo=CHICAGO)
    target = datetime(2025, 11, 4, 1, tzinfo=CHICAGO)
    decision = datetime(2025, 11, 3, 17, 30, tzinfo=CHICAGO)
    with pytest.raises(ValueError):
        persistence({source.astimezone(UTC): 1}, target, decision)


def test_forecast_plan_unaffected_by_future_realized_weather_and_price():
    from hirz.adapters.base import WeatherSample
    from scripts.backtest import inputs

    day = AT.astimezone(CHICAGO).date()
    start = AT - timedelta(days=8)
    times = [start + timedelta(hours=i) for i in range(24 * 11)]
    prices = {t: 0.1 for t in times}
    weather = {t: WeatherSample(at=t, temp_f=65, cloud_cover_percent=50) for t in times}
    first, _, _ = inputs(day, "comed_hourly", "ev_only", prices, weather)
    decision = (
        datetime.combine(day, datetime.min.time(), CHICAGO)
        .replace(hour=17, minute=30)
        .astimezone(UTC)
    )
    for t in times:
        if t >= decision:
            prices[t] = 100
            weather[t] = WeatherSample(at=t, temp_f=105, cloud_cover_percent=0)
    second, actual, _ = inputs(day, "comed_hourly", "ev_only", prices, weather)
    assert first == second
    assert any(f.outdoor_f != a.outdoor_f for f, a in zip(second, actual))


def test_counterfactual_does_not_weaken_production_tariff():
    from pathlib import Path

    tariff = load_tariff(Path("tariffs/comed-time-of-day.yaml"))
    with pytest.raises(ValueError):
        tariff.row(AT, "supply")
    assert counterfactual_rate(tariff, AT) > 0


def test_archive_checksum(tmp_path):
    import gzip
    import json

    (tmp_path / "a.gz").write_bytes(gzip.compress(b"changed"))
    (tmp_path / "manifest.json").write_text(json.dumps({"a.gz": {"sha256": "bad"}}))
    with pytest.raises(ValueError, match="checksum"):
        read_raw(tmp_path, "a.gz")


@pytest.mark.parametrize("profile", ["comed_time_of_day", "comed_hourly"])
@pytest.mark.parametrize(
    "configuration", ["solar_battery_ev", "ev_only", "solar_battery"]
)
def test_small_offline_study_carries_state_and_missing_bills(profile, configuration):
    from datetime import date

    from hirz.adapters.base import WeatherSample
    from scripts.backtest import run

    start = datetime(2025, 9, 1, tzinfo=UTC) - timedelta(days=8)
    times = [start + timedelta(hours=i) for i in range(24 * 12)]
    prices = {t: 0.03 for t in times}
    # Constant retained synthetic test weather makes forecast and replay agree.
    weather = {
        t: WeatherSample(at=t, temp_f=65, cloud_cover_percent=100) for t in times
    }
    prices[datetime(2025, 9, 2, 7, tzinfo=UTC)] = None
    report = run(
        profile,
        configuration,
        0.01,
        prices,
        weather,
        date(2025, 9, 1),
        date(2025, 9, 3),
    )
    if profile == "comed_hourly":
        assert report["days"][0]["billing_complete"] is False
        assert report["days"][0]["savings"]["timer"] is None
    assert len(report["days"]) == 2
    ev = report["final_states"]["timer"]["ev"]
    if configuration != "solar_battery":
        assert ev["driven_kwh"] == 24
        assert ev["stored_kwh"] == pytest.approx(24)
        assert ev["soc"] == pytest.approx(0.34)
    assert report["days"][1]["strategies"]["timer"]["appliance_completions"] == 1


def test_existing_recorded_billing_fixtures_cover_dst():
    from pathlib import Path

    from hirz.adapters.energy.real import feeds

    for name in (
        "realtime-spring.json",
        "realtime-fall.json",
        "realtime-20260801.json",
    ):
        quotes = feeds.realtime((Path("tests/fixtures/energy") / name).read_text())
        billed = hourly(quotes)
        for at, value in billed.items():
            values = [quotes.get(at + timedelta(minutes=5 * i)) for i in range(12)]
            assert (value is not None) == all(v is not None for v in values)


def test_power_export_and_window_guards():
    p = tiny(ev=None, battery=Battery(soc=0.55, dispatch_kw=0))
    controls = tuple(
        Control(ev_kwh=0, battery_kw=1, targets=(), modes=(), appliance_start=False)
        for _ in p.slots
    )
    r = replay(p, Schedule(controls=controls, method="greedy"))
    assert "Battery discharge to grid prohibited" in r.reasons
    p = changed(p, battery=None)
    assert (
        "Battery control without battery"
        in replay(p, Schedule(controls=controls, method="greedy")).reasons
    )
    p = tiny(ev_deadline=AT + timedelta(minutes=15))
    schedule = baseline(tiny((0.4, 0.1)))
    assert "EV charging outside allowed window" in replay(p, schedule).reasons


def test_archive_fetch_resumes_and_never_downloads_during_replay(tmp_path, monkeypatch):
    import asyncio
    import json
    from datetime import date

    import httpx

    from hirz.planner import history

    calls = []
    transport = httpx.MockTransport(
        lambda request: calls.append(str(request.url)) or httpx.Response(200, text="[]")
    )
    original = httpx.AsyncClient
    monkeypatch.setattr(
        history.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=transport, **kwargs),
    )
    asyncio.run(history.fetch_archive(tmp_path, date(2025, 9, 1), date(2025, 9, 1)))
    count = len(calls)
    assert count == 21
    asyncio.run(history.fetch_archive(tmp_path, date(2025, 9, 1), date(2025, 9, 1)))
    assert len(calls) == count
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    for name in manifest:
        assert history.read_raw(tmp_path, name) == "[]"


def test_no_database_or_device_write_imports():
    import ast
    from pathlib import Path

    for source in Path("hirz/planner").glob("*.py"):
        tree = ast.parse(source.read_text())
        imported = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        assert not set(imported) & {
            "hirz.db",
            "hirz.pipeline.service",
            "hirz.graph.repository",
        }


def test_canonical_invalid_comparison_cannot_claim_savings():
    from hirz.pipeline.models import ComparisonValidity, PlanAlternative

    with pytest.raises(ValueError, match="cannot claim savings"):
        PlanAlternative(
            label="timer",
            cost_delta_usd=0,
            why_rejected="missing",
            validity=ComparisonValidity(valid=False, reasons=("missing",)),
        )
    result = plan(tiny())
    values = result.plan.model_dump()
    values["comparison_validity"] = {"valid": False, "reasons": ["missing"]}
    with pytest.raises(ValueError, match="cannot claim savings"):
        type(result.plan).model_validate(values)


def test_hourly_planning_scenario_has_no_future_kitchen_constraint():
    import asyncio
    from pathlib import Path

    from hirz.twin.scenario import LoadedScenario, run_scenario

    loaded = LoadedScenario(Path("scenarios/demo-evening-hourly.yaml"))
    report = asyncio.run(run_scenario(loaded, headless=True, assertions=True))
    assert report["status"] == "item17_planning_and_observations_passed"
    assert len(report["planning"]) == 2
    for snapshot in report["planning"]:
        assert snapshot["status"] == "passed"
        result = snapshot["result"]
        assert len(result["plan"]["constraints"]) == 1
        assert result["plan"]["constraints"][0]["source"] == "member:" + str(
            loaded.ref("members", "malik")
        )
        assert "kitchen" not in str(result["plan"]["constraints"])
    assert all(event.starts_at.year == 2025 for event in loaded.world.calendar)
