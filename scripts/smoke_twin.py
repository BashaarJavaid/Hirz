"""Credential-free item 13 demonstration. Every input and output is simulated."""

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

from hirz.adapters.base import AdapterUnavailable, WeatherSample
from hirz.adapters.calendar import CalendarAdapter
from hirz.adapters.contacts import ContactsAdapter
from hirz.adapters.devices import DevicesAdapter
from hirz.adapters.doorbell import DoorbellAdapter
from hirz.adapters.energy import EnergyAdapter
from hirz.adapters.ev import EVAdapter
from hirz.adapters.presence import PresenceAdapter
from hirz.adapters.wearable import WearableAdapter
from hirz.graph.context import ChannelSummary
from hirz.graph.models import (
    Asset,
    AssetBinding,
    Household,
    Member,
    Observation,
    ObservationState,
    ScheduleEvent,
    TrustedContact,
)
from hirz.graph.seeds import read_seed
from hirz.twin.adapters import registry
from hirz.twin.clock import SimClock
from hirz.twin.environment import Period, Solar, Tariff, Weather
from hirz.twin.people import Device, Presence, Recovery
from hirz.twin.physics import EV, Appliance, Battery, ThermalZone, changed
from hirz.twin.world import TwinConfig, TwinWorld

START = datetime.fromisoformat("2026-10-13T17:30:00-05:00")
CONFIG = "devices:twin,ev:twin,energy:twin,presence:twin,wearable:twin,calendar:twin,contacts:twin,doorbell:twin"


def demo_world(slug: str = "quinn-home") -> TwinWorld:
    """Explicit demonstration inputs, not product initialization defaults."""
    rows = read_seed(Path(f"constitutions/{slug}.yaml")).models(START)
    household = changed(cast(Household, rows["households"][0]), rate_plan="twin")
    assets = tuple(cast(Asset, a) for a in rows["assets"])
    members = tuple(cast(Member, m) for m in rows["members"])
    end = START + timedelta(days=2)
    config = TwinConfig(
        start=START,
        end=end,
        seed=20261013,
        base_load_kw=0.4,
        weather=Weather(
            start=START,
            end=end,
            samples=(WeatherSample(at=START, temp_f=40, cloud_cover_percent=20),),
        ),
        tariff=Tariff(
            periods=(
                Period(
                    start_minute=0,
                    end_minute=1440,
                    import_cents_per_kwh=Decimal("10"),
                    band="synthetic-base",
                ),
            ),
            slot_minutes=60,
            spike_probability=0.1,
            spike_min_cents=Decimal("5"),
            spike_max_cents=Decimal("15"),
        ),
        evs={
            a.id: EV(soc=0.34, plugged_in=True, charging=True, charge_limit=0.5)
            for a in assets
            if a.kind == "ev"
        },
        batteries={
            a.id: Battery(soc=0.55, dispatch_kw=0)
            for a in assets
            if a.kind == "home_battery"
        },
        zones={
            a.id: ThermalZone(temp_f=70, target_f=74, mode="heat", solar_gain_area_m2=0)
            for a in assets
            if a.kind == "hvac_zone"
        },
        solar={
            a.id: Solar(tilt_degrees=30, orientation_degrees=180)
            for a in assets
            if a.kind == "solar"
        },
        appliances={
            a.id: Appliance(
                cycle_minutes=105, cycle_kwh=1.2, noise_dba=50, running=True
            )
            for a in assets
            if a.kind == "appliance"
        },
        devices={
            a.id: Device(
                state=ObservationState(
                    available=True,
                    locked=True if a.kind == "lock" else None,
                    on=False if a.kind == "light" else None,
                ),
                delays={"lock": 1.5, "unlock": 1.5}
                if a.kind == "lock"
                else {"on": 0.2, "off": 0.2}
                if a.kind == "light"
                else {},
                fail_next=None,
            )
            for a in assets
            if a.kind in {"lock", "light", "doorbell"}
        },
        presence={
            m.id: Presence(present=False, sleeping=False, zone_id=None) for m in members
        },
        weekly={m.id: () for m in members},
        recovery={
            m.id: Recovery(score=75, mean=75, rho=0.7, noise_sd=5) for m in members
        },
        couplings=(),
        overrides=(),
        contact_scripts=(),
        inbound_calls=(),
    )
    channels = tuple(
        ChannelSummary.model_validate(c.model_dump(exclude={"value_hash"}))
        for c in rows["contact_channels"]
    )
    return TwinWorld(
        household,
        members=members,
        assets=assets,
        bindings=tuple(cast(AssetBinding, b) for b in rows["asset_bindings"]),
        contacts=tuple(cast(TrustedContact, c) for c in rows["trusted_contacts"]),
        channels=channels,
        calendar=tuple(cast(ScheduleEvent, e) for e in rows["schedule_events"]),
        config=config,
        clock=SimClock(START, 0),
    )


