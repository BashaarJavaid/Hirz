"""Physics, clock partitioning, adapter boundaries and private simulated worlds."""

import asyncio
import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from hirz.adapters.base import AdapterError, AdapterUnavailable, WeatherSample
from hirz.adapters.doorbell.twin import TwinDoorbellEvent
from hirz.graph.models import (
    Asset,
    AssetBinding,
    ObservationState,
    validate_observation_scope,
)
from hirz.twin.adapters import factories, registry
from hirz.twin.clock import SimClock
from hirz.twin.environment import Period, Solar, Tariff, Weather, stream, sun_vector
from hirz.twin.people import (
    ContactScript,
    Device,
    InboundCall,
    Presence,
    Recovery,
    WeeklyTransition,
    local_instant,
    presence_change,
)
from hirz.twin.physics import EV, PROFILES, Appliance, Battery, ThermalZone, changed
from hirz.twin.world import Coupling, Override, TwinWorld
from scripts.smoke_twin import CONFIG, START, demo_world, physics_checks, smoke


def rebuild(world, **updates):
    return TwinWorld(
        world.household,
        members=tuple(world.members.values()),
        assets=tuple(world.assets.values()),
        bindings=tuple(world.bindings.values()),
        contacts=tuple(world.contacts.values()),
        channels=world.channels,
        calendar=world.calendar,
        config=changed(world.config, **updates),
        clock=SimClock(world.config.start, 0),
    )


def test_smoke_and_physics_targets(capsys):
    asyncio.run(smoke())
    output = capsys.readouterr().out
    assert "quinn-home: adapters=8" in output and "quinn-parents: adapters=8" in output
    assert physics_checks()["ev_minutes_34_to_50"] == pytest.approx(105.7579318449)


def test_clock_speed_pause_jump_and_invalid_time():
    elapsed = [100.0]
    clock = SimClock(START, 60, timer=lambda: elapsed[0])
    elapsed[0] += 2
    assert clock() == START + timedelta(minutes=2)
    clock.set_speed(0)
    elapsed[0] += 100
    assert clock() == START + timedelta(minutes=2)
    clock.jump(START + timedelta(hours=1))
    clock.set_speed(1)
    elapsed[0] += 1
    assert clock() == START + timedelta(hours=1, seconds=1)
    for invalid in (-1, math.inf, math.nan):
        with pytest.raises(AdapterError):
            clock.set_speed(invalid)
    with pytest.raises(AdapterError):
        clock.jump(START)
    with pytest.raises(ValueError):
        SimClock(datetime(2026, 1, 1), 0)
    elapsed[0] -= 2
    with pytest.raises(AdapterError):
        clock.now()


@given(
    st.floats(min_value=0, max_value=1, allow_nan=False),
    st.floats(min_value=-20, max_value=20, allow_nan=False),
    st.floats(min_value=0, max_value=86400, allow_nan=False),
)
@settings(max_examples=80)
def test_battery_energy_conservation_and_limits(soc, dispatch, seconds):
    before = Battery(soc=soc, dispatch_kw=dispatch)
    after = before.advance(seconds)
    delta = (after.soc - soc) * before.capacity_kwh
    assert 0 <= after.soc <= 1
    assert after.input_kwh - after.output_kwh == pytest.approx(
        delta + after.loss_kwh, abs=1e-8, rel=1e-9
    )
    assert after.cycles == pytest.approx(abs(delta) / (2 * before.capacity_kwh))
    if dispatch >= 0:
        assert after.soc >= min(soc, before.reserve_soc) - 1e-12


def test_battery_roundtrip_and_ev_taper_driving():
    battery = Battery(soc=0.1, dispatch_kw=-5)
    charged = battery.advance(10 * 3600)
    emptied = changed(charged, dispatch_kw=5).advance(10 * 3600)
    assert emptied.soc == pytest.approx(0.1)
    assert emptied.output_kwh / emptied.input_kwh == pytest.approx(0.9)
    ev = EV(soc=0.79, plugged_in=True, charging=True, charge_limit=1)
    long = ev.advance(7200)
    short = ev
    for _ in range(120):
        short = short.advance(60)
    assert short.soc == pytest.approx(long.soc)
    assert long.grid_kwh == pytest.approx(long.stored_kwh + long.loss_kwh)
    assert long.power_kw < ev.power_kw
    full = ev.advance(86400)
    assert full.soc == 1 and full.power_kw == 0
    assert changed(ev, plugged_in=False).advance(3600).soc == ev.soc
    with pytest.raises(AdapterError):
        ev.drive(1)
    unplugged = changed(ev, plugged_in=False)
    assert unplugged.drive(7.5).soc == pytest.approx(0.69)
    with pytest.raises(AdapterError):
        unplugged.drive(100)
    for model in (
        ev,
        battery,
        ThermalZone(temp_f=70, target_f=74, mode="heat", solar_gain_area_m2=0),
        Appliance(cycle_minutes=60, cycle_kwh=1, noise_dba=40, running=False),
    ):
        with pytest.raises(AdapterError):
            model.advance(-1, 40) if isinstance(model, ThermalZone) else model.advance(
                -1
            )


