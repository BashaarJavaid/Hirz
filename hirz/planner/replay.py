"""Validate hypothetical controls using the same pure transitions as the twin."""

from datetime import datetime

from hirz.planner.models import ENERGY_TOL, TEMP_TOL, PlannerInput, Replay, Schedule
from hirz.twin.physics import changed


def effective(p: PlannerInput) -> tuple[float, datetime, datetime]:
    target = p.ev_target
    ev_start = p.slots[0].start
    release = p.appliance_release
    for c in p.constraints:
        if c.kind == "ev_target":
            assert c.value is not None
            target = c.value
        elif c.kind == "ev_not_before":
            assert c.at is not None
            ev_start = max(ev_start, c.at)
        elif c.kind == "appliance_not_before":
            assert c.at is not None
            release = max(release, c.at)
    return target, ev_start, release


def replay(p: PlannerInput, schedule: Schedule) -> Replay:
    if len(schedule.controls) != len(p.slots):
        raise ValueError("Schedule does not cover the horizon")
    ev, battery, appliance = p.ev, p.battery, p.appliance
    zones = [z.physical for z in p.zones]
    imports, exports, reasons = [], [], []
    cost = comfort = 0.0
    target, ev_start, release = effective(p)
    for i, (slot, control) in enumerate(zip(p.slots, schedule.controls, strict=True)):
        if len(control.targets) != len(zones) or len(control.modes) != len(zones):
            raise ValueError("Controls must cover every zone")
        for j, held_spec in enumerate(p.zones):
            if (
                held_spec.held_targets
                and held_spec.held_targets[i] is not None
                and (
                    abs(control.targets[j] - float(held_spec.held_targets[i] or 0))
                    > TEMP_TOL
                    or control.modes[j] != held_spec.held_modes[i]
                )
            ):
                reasons.append("Manual thermostat hold changed")
        seconds = slot.hours * 3600
        load = p.base_load_kw * slot.hours
        if ev is not None:
            if control.ev_kwh > ENERGY_TOL and (
                slot.start < ev_start or slot.end > p.ev_deadline
            ):
                reasons.append("EV charging outside allowed window")
            opening = ev.grid_kwh
            limit = min(0.8, ev.soc + control.ev_kwh * ev.efficiency / ev.capacity_kwh)
            ev = changed(ev, charging=control.ev_kwh > 0, charge_limit=limit).advance(
                seconds
            )
            used = ev.grid_kwh - opening
            if abs(used - control.ev_kwh) > ENERGY_TOL:
                reasons.append("EV control exceeds charging power or taper limit")
            load += used
            for c in p.constraints:
                if (
                    c.kind == "ev_ceiling"
                    and (c.starts_at is None or slot.start >= c.starts_at)
                    and (c.ends_at is None or slot.start < c.ends_at)
                    and c.value is not None
                    and ev.soc > c.value + ENERGY_TOL
                ):
                    reasons.append("EV ceiling exceeded")
        elif control.ev_kwh > ENERGY_TOL:
            reasons.append("EV control without EV")
        if appliance is not None:
            assert p.appliance is not None
            if control.appliance_start:
                if slot.start < release or appliance.running:
                    reasons.append(
                        "Appliance start outside allowed window or overlaps cycle"
                    )
                else:
                    appliance = appliance.start_cycle()
            before = appliance.energy_kwh
            appliance = appliance.advance(seconds)
            load += appliance.energy_kwh - before
            if slot.end >= p.appliance_deadline and (
                appliance.running
                or appliance.completions != p.appliance.completions + 1
            ):
                reasons.append("Appliance deadline or workload missed")
        elif control.appliance_start:
            reasons.append("Appliance start without appliance")
        for j, (zone, spec) in enumerate(zip(zones, p.zones, strict=True)):
            after = changed(
                zone, target_f=control.targets[j], mode=control.modes[j]
            ).advance(
                seconds,
                slot.outdoor_f,
                occupants=spec.occupants[i],
                irradiance_kw_m2=slot.irradiance,
            )
            if (
                min(zone.temp_f, after.temp_f) < spec.lower[i] - TEMP_TOL
                or max(zone.temp_f, after.temp_f) > spec.upper[i] + TEMP_TOL
            ):
                comfort += seconds / 60
            load += after.electricity_kwh - zone.electricity_kwh
            zones[j] = after
        incoming = outgoing = 0.0
        if battery is not None:
            if abs(control.battery_kw) > battery.power_kw + ENERGY_TOL:
                reasons.append("Battery power exceeded")
            after_battery = changed(battery, dispatch_kw=control.battery_kw).advance(
                seconds
            )
            incoming = after_battery.input_kwh - battery.input_kwh
            outgoing = after_battery.output_kwh - battery.output_kwh
            if abs(incoming - outgoing + control.battery_kw * slot.hours) > ENERGY_TOL:
                reasons.append("Battery energy bounds exceeded")
            battery = after_battery
        elif abs(control.battery_kw) > ENERGY_TOL:
            reasons.append("Battery control without battery")
        net = load + incoming - outgoing - slot.solar_kw * slot.hours
        if outgoing > ENERGY_TOL and net < -ENERGY_TOL:
            reasons.append("Battery discharge to grid prohibited")
        imports.append(max(0, net))
        exports.append(max(0, -net))
        cost += max(0, net) * slot.price
    delivered = 0.0 if ev is None or p.ev is None else ev.stored_kwh - p.ev.stored_kwh
    if (
        ev is not None
        and p.ev is not None
        and abs(delivered - (target - p.ev.soc) * ev.capacity_kwh) > ENERGY_TOL
    ):
        reasons.append("Unequal EV delivery")
    for zone, spec in zip(zones, p.zones, strict=True):
        if not spec.end_lower - TEMP_TOL <= zone.temp_f <= spec.end_upper + TEMP_TOL:
            reasons.append("Terminal comfort band missed")
    if comfort > 0:
        reasons.append("Hard comfort band missed")
    if (
        battery is not None
        and p.battery is not None
        and abs((battery.soc - p.battery.soc) * battery.capacity_kwh) > ENERGY_TOL
    ):
        reasons.append("Ending battery energy differs from opening energy")
    completions = (
        0
        if appliance is None or p.appliance is None
        else appliance.completions - p.appliance.completions
    )
    if p.appliance is not None and completions != 1:
        reasons.append("Incomplete or extra appliance workload")
    throughput = (
        0
        if battery is None or p.battery is None
        else battery.throughput_kwh - p.battery.throughput_kwh
    )
    return Replay(
        valid=not reasons,
        reasons=tuple(dict.fromkeys(reasons)),
        electricity_usd=cost,
        wear_usd=throughput * p.wear_per_kwh,
        grid_kwh=tuple(imports),
        export_kwh=tuple(exports),
        ev_delivered_kwh=delivered,
        battery_end_kwh=None if battery is None else battery.soc * battery.capacity_kwh,
        battery_loss_kwh=0
        if battery is None or p.battery is None
        else battery.loss_kwh - p.battery.loss_kwh,
        ev_loss_kwh=0 if ev is None or p.ev is None else ev.loss_kwh - p.ev.loss_kwh,
        throughput_kwh=throughput,
        comfort_violations_minutes=comfort,
        appliance_completions=completions,
        ev=ev,
        battery=battery,
        zones=tuple(zones),
        appliance=appliance,
    )
