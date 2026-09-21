"""Read-only planner contracts; physical parameters use the existing twin models."""

from datetime import datetime, timedelta
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from hirz.adapters.energy.real.tariff import CHICAGO
from hirz.graph.models import Model, utc
from hirz.pipeline.models import Action, Plan, PlanConstraint, Requester
from hirz.twin.physics import EV, Appliance, Battery, ThermalZone

ENERGY_TOL = 1e-6
TEMP_TOL = 1e-4
Strategy = Literal["milp", "timer", "immediate", "greedy"]


def boundaries(start: datetime, end: datetime | None = None) -> tuple[datetime, ...]:
    start = utc(start)
    if end is None:
        local = start.astimezone(CHICAGO)
        end = datetime.combine(
            local.date() + timedelta(days=1), datetime.min.time(), CHICAGO
        ).replace(hour=17, minute=30)
    end = utc(end)
    if not start < end <= start + timedelta(hours=25):
        raise ValueError("Planner horizon must be positive and at most 25 hours")
    result = [start]
    at = start.replace(
        minute=start.minute // 15 * 15, second=0, microsecond=0
    ) + timedelta(minutes=15)
    while at < end:
        result.append(at)
        at += timedelta(minutes=15)
    return (*result, end)


class Slot(Model):
    start: AwareDatetime
    end: AwareDatetime
    price: float = Field(allow_inf_nan=False)  # dollars per grid kWh
    outdoor_f: float = Field(allow_inf_nan=False)
    solar_kw: float = Field(ge=0, allow_inf_nan=False)
    # Installed PV geometry at zero cloud, known before the decision. None
    # means no guaranteed future self-consumption, not a perfect PV forecast.
    solar_max_kw: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    irradiance: float = Field(default=0, ge=0, allow_inf_nan=False)
    price_source: AwareDatetime | None = None
    weather_source: AwareDatetime | None = None

    @property
    def hours(self) -> float:
        return (utc(self.end) - utc(self.start)).total_seconds() / 3600


class Zone(Model):
    entity: str
    physical: ThermalZone
    lower: tuple[float, ...]
    upper: tuple[float, ...]
    targets: tuple[float, ...]
    occupants: tuple[int, ...]
    preferences: tuple[float | None, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )
    held_targets: tuple[float | None, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )
    held_modes: tuple[Literal["heat", "cool", "off"] | None, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )
    end_lower: float = 66
    end_upper: float = 76


class MemberConstraint(Model):
    provenance: PlanConstraint
    kind: Literal[
        "ev_not_before",
        "ev_target",
        "appliance_not_before",
        "ev_ceiling",
        "ev_deadline",
        "appliance_deadline",
        "temperature",
        "temperature_band",
        "manual_hold",
    ]
    starts_at: AwareDatetime | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    ends_at: AwareDatetime | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    at: AwareDatetime | None = None
    value: float | None = Field(default=None, ge=0, le=0.8)

    @model_validator(mode="after")
    def payload(self) -> Self:
        if self.kind in {"ev_target", "ev_ceiling"} and self.value is None:
            raise ValueError("Constraint value is missing")
        if (
            self.kind
            in {
                "ev_not_before",
                "ev_deadline",
                "appliance_not_before",
                "appliance_deadline",
            }
            and self.at is None
        ):
            raise ValueError("Constraint time is missing")
        return self