@pytest.mark.parametrize("name", PROFILES)
def test_appliance_energy_and_single_completion(name):
    minutes, energy = PROFILES[name]
    model = Appliance(
        cycle_minutes=minutes, cycle_kwh=energy, noise_dba=50, running=False
    ).start_cycle()
    with pytest.raises(AdapterError):
        model.start_cycle()
    before = model.advance(minutes * 60 - 0.5)
    assert before.running
    done = before.advance(1)
    assert done.completions == 1 and not done.running
    assert done.energy_kwh == pytest.approx(energy)
    assert done.advance(86400) == done
    assert done.start_cycle().elapsed_seconds == 0


def test_thermal_cooling_duty_cop_and_coupling_conservation():
    zone = ThermalZone(
        temp_f=75, target_f=74.99, mode="cool", cop=3, solar_gain_area_m2=0
    )
    result = zone.advance(60, 75)
    assert result.temp_f == pytest.approx(74.99)
    assert result.electricity_kwh == pytest.approx(abs(result.heat_kwh) / 3)
    assert (result.temp_f - zone.temp_f) * zone.thermal_mass_kwh_per_f == pytest.approx(
        result.heat_kwh + result.passive_kwh
    )
    world = demo_world()
    left, right = list(world.config.zones)
    zones = {
        left: changed(world.config.zones[left], mode="off", temp_f=80),
        right: changed(world.config.zones[right], mode="off", temp_f=60),
    }
    coupled = rebuild(world, zones=zones, couplings=(Coupling(left=left, right=right),))
    after = coupled.advance_to(START + timedelta(minutes=1))
    expected = sum(
        -(z.temp_f - 40) / z.resistance_f_per_kw / 60 for z in zones.values()
    )
    actual = sum(
        (after.zones[i].temp_f - z.temp_f) * z.thermal_mass_kwh_per_f
        for i, z in zones.items()
    )
    assert actual == pytest.approx(expected, abs=1e-8)
    with pytest.raises(AdapterError):
        rebuild(
            world,
            zones={
                left: changed(zones[left], thermal_mass_kwh_per_f=1e-8),
                right: zones[right],
            },
        )


def test_solar_geometry_weather_and_coverage():
    noon = datetime(2026, 3, 20, 12, tzinfo=UTC)
    solar = Solar(tilt_degrees=0, orientation_degrees=0)
    assert solar.irradiance(noon, 0, 0, 0) > 0.99
    assert solar.irradiance(noon + timedelta(hours=12), 0, 0, 0) == 0
    assert solar.irradiance(noon, 0, 0, 100) == pytest.approx(
        0.2 * solar.irradiance(noon, 0, 0, 0)
    )
    south = Solar(tilt_degrees=45, orientation_degrees=180)
    north = changed(south, orientation_degrees=0)
    assert south.irradiance(noon, 45, 0, 0) > north.irradiance(noon, 45, 0, 0)
    assert math.sqrt(sum(v * v for v in sun_vector(noon, 90, 0))) == pytest.approx(1)
    with pytest.raises(AdapterError):
        solar.irradiance(noon, 91, 0, 0)
    with pytest.raises(AdapterError):
        solar.irradiance(noon, 0, 0, 101)
    world = demo_world()
    weather = changed(
        world.config.weather,
        samples=(
            world.config.weather.samples[0],
            WeatherSample(
                at=START + timedelta(hours=1), temp_f=50, cloud_cover_percent=0
            ),
        ),
    )
    assert weather.at(START + timedelta(minutes=59)).temp_f == 40
    assert weather.at(START + timedelta(hours=1)).temp_f == 50
    assert (
        len(weather.between(START + timedelta(minutes=30), START + timedelta(hours=2)))
        == 2
    )
    with pytest.raises(AdapterError):
        weather.at(START - timedelta(seconds=1))
    with pytest.raises(ValueError):
        Weather(start=START, end=START + timedelta(hours=1), samples=())


