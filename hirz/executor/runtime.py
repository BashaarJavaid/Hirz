"""Explicit refresh inputs, prediction evidence and remaining-horizon arithmetic."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Self

from pydantic import AwareDatetime, Field, model_validator

from hirz.graph.models import Model, ScheduleEvent
from hirz.pipeline.models import Action, Plan
from hirz.planner.models import PlannerInput, Schedule
from hirz.planner.replay import replay
from hirz.twin.physics import changed


class Thresholds(Model):
    temp_f: float = Field(default=1, ge=0, allow_inf_nan=False)
    soc: float = Field(default=0.02, ge=0, allow_inf_nan=False)
    power_kw: float = Field(default=0.25, ge=0, allow_inf_nan=False)


class IntervalEstimate(Model):
    start: AwareDatetime
    end: AwareDatetime
    electricity: Decimal
    wear: Decimal = Decimal(0)

    @model_validator(mode="after")
    def valid(self) -> Self:
        if (
            self.end <= self.start
            or not self.electricity.is_finite()
            or not self.wear.is_finite()
            or self.wear < 0
        ):
            raise ValueError("Invalid interval estimate")
        return self

    @property
    def reserved(self) -> Decimal:
        return max(Decimal(0), self.electricity + self.wear)


class RuntimeInputs(Model):
    workload: PlannerInput
    prediction_workload: PlannerInput | None = None
    prediction: Schedule
    thresholds: dict[str, Thresholds] = {}
    estimates: tuple[IntervalEstimate, ...]
    battery_terminal_kwh: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    appliance_completions: int | None = Field(default=None, ge=0)
    exhausted: tuple[str, ...] = ()
    retry_actions: tuple[str, ...] = ()
    feed_origin: AwareDatetime | None = None
    feed_hash: str | None = None
    calendar: tuple[ScheduleEvent, ...] | None = None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        accepted = self.prediction_workload or self.workload
        if len(self.prediction.controls) != len(accepted.slots):
            raise ValueError("Prediction must cover the supplied workload")
        if len(self.estimates) != len(accepted.slots) or any(
            (estimate.start, estimate.end) != (slot.start, slot.end)
            for estimate, slot in zip(self.estimates, accepted.slots, strict=True)
        ):
            raise ValueError("Estimates must cover the supplied forecast intervals")
        if self.workload.battery and self.battery_terminal_kwh is None:
            raise ValueError("Original terminal battery obligation is required")
        if self.workload.appliance and self.appliance_completions is None:
            raise ValueError("Original appliance completion obligation is required")
        return self

    def preserves(self, prior: "RuntimeInputs") -> None:
        if (
            self.battery_terminal_kwh != prior.battery_terminal_kwh
            or self.appliance_completions != prior.appliance_completions
            or (prior.workload.battery is not None and self.workload.battery is None)
            or (prior.workload.ev is not None and self.workload.ev is None)
            or not {z.entity for z in prior.workload.zones}
            <= {z.entity for z in self.workload.zones}
            or (
                prior.workload.appliance is not None
                and self.workload.appliance is None
                and not self.workload.appliance_completed
            )
        ):
            raise ValueError(
                "Replacement cannot erase original terminal obligations or required domains"
            )

    def validate_plan(self, plan: Plan) -> None:
        if (
            self.workload.household_id != plan.household_id
            or self.workload.slots[0].start != plan.horizon.start
            or self.workload.slots[-1].end != plan.horizon.end
        ):
            raise ValueError("Runtime input scope or horizon mismatch")

    @classmethod
    def from_schedule(
        cls,
        workload: PlannerInput,
        schedule: Schedule,
        *,
        prior: "RuntimeInputs | None" = None,
    ) -> "RuntimeInputs":
        # Prefix replays retain physical counters; they never grant authority.
        estimates = []
        last_wear = 0.0
        for i, slot in enumerate(workload.slots):
            part = slice_input(workload, workload.slots[0].start, slot.end)
            result = replay(
                part, changed(schedule, controls=schedule.controls[: i + 1])
            )
            estimates.append(
                IntervalEstimate(
                    start=slot.start,
                    end=slot.end,
                    electricity=Decimal(str(result.grid_kwh[-1] * slot.price)),
                    wear=Decimal(str(max(0, result.wear_usd - last_wear))),
                )
            )
            last_wear = result.wear_usd
        return cls(
            workload=workload,
            prediction=schedule,
            estimates=tuple(estimates),
            battery_terminal_kwh=prior.battery_terminal_kwh
            if prior
            else workload.battery.soc * workload.battery.capacity_kwh
            if workload.battery
            else None,
            appliance_completions=prior.appliance_completions
            if prior
            else workload.appliance.completions + 1
            if workload.appliance
            else None,
            thresholds=prior.thresholds if prior else {},
            exhausted=prior.exhausted if prior else (),
            retry_actions=prior.retry_actions if prior else (),
            feed_origin=prior.feed_origin if prior else workload.slots[0].start,
            feed_hash=prior.feed_hash if prior else None,
            calendar=prior.calendar if prior else None,
        )


def slice_input(p: PlannerInput, start: datetime, end: datetime) -> PlannerInput:
    if not p.slots[0].start <= start < end <= p.slots[-1].end:
        raise ValueError("Supplied forecasts do not cover the remaining horizon")
    indices = [i for i, s in enumerate(p.slots) if s.end > start and s.start < end]
    zones = []
    for z in p.zones:
        arrays = {
            name: tuple(getattr(z, name)[i] for i in indices)
            for name in (
                "lower",
                "upper",
                "targets",
                "baseline_targets",
                "occupants",
                "preferences",
                "held_targets",
                "held_modes",
            )
            if getattr(z, name)
        }
        zones.append(z.model_copy(update=arrays))
    return p.model_copy(
        update=dict(
            slots=tuple(
                changed(
                    p.slots[i],
                    start=max(start, p.slots[i].start),
                    end=min(end, p.slots[i].end),
                )
                for i in indices
            ),
            zones=tuple(zones),
            fixed_ev_kwh=tuple(
                None
                if p.fixed_ev_kwh[i] is None
                else (p.fixed_ev_kwh[i] or 0)
                * (
                    min(end, p.slots[i].end) - max(start, p.slots[i].start)
                ).total_seconds()
                / (p.slots[i].hours * 3600)
                for i in indices
            )
            if p.fixed_ev_kwh
            else (),
            fixed_battery_kw=tuple(p.fixed_battery_kw[i] for i in indices)
            if p.fixed_battery_kw
            else (),
        )
    )


def predicted(
    runtime: RuntimeInputs,
    at: datetime,
    *,
    applied: tuple[tuple[datetime, Action], ...] | None = None,
) -> dict[str, dict[str, Any]]:
    p = runtime.prediction_workload or runtime.workload
    ev, battery, appliance = p.ev, p.battery, p.appliance
    zones = tuple(z.physical for z in p.zones)
    if applied is not None:
        # The snapshot carries the previous applied controls. Only verified
        # dispatches change them; scheduled openings and endings do not.
        end = max(p.slots[0].start, min(at, p.slots[-1].end))
        changes: dict[datetime, list[Action]] = {}
        for dispatched, action in applied:
            # A same-instant observation predates the write and its verification.
            if p.slots[0].start <= dispatched <= end and dispatched < at:
                changes.setdefault(dispatched, []).append(action)
        edges = sorted(
            {p.slots[0].start, end, *changes} | {s.end for s in p.slots if s.end < end}
        )
        previous = edges[0]
        for edge in edges:
            if edge > previous:
                slot_index = next(
                    i for i, s in enumerate(p.slots) if s.start <= previous < s.end
                )
                slot = p.slots[slot_index]
                seconds = (edge - previous).total_seconds()
                ev = ev.advance(seconds) if ev else None
                battery = battery.advance(seconds) if battery else None
                appliance = appliance.advance(seconds) if appliance else None
                zones = tuple(
                    z.advance(
                        seconds,
                        slot.outdoor_f,
                        occupants=spec.occupants[slot_index],
                        irradiance_kw_m2=slot.irradiance,
                    )
                    for z, spec in zip(zones, p.zones, strict=True)
                )
            for action in changes.get(edge, []):
                entity, params = action.target.entity, action.params
                if entity == "ev" and ev and action.action_class == "energy.ev_charge":
                    ev = changed(ev, **params)
                elif (
                    entity == "home_battery"
                    and battery
                    and action.action_class == "energy.battery_dispatch"
                ):
                    battery = changed(battery, **params)
                elif (
                    entity == "dishwasher"
                    and appliance
                    and action.action_class == "energy.appliance_start"
                ):
                    if not appliance.running:
                        appliance = appliance.start_cycle()
                elif action.action_class == "energy.hvac_adjust":
                    zones = tuple(
                        changed(z, **params) if spec.entity == entity else z
                        for z, spec in zip(zones, p.zones, strict=True)
                    )
            previous = edge
    elif at > p.slots[0].start:
        at = min(at, p.slots[-1].end)
        part = slice_input(p, p.slots[0].start, at)
        # EV energy sets the slot's charge ceiling, not a fractional power level.
        # Retain that ceiling during a partial slot so prediction sees charging
        # until the actual energy is delivered, just like the bounded action.
        controls = runtime.prediction.controls[: len(part.slots)]
        r = replay(part, changed(runtime.prediction, controls=controls))
        ev, battery, appliance, zones = r.ev, r.battery, r.appliance, r.zones
    result = {
        z.entity: dict(temp_f=v.temp_f, target_f=v.target_f, mode=v.mode)
        for z, v in zip(p.zones, zones, strict=True)
    }
    if ev:
        result["ev"] = dict(
            soc=ev.soc,
            charging=ev.charging,
            plugged_in=ev.plugged_in,
            power_kw=ev.power_kw,
        )
    if battery:
        power = min(abs(battery.dispatch_kw), battery.power_kw)
        power = (
            (power if battery.soc > battery.reserve_soc else 0)
            if battery.dispatch_kw >= 0
            else (-power if battery.soc < 1 else 0)
        )
        result["home_battery"] = dict(
            soc=battery.soc, dispatch_kw=battery.dispatch_kw, power_kw=power
        )
    if appliance:
        result["dishwasher"] = dict(on=appliance.running, power_kw=appliance.power_kw)
    if any(s.solar_kw for s in p.slots):
        slot = next((s for s in p.slots if s.start <= at < s.end), p.slots[-1])
        result["solar"] = dict(power_kw=slot.solar_kw)
    return result


def deviates(
    actual: dict[str, Any], expected: dict[str, Any], thresholds: Thresholds
) -> bool:
    for name in ("temp_f", "soc", "power_kw"):
        if actual.get(name) is not None and expected.get(name) is not None:
            # Decimal keeps the documented exact threshold boundary out of float noise.
            if abs(Decimal(str(actual[name])) - Decimal(str(expected[name]))) > Decimal(
                str(getattr(thresholds, name))
            ):
                return True
    return any(
        actual.get(k) is not None and k in expected and actual[k] != expected[k]
        for k in (
            "available",
            "plugged_in",
            "charging",
            "dispatch_kw",
            "on",
            "mode",
            "target_f",
        )
    )
