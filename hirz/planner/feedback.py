"""Causal hypothetical device controls; never an execution or approval path.

The twin holds environmental observations constant within each quarter hour.
EV/cycle completion splits that interval so metering cannot conceal an export.
Only the current observation is passed to the controller; future inputs below
are the original forecast, declared comfort windows and installed PV bounds.
"""

import math
from datetime import timedelta
from typing import Literal

from hirz.adapters.energy.real.tariff import CHICAGO
from hirz.planner.models import PlannerInput, Replay, Schedule, Slot, Zone
from hirz.planner.replay import replay
from hirz.twin.physics import changed


def forecast_replay(p: PlannerInput, schedule: Schedule) -> Replay:
    checked = replay(p, schedule)
    if checked.valid and p.causal_controls:
        return simulate(p, schedule, p.slots)
    return checked


def battery_envelope(p: PlannerInput) -> tuple[list[float], list[float]]:
    """Energy at each boundary that can still reach the opening reserve."""
    if p.battery is None:
        return [0.0] * (len(p.slots) + 1), [0.0] * (len(p.slots) + 1)
    battery = p.battery
    opening = battery.soc * battery.capacity_kwh
    eta = math.sqrt(battery.efficiency)
    upper = [opening] * (len(p.slots) + 1)
    lower = [opening] * (len(p.slots) + 1)
    for k in range(len(p.slots) - 1, -1, -1):
        s = p.slots[k]
        guaranteed = (
            0 if s.solar_max_kw is None else max(0, p.base_load_kw - s.solar_max_kw)
        )
        upper[k] = min(
            battery.capacity_kwh,
            upper[k + 1] + min(battery.power_kw, guaranteed) * s.hours / eta,
        )
        lower[k] = max(
            battery.reserve_soc * battery.capacity_kwh,
            lower[k + 1] - battery.power_kw * eta * s.hours,
        )
    return lower, upper


def comfort_envelope(
    spec: Zone, slots: tuple[Slot, ...], *, observation: Slot | None = None
) -> tuple[list[float], list[float]]:
    """Prepare for a tightening window at its declared occupied target.

    This uses existing target settings as arrival waypoints, leaving a margin
    inside the hard band without changing power, capacity or comfort limits.
    Forecast generation uses forecast weather; feedback holds the current
    observation constant. Neither consumes a future realized observation.
    """
    z = spec.physical
    mass, resistance = z.thermal_mass_kwh_per_f, z.resistance_f_per_kw
    lower, upper = [*spec.lower, spec.end_lower], [*spec.upper, spec.end_upper]
    for t in range(1, len(slots)):
        if lower[t] > spec.lower[t - 1] or upper[t] < spec.upper[t - 1]:
            lower[t] = upper[t] = spec.targets[t]
    for t in range(len(slots) - 1, -1, -1):
        h = slots[t].hours
        w = slots[t] if observation is None else observation
        a = 1 - h / (mass * resistance)
        b = (
            h
            / mass
            * (
                w.outdoor_f / resistance
                + spec.occupants[t] * z.occupant_kw
                + w.irradiance * z.solar_gain_area_m2
            )
        )
        power = z.hvac_kw * h / mass
        if lower[t + 1] > upper[t + 1] or (
            a == 0 and (b + power < lower[t + 1] or b - power > upper[t + 1])
        ):
            lower[t], upper[t] = spec.upper[t] + 1, spec.lower[t] - 1
        elif a != 0:
            lo, hi = (lower[t + 1] - b - power) / a, (upper[t + 1] - b + power) / a
            if a < 0:
                lo, hi = hi, lo
            lower[t], upper[t] = max(lower[t], lo), min(upper[t], hi)
    return lower, upper