def test_tariff_clipping_negative_prices_and_stable_spikes():
    w = demo_world()
    tariff = Tariff(
        periods=(
            Period(
                start_minute=0,
                end_minute=1080,
                import_cents_per_kwh=Decimal("-1"),
                band="low",
                export_cents_per_kwh=Decimal("2"),
            ),
            Period(
                start_minute=1080,
                end_minute=1440,
                import_cents_per_kwh=Decimal("20"),
                band="peak",
            ),
        ),
        slot_minutes=30,
        spike_probability=1,
        spike_min_cents=Decimal("5"),
        spike_max_cents=Decimal("10"),
    )
    args = dict(
        origin=START,
        horizon=w.config.end,
        timezone=w.household.timezone,
        seed=7,
        home=w.household.id,
    )
    start, end = START + timedelta(minutes=10), START + timedelta(minutes=70)
    forecast = tariff.prices(start, end, "day_ahead", **args)
    realtime = tariff.prices(start, end, "realtime", **args)
    assert forecast[0].start == start and forecast[-1].end == end
    assert [p.import_cents_per_kwh for p in forecast] == [
        Decimal(-1),
        Decimal(20),
        Decimal(20),
    ]
    assert realtime == tariff.prices(start, end, "realtime", **args)
    assert all(
        Decimal(5) <= r.import_cents_per_kwh - f.import_cents_per_kwh <= Decimal(10)
        for r, f in zip(realtime, forecast)
    )
    assert realtime[0].export_cents_per_kwh == Decimal(2)
    assert (
        tariff.prices(START + timedelta(minutes=30), end, "realtime", **args)[
            0
        ].import_cents_per_kwh
        == realtime[1].import_cents_per_kwh
    )
    with pytest.raises(AdapterError):
        tariff.prices(START - timedelta(seconds=1), end, "realtime", **args)
    with pytest.raises(ValueError):
        changed(tariff, periods=())


def test_partitioned_reads_and_jumps_are_identical():
    direct, polling = demo_world(), demo_world()
    target = START + timedelta(hours=3, seconds=0.5)
    expected = direct.advance_to(target)
    for seconds in range(7, 3 * 3600, 37):
        polling.advance_to(START + timedelta(seconds=seconds))
    assert polling.advance_to(target) == expected
    assert polling.advance_to(target) == expected
    assert len([e for e in expected.events if e[1] == "appliance.completed"]) == 1
    assert expected.events[0][0] == START + timedelta(minutes=105)
    with pytest.raises(AdapterError):
        polling.advance_to(START)
    with pytest.raises(AdapterError):
        polling.advance_to(polling.config.end + timedelta(seconds=1))


def test_presence_recovery_overrides_and_dst():
    world = demo_world()
    member = next(iter(world.members))
    zone = next(iter(world.config.zones))
    at = START + timedelta(minutes=1)
    arrive = WeeklyTransition(
        weekday=1, minute=17 * 60 + 31, kind="arrive", zone_id=zone, jitter_minutes=0
    )
    leave = changed(arrive, minute=17 * 60 + 33, kind="leave", zone_id=None)
    config = dict(
        weekly=world.config.weekly | {member: (arrive, leave)},
        overrides=(
            Override(
                at=at,
                member_id=member,
                presence=Presence(present=True, sleeping=True, zone_id=zone),
            ),
            Override(at=at, member_id=member, recovery_score=10),
        ),
    )
    w = rebuild(world, **config)
    state = w.advance_to(at)
    assert state.presence[member].sleeping and state.recovery[member].score == 10
    state = w.advance_to(START + timedelta(minutes=3))
    assert not state.presence[member].present
    assert not state.presence[member].sleeping
    midnight = local_instant(
        START.date() + timedelta(days=1), 0, world.household.timezone
    )
    state = w.advance_to(midnight)
    expected = changed(world.config.recovery[member], score=10).next_day(
        midnight.astimezone(ZoneInfo(world.household.timezone)).date(),
        world.config.seed,
        world.household.id,
        member,
    )
    assert state.recovery[member] == expected
    assert rebuild(world, **config).advance_to(midnight) == state
    assert local_instant(
        datetime(2026, 3, 8).date(), 150, "America/Chicago"
    ) == datetime(2026, 3, 8, 8, 30, tzinfo=UTC)
    assert local_instant(
        datetime(2026, 11, 1).date(), 90, "America/Chicago"
    ) == datetime(2026, 11, 1, 6, 30, tzinfo=UTC)
    with pytest.raises(AdapterError):
        rebuild(world, weekly=world.config.weekly | {member: (arrive, arrive)})
    sleeping = presence_change(
        Presence(present=True, sleeping=False, zone_id=zone),
        changed(arrive, kind="sleep"),
    )
    assert sleeping.sleeping
    assert not presence_change(sleeping, changed(arrive, kind="wake")).sleeping


