"""Timer, immediate, and cheapest-slot schedules, without a solver."""

import math
from datetime import timedelta
from typing import Literal

from hirz.adapters.energy.real.tariff import CHICAGO
from hirz.planner.feedback import battery_envelope, comfort_envelope
from hirz.planner.models import Control, PlannerInput, Schedule
from hirz.planner.replay import effective
from hirz.twin.physics import changed


def appliance_windows(p: PlannerInput) -> dict[int, tuple[float, ...]]:
    if p.appliance is None:
        return {}
    _, _, release = effective(p)
    result = {}
    for i, slot in enumerate(p.slots):
        end = slot.start + timedelta(minutes=p.appliance.cycle_minutes)
        if slot.start < release or end > p.appliance_deadline or end > p.slots[-1].end:
            continue
        result[i] = tuple(
            max(0, (min(s.end, end) - max(s.start, slot.start)).total_seconds())
            / 3600
            * p.appliance.cycle_kwh
            / (p.appliance.cycle_minutes / 60)
            for s in p.slots
        )
    return result


def baseline(
    p: PlannerInput, method: Literal["timer", "immediate", "greedy"] = "greedy"
) -> Schedule:
    if method not in {"timer", "immediate", "greedy"}:
        raise ValueError("Unknown baseline")
    target, ev_start, _ = effective(p)
    ev = [0.0] * len(p.slots)
    need = (
        0 if p.ev is None else (target - p.ev.soc) * p.ev.capacity_kwh / p.ev.efficiency
    )
    eligible = [
        i
        for i, s in enumerate(p.slots)
        if p.ev is not None
        and s.start >= ev_start
        and s.end <= p.ev_deadline
        and (
            method != "timer"
            or s.start.astimezone(CHICAGO).hour >= 21
            or s.start.astimezone(CHICAGO).date()
            > p.slots[0].start.astimezone(CHICAGO).date()
        )
    ]
    if method == "greedy":
        eligible.sort(key=lambda i: (p.slots[i].price, i))
    for i in eligible:
        assert p.ev is not None
        ev[i] = min(max(0, need), p.ev.charger_kw * p.slots[i].hours)
        need -= ev[i]
    windows = appliance_windows(p)
    start = (
        min(
            windows,
            key=lambda i: (
                sum(e * s.price for e, s in zip(windows[i], p.slots, strict=True)),
                i,
            ),
        )
        if windows and method == "greedy"
        else min(windows, default=-1)
    )
    zones = [z.physical for z in p.zones]
    battery = p.battery
    controls = []
    net_load = []
    envelopes = [comfort_envelope(z, p.slots) for z in p.zones]
    for i, slot in enumerate(p.slots):
        targets: list[float] = []
        modes: list[Literal["heat", "cool", "off"]] = []
        load = (
            p.base_load_kw * slot.hours
            + ev[i]
            + (windows[start][i] if start >= 0 else 0)
        )
        for j, spec in enumerate(p.zones):
            zone = zones[j]
            target_f = spec.targets[i]
            lower, upper = envelopes[j]
            target_f = min(
                upper[i + 1], spec.upper[i], max(lower[i + 1], spec.lower[i], target_f)
            )
            passive = changed(zone, mode="off").advance(
                slot.hours * 3600,
                slot.outdoor_f,
                occupants=spec.occupants[i],
                irradiance_kw_m2=slot.irradiance,
            )
            mode: Literal["heat", "cool", "off"] = (
                "heat" if passive.temp_f < target_f else "cool"
            )
            after = changed(zone, target_f=target_f, mode=mode).advance(
                slot.hours * 3600,
                slot.outdoor_f,
                occupants=spec.occupants[i],
                irradiance_kw_m2=slot.irradiance,
            )
            load += after.electricity_kwh - zone.electricity_kwh
            zones[j] = after
            targets.append(target_f)
            modes.append(mode)
        net_load.append(load / slot.hours - slot.solar_kw)
        controls.append(
            Control(
                ev_kwh=ev[i],
                battery_kw=0,
                targets=tuple(targets),
                modes=tuple(modes),
                appliance_start=i == start,
            )
        )
    if battery is not None:
        eta = math.sqrt(battery.efficiency)
        opening = battery.soc * battery.capacity_kwh
        # Equal terminal energy: only store surplus that can serve forecast load
        # before the boundary. This uses the same forecast as every strategy.
        ceiling = [opening] * (len(p.slots) + 1)
        for i in range(len(p.slots) - 1, -1, -1):
            s = p.slots[i]
            hour = s.start.astimezone(CHICAGO).hour
            dischargeable = (
                min(max(0, net_load[i]), battery.power_kw) * s.hours / eta
                if 6 <= hour < 21
                else 0
            )
            ceiling[i] = min(battery.capacity_kwh, ceiling[i + 1] + dischargeable)
        if p.causal_controls:
            _, reachable = battery_envelope(p)
            ceiling = [min(a, b) for a, b in zip(ceiling, reachable, strict=True)]
        for i, slot in enumerate(p.slots):
            energy = battery.soc * battery.capacity_kwh
            local = slot.start.astimezone(CHICAGO)
            restore = local.hour >= 21 or local.hour < 6
            before_21 = (
                local.date() == p.slots[0].start.astimezone(CHICAGO).date()
                and local.hour < 21
            )
            net = net_load[i]
            if net < 0:
                dispatch = -min(
                    -net,
                    battery.power_kw,
                    max(0, ceiling[i + 1] - energy) / eta / slot.hours,
                )
            elif restore:
                dispatch = -min(
                    battery.power_kw, max(0, opening - energy) / eta / slot.hours
                )
            else:
                floor = (
                    battery.reserve_soc * battery.capacity_kwh if before_21 else opening
                )
                dispatch = min(
                    net, battery.power_kw, max(0, energy - floor) * eta / slot.hours
                )
            battery = changed(battery, dispatch_kw=dispatch).advance(slot.hours * 3600)
            controls[i] = changed(controls[i], battery_kw=dispatch)
    return Schedule(controls=tuple(controls), method=method)