def physics_checks() -> dict[str, float]:
    ev = EV(soc=0.34, plugged_in=True, charging=True, charge_limit=0.5)
    minutes = ev.capacity_kwh * (0.5 - ev.soc) / (ev.charger_kw * ev.efficiency) * 60
    charged = ev.advance(minutes * 60)
    assert abs(charged.soc - 0.5) < 1e-10
    warm = ThermalZone(temp_f=70, target_f=80, mode="heat", solar_gain_area_m2=0)
    drift = changed(warm, mode="off")
    for minute in range(60):
        drift = drift.advance(60, 40)
        if minute < 45:
            warm = warm.advance(60, 40)
    assert 100 <= minutes <= 110
    assert 3.8 <= warm.temp_f - 70 <= 4.2
    assert 0.9 <= 70 - drift.temp_f <= 1.1
    return {
        "ev_minutes_34_to_50": minutes,
        "warm_45_min_f": warm.temp_f - 70,
        "drift_60_min_f": 70 - drift.temp_f,
        "ev_energy_residual_kwh": charged.grid_kwh
        - charged.stored_kwh
        - charged.loss_kwh,
    }


async def smoke() -> None:
    print("SIMULATED: standalone physics and read adapters; no actions or persistence")
    for name, value in physics_checks().items():
        print(f"PASS {name}={value:.8f}")
    for slug in ("quinn-home", "quinn-parents"):
        world = demo_world(slug)
        reg = registry(world, CONFIG)
        await reg.start()
        try:
            readings: list[Observation] = []
            devices = cast(DevicesAdapter, reg.resolve("devices"))
            for entity in await devices.list_entities():
                readings.append(await devices.get_state(entity))
            ev = cast(EVAdapter, reg.resolve("ev"))
            energy = cast(EnergyAdapter, reg.resolve("energy"))
            for ident, binding in world.bindings.items():
                kind = world.assets[ident].kind
                if kind == "ev":
                    readings.append(await ev.get_charge_state(binding.entity_id))
                elif kind == "home_battery":
                    readings.append(await energy.get_battery(binding.entity_id))
                elif kind == "solar":
                    readings.append(await energy.get_solar(binding.entity_id))
            readings.append(await energy.get_tariff_state())
            readings.extend(
                await cast(PresenceAdapter, reg.resolve("presence")).who_is_home()
            )
            wearable = cast(WearableAdapter, reg.resolve("wearable"))
            for member in world.members:
                readings.append(await wearable.get_recovery(member))
            prices = await energy.get_prices(
                START, START + timedelta(hours=2), "realtime"
            )
            assert len(prices.slots) == 2 and prices.complete
            assert (
                await energy.get_weather(START, START + timedelta(hours=2))
            ).complete
            await cast(CalendarAdapter, reg.resolve("calendar")).expected_arrivals(
                START, START + timedelta(days=1)
            )
            contacts = cast(ContactsAdapter, reg.resolve("contacts"))
            for contact in world.contacts:
                assert await contacts.verified_channels(contact)
            doorbell = cast(DoorbellAdapter, reg.resolve("doorbell"))
            assert b"Simulated doorbell snapshot" in (
                await doorbell.snapshot("doorbell.front_door") or b""
            )
            for row in readings:
                assert row.domain is not None
                assert (
                    reg.stamp(row.domain, "twin", row, at=world.clock.now()).source
                    == "twin"
                )
            try:
                reg.resolve("devices", capability="set_light")
            except AdapterUnavailable:
                pass
            else:
                raise AssertionError("Write capability was advertised")
            world.clock.jump(START + timedelta(hours=2))
            _, state = world.read()
            incoming = sum(b.input_kwh for b in state.batteries.values())
            outgoing = sum(b.output_kwh for b in state.batteries.values())
            residual = (
                state.import_kwh
                + state.pv_kwh
                + outgoing
                - state.export_kwh
                - state.load_kwh
                - incoming
            )
            assert abs(residual) < 1e-8
            print(
                f"PASS {slug}: adapters={len(reg.instances)} observations={len(readings)} source=twin writes=unavailable balance_residual_kwh={residual:.10f}"
            )
        finally:
            await reg.close()


if __name__ == "__main__":
    asyncio.run(smoke())