def test_random_streams_and_recovery_are_subject_independent():
    home, member = uuid4(), uuid4()
    before = stream(1, home, "recovery", str(member), "day").random()
    stream(1, home, "presence", str(uuid4()), "day").random()
    assert stream(1, home, "recovery", str(member), "day").random() == before
    r = Recovery(score=100, mean=100, rho=1, noise_sd=100)
    assert 0 <= r.next_day(START.date(), 1, home, member).score <= 100


def test_device_exact_latency_failure_and_pending_overlap():
    device = Device(
        state=ObservationState(available=True, locked=True),
        delays={"unlock": 1.5},
        fail_next="unlock",
    )
    pending = device.transition(
        "unlock", ObservationState(available=True, locked=False), START
    )
    with pytest.raises(AdapterError):
        pending.transition("unlock", device.state, START)
    assert pending.advance(START + timedelta(seconds=1)).state.locked
    failed = pending.advance(START + timedelta(seconds=1.5))
    assert failed.failed == 1 and failed.state.locked and failed.fail_next is None
    success = failed.transition(
        "unlock",
        ObservationState(available=True, locked=False),
        START + timedelta(seconds=2),
    ).advance(START + timedelta(seconds=3.5))
    assert not success.state.locked
    world = demo_world()
    lock = next(i for i, a in world.assets.items() if a.kind == "lock")
    w = rebuild(
        world,
        devices=world.config.devices
        | {lock: changed(pending, delays={"lock": 1.5, "unlock": 1.5})},
    )
    state = w.advance_to(START + timedelta(seconds=2))
    assert state.events[-1] == (START + timedelta(seconds=1.5), "device.failed", lock)


def test_contact_scripts_have_no_side_effects():
    contact = uuid4()
    for response in ("genuine", "not_genuine", "will_call", "no_answer"):
        script = ContactScript(
            contact_id=contact,
            requested_at=START,
            deadline=START + timedelta(minutes=5),
            reply=response,
            reply_at=None if response == "no_answer" else START + timedelta(minutes=1),
        )
        assert script.status(START) == "pending"
        assert script.status(START + timedelta(minutes=5)) == response
        with pytest.raises(AdapterError):
            script.status(START - timedelta(seconds=1))
    with pytest.raises(ValueError):
        changed(script, deadline=START)


def test_adapters_lifecycle_scoping_writes_and_doorbell():
    async def run():
        world = demo_world()
        reg = registry(world, CONFIG)
        await reg.start()
        devices = reg.resolve("devices")
        for write in (
            "set_climate",
            "set_light",
            "set_cover",
            "start_charge",
            "send_checkin",
        ):
            with pytest.raises(AdapterUnavailable):
                await getattr(devices, write)(None, None)
        with pytest.raises(AdapterUnavailable):
            devices.subscribe()
        with pytest.raises(AdapterError):
            await devices.get_state("not-a-device")
        with pytest.raises(AdapterError):
            await reg.resolve("wearable").get_recovery(uuid4())
        with pytest.raises(AdapterError):
            await reg.resolve("energy").get_battery("solar")
        bell = reg.resolve("doorbell")
        for kind, classification in (
            ("press", None),
            ("motion", "vehicle"),
            ("offline", None),
            ("online", None),
        ):
            body = (
                TwinDoorbellEvent(
                    kind=kind,
                    entity_id="doorbell.front_door",
                    at=START,
                    classification=classification,
                )
                .model_dump_json()
                .encode()
            )
            (row,) = await bell.on_event(body, {})
            assert reg.stamp("doorbell", "twin", row, at=START) == row
            if kind == "press":
                assert row.state.last_press_at == START
            if kind == "motion":
                assert row.state.motion_classification == "vehicle"
            if kind == "offline":
                assert row.state.model_dump(exclude_none=True) == {"available": False}
                assert await bell.snapshot("doorbell.front_door") is None
                with pytest.raises(AdapterError):
                    await bell.on_event(
                        TwinDoorbellEvent(
                            kind="press", entity_id="doorbell.front_door", at=START
                        )
                        .model_dump_json()
                        .encode(),
                        {},
                    )
        assert await bell.live_view_url("doorbell.front_door") is None
        for body, headers in (
            (b"{}", {}),
            (b"{}", {"Authorization": "private"}),
            (
                TwinDoorbellEvent(
                    kind="press",
                    entity_id="doorbell.front_door",
                    at=START + timedelta(seconds=1),
                )
                .model_dump_json()
                .encode(),
                {},
            ),
        ):
            with pytest.raises(AdapterError):
                await bell.on_event(body, headers)
        other = demo_world("quinn-parents")
        with pytest.raises(AdapterError):
            factories(world)[("devices", "twin")](other.household)
        await reg.close()
        with pytest.raises(AdapterUnavailable):
            await devices.get_state("lock.front_door")

    asyncio.run(run())