def simulate(
    p: PlannerInput, schedule: Schedule, observations: tuple[Slot, ...]
) -> Replay:
    if len(observations) != len(p.slots) or any(
        (a.start, a.end) != (b.start, b.end)
        for a, b in zip(p.slots, observations, strict=True)
    ):
        raise ValueError("Observations must match the planned interval boundaries")
    if len(schedule.controls) != len(p.slots):
        raise ValueError("Schedule does not cover the horizon")
    # Split at known device stop times, without consulting realized weather/load.
    slots, controls, indices = [], [], []
    cycle_end = None
    for i, (slot, control) in enumerate(zip(p.slots, schedule.controls, strict=True)):
        if control.appliance_start and p.appliance:
            cycle_end = slot.start + timedelta(minutes=p.appliance.cycle_minutes)
        ev_end = slot.start + timedelta(
            hours=control.ev_kwh / p.ev.charger_kw if p.ev else 0
        )
        edges = sorted(
            {slot.start, slot.end}
            | {
                t
                for t in (ev_end, cycle_end)
                if t is not None and slot.start < t < slot.end
            }
        )
        for left, right in zip(edges, edges[1:]):
            slots.append(changed(slot, start=left, end=right))
            indices.append(i)
            controls.append(
                changed(
                    control,
                    ev_kwh=0
                    if not p.ev or left >= ev_end
                    else p.ev.charger_kw * (right - left).total_seconds() / 3600,
                    appliance_start=control.appliance_start and left == slot.start,
                )
            )
    specs = tuple(
        changed(
            z,
            lower=tuple(z.lower[i] for i in indices),
            upper=tuple(z.upper[i] for i in indices),
            targets=tuple(z.targets[i] for i in indices),
            occupants=tuple(z.occupants[i] for i in indices),
            preferences=tuple(z.preferences[i] for i in indices)
            if z.preferences
            else (),
            held_targets=tuple(z.held_targets[i] for i in indices)
            if z.held_targets
            else (),
            held_modes=tuple(z.held_modes[i] for i in indices) if z.held_modes else (),
        )
        for z in p.zones
    )
    expanded = changed(p, slots=tuple(slots), zones=specs)
    battery, appliance = p.battery, p.appliance
    zones = [z.physical for z in p.zones]
    opening = 0 if battery is None else battery.soc * battery.capacity_kwh
    eta = 1 if battery is None else math.sqrt(battery.efficiency)
    floors, ceilings = battery_envelope(expanded)
    envelopes: dict[tuple[int, float, float], tuple[list[float], list[float]]] = {}
    applied, realized = [], []
    for k, (slot, control, i) in enumerate(zip(slots, controls, indices, strict=True)):
        observed = observations[i]  # No later realized slot is read by this step.
        current = changed(
            slot,
            outdoor_f=observed.outdoor_f,
            solar_kw=observed.solar_kw,
            irradiance=observed.irradiance,
            price=observed.price,
        )
        realized.append(current)
        dt = slot.hours
        load = p.base_load_kw + control.ev_kwh / dt
        if appliance:
            if control.appliance_start:
                appliance = appliance.start_cycle()
            after = appliance.advance(dt * 3600)
            load += (after.energy_kwh - appliance.energy_kwh) / dt
            appliance = after
        targets, modes = [], []
        for j, (zone, spec) in enumerate(zip(zones, specs, strict=True)):
            key = (j, current.outdoor_f, current.irradiance)
            if key not in envelopes:
                envelopes[key] = comfort_envelope(
                    spec, tuple(slots), observation=current
                )
            lower, upper = envelopes[key]
            lo, hi = max(spec.lower[k], lower[k + 1]), min(spec.upper[k], upper[k + 1])
            target = min(hi, max(lo, control.targets[j]))
            passive = changed(zone, mode="off").advance(
                dt * 3600,
                current.outdoor_f,
                occupants=spec.occupants[k],
                irradiance_kw_m2=current.irradiance,
            )
            mode: Literal["heat", "cool", "off"] = (
                "heat" if passive.temp_f < target else "cool"
            )
            if spec.held_targets and spec.held_targets[k] is not None:
                target = float(spec.held_targets[k] or 0)
                mode = spec.held_modes[k] or "off"
            after_zone = changed(zone, mode=mode, target_f=target).advance(
                dt * 3600,
                current.outdoor_f,
                occupants=spec.occupants[k],
                irradiance_kw_m2=current.irradiance,
            )
            load += (after_zone.electricity_kwh - zone.electricity_kwh) / dt
            zones[j] = after_zone
            targets.append(target)
            modes.append(mode)
        net = load - current.solar_kw
        dispatch = control.battery_kw
        if battery:
            energy = battery.soc * battery.capacity_kwh
            local = slot.start.astimezone(CHICAGO)
            if schedule.method in {"timer", "immediate", "greedy"}:
                if net < 0:
                    dispatch = net
                elif local.hour >= 21 or local.hour < 6:
                    dispatch = -max(0, opening - energy) / eta / dt
                else:
                    before_21 = (
                        local.date() == slots[0].start.astimezone(CHICAGO).date()
                        and local.hour < 21
                    )
                    reserve = (
                        battery.reserve_soc * battery.capacity_kwh
                        if before_21
                        else opening
                    )
                    dispatch = min(net, max(0, energy - reserve) * eta / dt)
            floor, energy_ceiling = floors[k + 1], ceilings[k + 1]
            # Bounds on internal energy change preserve terminal reachability.
            delta = -dispatch * dt / (eta if dispatch >= 0 else 1 / eta)
            delta = min(energy_ceiling - energy, max(floor - energy, delta))
            dispatch = -delta * (eta if delta <= 0 else 1 / eta) / dt
            dispatch = min(
                max(0, net), battery.power_kw, max(-battery.power_kw, dispatch)
            )
            battery = changed(battery, dispatch_kw=dispatch).advance(dt * 3600)
        applied.append(
            changed(
                control, battery_kw=dispatch, targets=tuple(targets), modes=tuple(modes)
            )
        )
    result = replay(
        changed(expanded, slots=tuple(realized)),
        changed(schedule, controls=tuple(applied)),
    )
    # Public daily metrics retain the original quarter-hour alignment.
    imports, exports = [0.0] * len(p.slots), [0.0] * len(p.slots)
    for i, incoming, outgoing in zip(
        indices, result.grid_kwh, result.export_kwh, strict=True
    ):
        imports[i] += incoming
        exports[i] += outgoing
    return changed(
        result,
        grid_kwh=tuple(imports),
        export_kwh=tuple(exports),
        applied_controls=tuple(applied),
        control_boundaries=tuple(s.start for s in slots) + (slots[-1].end,),
    )