class PlannerInput(Model):
    household_id: UUID
    requester: Requester
    slots: tuple[Slot, ...] = Field(min_length=1)
    ev: EV | None
    ev_target: float = Field(ge=0, le=0.8)
    ev_deadline: AwareDatetime
    battery: Battery | None
    zones: tuple[Zone, ...]
    appliance: Appliance | None
    appliance_release: AwareDatetime
    appliance_deadline: AwareDatetime
    base_load_kw: float = Field(ge=0, allow_inf_nan=False)
    wear_per_kwh: float = Field(default=0.01, ge=0, allow_inf_nan=False)
    causal_controls: bool = False  # Explicit hypothetical study-device behavior.
    constraints: tuple[MemberConstraint, ...] = ()
    provenance: tuple[str, ...]

    @model_validator(mode="after")
    def consistency(self) -> Self:
        n = len(self.slots)
        for i, slot in enumerate(self.slots):
            if not 0 < slot.hours <= 0.25 or (
                i and utc(self.slots[i - 1].end) != utc(slot.start)
            ):
                raise ValueError(
                    "Slots must be consecutive and at most fifteen minutes"
                )
        for zone in self.zones:
            for values in (zone.preferences, zone.held_targets, zone.held_modes):
                if values and len(values) != n:
                    raise ValueError("Coordinator arrays must cover every slot")
            if bool(zone.held_targets) != bool(zone.held_modes):
                raise ValueError("Hold needs target and mode")
            ended = False
            for target, mode in zip(zone.held_targets, zone.held_modes, strict=True):
                if (target is None) != (mode is None) or (ended and target is not None):
                    raise ValueError("Active manual holds must form a prefix")
                ended = ended or target is None
            if any(
                len(v) != n
                for v in (zone.lower, zone.upper, zone.targets, zone.occupants)
            ):
                raise ValueError("Zone arrays must cover every slot")
            if any(
                lo > hi or not lo <= target <= hi
                for lo, hi, target in zip(
                    zone.lower, zone.upper, zone.targets, strict=True
                )
            ):
                raise ValueError("Invalid comfort bounds")
        if len({z.entity for z in self.zones}) != len(self.zones):
            raise ValueError("Duplicate zone")
        if self.ev and (self.ev.soc > self.ev_target or not self.ev.plugged_in):
            raise ValueError(
                "EV must be plugged in with opening SoC at or below target"
            )
        if self.battery and self.battery.soc < self.battery.reserve_soc:
            raise ValueError("Battery opening energy is below reserve")
        if self.appliance and self.appliance.running:
            raise ValueError("New workload requires an idle appliance")
        if any(
            utc(c.provenance.recorded_at) > utc(self.slots[0].start)
            for c in self.constraints
        ):
            raise ValueError("Future constraints are not planner inputs")
        return self


class Control(Model):
    ev_kwh: float = Field(ge=0, allow_inf_nan=False)
    battery_kw: float = Field(allow_inf_nan=False)
    targets: tuple[float, ...]
    modes: tuple[Literal["heat", "cool", "off"], ...]
    appliance_start: bool


class Schedule(Model):
    controls: tuple[Control, ...]
    method: Literal["milp", "timeout_incumbent", "timer", "immediate", "greedy"]


class Replay(Model):
    valid: bool
    reasons: tuple[str, ...]
    electricity_usd: float
    wear_usd: float
    grid_kwh: tuple[float, ...]
    export_kwh: tuple[float, ...]
    ev_delivered_kwh: float
    battery_end_kwh: float | None
    battery_loss_kwh: float
    ev_loss_kwh: float
    throughput_kwh: float
    comfort_violations_minutes: float
    appliance_completions: int
    ev: EV | None
    battery: Battery | None
    zones: tuple[ThermalZone, ...]
    appliance: Appliance | None
    applied_controls: tuple[Control, ...] = ()
    control_boundaries: tuple[AwareDatetime, ...] = ()


class SolverDiagnostics(Model):
    status: str
    elapsed_seconds: float
    gap: float | None = None
    message: str = ""
    binding: tuple[str, ...] = ()


class PlannerResult(Model):
    plan: Plan | None
    actions: tuple[Action, ...] = ()
    schedule: Schedule | None
    replay: Replay | None
    baselines: dict[str, Replay] = {}
    diagnostics: SolverDiagnostics
    blocking_constraints: tuple[PlanConstraint, ...] = ()
    unresolved_conflict: bool = False
    previous_feasible_reference: Plan | None = None
    reference_label: str | None = None
    input_hash: str
    provenance: tuple[str, ...]