def test_contacts_never_expose_inbound_calls_or_unverified_channels():
    async def run():
        w = demo_world("quinn-parents")
        world = rebuild(
            w,
            inbound_calls=(
                InboundCall(
                    at=START,
                    presented_number="synthetic-private",
                    summary="private call",
                ),
            ),
        )
        reg = registry(world, CONFIG)
        await reg.start()
        try:
            adapter = reg.resolve("contacts")
            contact = next(iter(world.contacts))
            channels = await adapter.verified_channels(contact)
            assert len(channels) == 1
            assert "synthetic-private" not in repr(channels)
            assert "value_hash" not in channels[0].model_dump()
            world.channels = tuple(
                changed(c, verified_at=START + timedelta(minutes=1))
                for c in world.channels
            )
            assert await adapter.verified_channels(contact) == ()
            with pytest.raises(AdapterError):
                await adapter.verified_channels(uuid4())
        finally:
            await reg.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "field,value",
    [("camera_armed", True), ("cover_position_percent", 50), ("last_motion_at", START)],
)
def test_new_observation_fields_validate_scope(field, value):
    w = demo_world()
    lock = next(i for i, a in w.assets.items() if a.kind == "lock")
    with pytest.raises(ValueError):
        w.observation(
            "devices", lock, ObservationState.model_validate({field: value}), START
        )


def test_config_scope_missing_state_precedence_and_initial_validation():
    w = demo_world()
    with pytest.raises(AdapterError):
        rebuild(w, presence={})
    with pytest.raises(AdapterError):
        rebuild(w, evs={})
    i = next(iter(w.config.evs))
    w.assets[i] = changed(
        w.assets[i], physical={"capacity_kwh": 90, "charger_kw": 11, "efficiency": 0.9}
    )
    graph = rebuild(w)
    assert graph.advance_to(START).evs[i].capacity_kwh == 90
    explicit = rebuild(w, evs={i: changed(w.config.evs[i], capacity_kwh=80)})
    assert explicit.advance_to(START).evs[i].capacity_kwh == 80
    with pytest.raises(ValueError):
        changed(w.config, end=START)
    with pytest.raises(ValueError):
        EV(soc=float("nan"), plugged_in=True, charging=False, charge_limit=1)


def test_canonical_camera_shade_and_motion_valid_observations():
    w = demo_world()
    for kind, values in (
        ("camera", {"camera_armed": True}),
        ("shade", {"cover_position_percent": 50}),
    ):
        ident = uuid4()
        w.assets[ident] = Asset(
            id=ident, household_id=w.household.id, name=kind, kind=kind
        )
        w.bindings[ident] = AssetBinding(
            id=uuid4(),
            household_id=w.household.id,
            asset_id=ident,
            adapter="twin",
            entity_id=kind,
        )
        row = w.observation("devices", ident, ObservationState(**values), START)
        validate_observation_scope(
            row,
            w.household.id,
            w.members.keys(),
            {i: a.kind for i, a in w.assets.items()},
            START,
        )


def test_world_supply_loss_accounting_and_partial_device_state():
    w = demo_world()
    battery = next(iter(w.config.batteries))
    for dispatch in (-5, 5):
        run = rebuild(
            w,
            batteries={
                battery: changed(
                    w.config.batteries[battery], soc=0.11, dispatch_kw=dispatch
                )
            },
        )
        state = run.advance_to(START + timedelta(hours=12))
        b = state.batteries[battery]
        assert state.import_kwh + state.pv_kwh + b.output_kwh == pytest.approx(
            state.load_kwh + b.input_kwh + state.export_kwh, abs=1e-8, rel=1e-9
        )
        assert b.input_kwh - b.output_kwh == pytest.approx(
            (b.soc - 0.11) * b.capacity_kwh + b.loss_kwh, abs=1e-8, rel=1e-9
        )
    bell = next(i for i, a in w.assets.items() if a.kind == "doorbell")
    world = rebuild(
        w,
        devices=w.config.devices
        | {
            bell: changed(
                w.config.devices[bell], expected_visitor_hint="private-scenario-name"
            )
        },
    )

    async def read():
        reg = registry(world, CONFIG)
        await reg.start()
        try:
            adapter = reg.resolve("doorbell")
            body = (
                TwinDoorbellEvent(
                    kind="press", entity_id="doorbell.front_door", at=START
                )
                .model_dump_json()
                .encode()
            )
            rows = await adapter.on_event(body, {})
            assert "private-scenario-name" not in repr(rows)
        finally:
            await reg.close()

    asyncio.run(read())


def test_weekly_jitter_and_unrelated_member_do_not_change_existing_trace():
    w = demo_world()
    member, other = list(w.members)[:2]
    zone = next(iter(w.config.zones))
    arrival = WeeklyTransition(
        weekday=1, minute=18 * 60, kind="arrive", zone_id=zone, jitter_minutes=5
    )
    first = rebuild(w, weekly=w.config.weekly | {member: (arrival,)})
    second = rebuild(
        w, weekly=w.config.weekly | {member: (arrival,), other: (arrival,)}
    )
    at = START + timedelta(hours=1)
    state1, state2 = first.advance_to(at), second.advance_to(at)
    events1 = [e for e in state1.events if e[2] == member]
    events2 = [e for e in state2.events if e[2] == member]
    assert events1 == events2 and len(events1) == 1
    assert (
        START + timedelta(minutes=25) <= events1[0][0] <= START + timedelta(minutes=35)
    )


def test_valid_camera_shade_adapters_and_export_capability():
    w = demo_world()
    devices = dict(w.config.devices)
    for kind, values, delays in (
        ("camera", {"camera_armed": True}, {"arm": 0.5, "disarm": 0.7}),
        ("shade", {"cover_position_percent": 30}, {"move": 2}),
    ):
        ident = uuid4()
        w.assets[ident] = Asset(
            id=ident, household_id=w.household.id, name=kind, kind=kind
        )
        w.bindings[ident] = AssetBinding(
            id=uuid4(),
            household_id=w.household.id,
            asset_id=ident,
            adapter="twin",
            entity_id=kind,
        )
        devices[ident] = Device(
            state=ObservationState(available=True, **values),
            delays=delays,
            fail_next=None,
        )
    tariff = changed(
        w.config.tariff,
        periods=tuple(
            changed(p, export_cents_per_kwh=Decimal(2)) for p in w.config.tariff.periods
        ),
    )
    world = rebuild(w, devices=devices, tariff=tariff)

    async def run():
        reg = registry(world, CONFIG)
        await reg.start()
        try:
            assert reg.resolve("energy", capability="has_export_price")
            adapter = reg.resolve("devices")
            assert (await adapter.get_state("camera")).state.camera_armed
            assert (await adapter.get_state("shade")).state.cover_position_percent == 30
            events = await reg.resolve("calendar").list_events(
                START + timedelta(hours=1, minutes=20),
                START + timedelta(hours=1, minutes=21),
            )
            assert (
                len(events) == 1
            )  # overlap, not only events beginning inside the query
        finally:
            await reg.close()

    asyncio.run(run())


def test_read_ranges_stop_at_simulation_horizon_even_with_longer_weather():
    original = demo_world()
    world = rebuild(original, end=START + timedelta(hours=2))

    async def run():
        reg = registry(world, CONFIG)
        await reg.start()
        try:
            for domain, method in (
                ("energy", "get_weather"),
                ("calendar", "list_events"),
            ):
                with pytest.raises(AdapterError):
                    await getattr(reg.resolve(domain), method)(
                        START, START + timedelta(hours=3)
                    )
        finally:
            await reg.close()

    asyncio.run(run())


def test_forward_only_even_between_committed_minute_boundaries():
    world = demo_world()
    world.advance_to(START + timedelta(seconds=30))
    with pytest.raises(AdapterError):
        world.advance_to(START + timedelta(seconds=29))
    assert world.advance_to(START + timedelta(seconds=30)) == world.advance_to(
        START + timedelta(seconds=30)
    )
