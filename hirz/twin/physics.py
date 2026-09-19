"""Pure physics transitions. Controls are hypothetical, never household actions."""

import math
from typing import Annotated, Literal, Self, TypeVar

from pydantic import Field, model_validator

from hirz.adapters.base import AdapterError
from hirz.graph.models import Model

Positive = Annotated[float, Field(gt=0)]
Nonnegative = Annotated[float, Field(ge=0)]
Fraction = Annotated[float, Field(ge=0, le=1)]
Efficiency = Annotated[float, Field(gt=0, le=1)]
T = TypeVar("T", bound=Model)


def changed(model: T, **values: object) -> T:
    return type(model).model_validate(model.model_dump(exclude_unset=True) | values)


def hours(seconds: float) -> float:
    if not math.isfinite(seconds) or seconds < 0:
        raise AdapterError("Duration must be finite and nonnegative.")
    return seconds / 3600


class EV(Model):
    capacity_kwh: Positive = 75
    charger_kw: Positive = 7.4
    efficiency: Efficiency = 0.92
    soc: Fraction
    plugged_in: bool
    charging: bool
    charge_limit: Fraction
    grid_kwh: Nonnegative = 0
    stored_kwh: Nonnegative = 0
    loss_kwh: Nonnegative = 0
    driven_kwh: Nonnegative = 0

    def advance(self, seconds: float) -> Self:
        remaining = hours(seconds)
        soc = self.soc
        if not self.plugged_in or not self.charging or soc >= self.charge_limit:
            return self
        rate = self.charger_kw * self.efficiency / self.capacity_kwh
        # Integrate the linear taper analytically, including the 80% boundary.
        if soc < 0.8:
            duration = min(remaining, (min(0.8, self.charge_limit) - soc) / rate)
            soc += duration * rate
            remaining -= duration
        if remaining > 0 and soc < self.charge_limit:
            equilibrium = 3.8 / 3.5
            soc = min(
                self.charge_limit,
                equilibrium - (equilibrium - soc) * math.exp(-3.5 * rate * remaining),
            )
        stored = (soc - self.soc) * self.capacity_kwh
        grid = stored / self.efficiency
        return changed(
            self,
            soc=soc,
            stored_kwh=self.stored_kwh + stored,
            grid_kwh=self.grid_kwh + grid,
            loss_kwh=self.loss_kwh + grid - stored,
        )

    def drive(self, energy_kwh: float) -> Self:
        if (
            not math.isfinite(energy_kwh)
            or energy_kwh < 0
            or self.plugged_in
            or energy_kwh > self.soc * self.capacity_kwh
        ):
            raise AdapterError("Drive requires an unplugged EV with sufficient energy.")
        return changed(
            self,
            soc=self.soc - energy_kwh / self.capacity_kwh,
            driven_kwh=self.driven_kwh + energy_kwh,
        )

    @property
    def power_kw(self) -> float:
        if not self.plugged_in or not self.charging or self.soc >= self.charge_limit:
            return 0
        return self.charger_kw * (1 if self.soc <= 0.8 else 3.8 - 3.5 * self.soc)

    def seconds_to_limit(self) -> float | None:
        if not self.power_kw:
            return None
        rate = self.charger_kw * self.efficiency / self.capacity_kwh
        below = max(0, min(0.8, self.charge_limit) - self.soc) / rate
        above = 0.0
        if self.charge_limit > 0.8:
            equilibrium = 3.8 / 3.5
            above = math.log(
                (equilibrium - max(self.soc, 0.8)) / (equilibrium - self.charge_limit)
            ) / (3.5 * rate)
        return (below + above) * 3600


class Battery(Model):
    capacity_kwh: Positive = 13.5
    power_kw: Positive = 5
    efficiency: Efficiency = 0.9
    reserve_soc: Fraction = 0.1
    soc: Fraction
    dispatch_kw: float
    input_kwh: Nonnegative = 0
    output_kwh: Nonnegative = 0
    loss_kwh: Nonnegative = 0
    throughput_kwh: Nonnegative = 0

    def advance(self, seconds: float) -> Self:
        duration = hours(seconds)
        eta = math.sqrt(self.efficiency)
        requested = min(abs(self.dispatch_kw), self.power_kw) * duration
        if self.dispatch_kw >= 0:
            stored = min(
                requested / eta, max(0, self.soc - self.reserve_soc) * self.capacity_kwh
            )
            outgoing = stored * eta
            return changed(
                self,
                soc=max(0, self.soc - stored / self.capacity_kwh),
                output_kwh=self.output_kwh + outgoing,
                loss_kwh=self.loss_kwh + stored - outgoing,
                throughput_kwh=self.throughput_kwh + stored,
            )
        stored = min(requested * eta, (1 - self.soc) * self.capacity_kwh)
        incoming = stored / eta
        return changed(
            self,
            soc=min(1, self.soc + stored / self.capacity_kwh),
            input_kwh=self.input_kwh + incoming,
            loss_kwh=self.loss_kwh + incoming - stored,
            throughput_kwh=self.throughput_kwh + stored,
        )

    @property
    def cycles(self) -> float:
        return self.throughput_kwh / (2 * self.capacity_kwh)

    def seconds_to_limit(self) -> float | None:
        power = min(abs(self.dispatch_kw), self.power_kw)
        if not power:
            return None
        eta = math.sqrt(self.efficiency)
        energy = (
            max(0, self.soc - self.reserve_soc) * self.capacity_kwh * eta
            if self.dispatch_kw > 0
            else (1 - self.soc) * self.capacity_kwh / eta
        )
        return energy / power * 3600 if energy else None


class ThermalZone(Model):
    thermal_mass_kwh_per_f: Positive = 0.46875
    resistance_f_per_kw: Positive = 64
    hvac_kw: Positive = 3
    cop: Positive = 1
    occupant_kw: Nonnegative = 0.1
    solar_gain_area_m2: Nonnegative
    temp_f: float
    target_f: float
    mode: Literal["heat", "cool", "off"]
    electricity_kwh: Nonnegative = 0
    heat_kwh: float = 0
    passive_kwh: float = 0

    def advance(
        self,
        seconds: float,
        outdoor_f: float,
        *,
        occupants: int = 0,
        irradiance_kw_m2: float = 0,
        coupling_kw: float = 0,
    ) -> Self:
        duration = hours(seconds)
        if (
            occupants < 0
            or not all(
                math.isfinite(v) for v in (outdoor_f, irradiance_kw_m2, coupling_kw)
            )
            or irradiance_kw_m2 < 0
        ):
            raise AdapterError("Invalid thermal inputs.")
        passive = (
            occupants * self.occupant_kw
            + irradiance_kw_m2 * self.solar_gain_area_m2
            + coupling_kw
            - (self.temp_f - outdoor_f) / self.resistance_f_per_kw
        )
        needed = (
            self.target_f - self.temp_f
        ) * self.thermal_mass_kwh_per_f - passive * duration
        heat = (
            min(self.hvac_kw * duration, max(0, needed))
            if self.mode == "heat"
            else max(-self.hvac_kw * duration, min(0, needed))
            if self.mode == "cool"
            else 0
        )
        return changed(
            self,
            temp_f=self.temp_f
            + (passive * duration + heat) / self.thermal_mass_kwh_per_f,
            electricity_kwh=self.electricity_kwh + abs(heat) / self.cop,
            heat_kwh=self.heat_kwh + heat,
            passive_kwh=self.passive_kwh + passive * duration,
        )


PROFILES = {"dishwasher": (105, 1.2), "laundry": (60, 0.9), "dryer": (50, 2.5)}


class Appliance(Model):
    cycle_minutes: Positive
    cycle_kwh: Positive
    noise_dba: Nonnegative
    running: bool
    elapsed_seconds: Nonnegative = 0
    energy_kwh: Nonnegative = 0
    completions: Annotated[int, Field(ge=0)] = 0

    @model_validator(mode="after")
    def duration(self) -> Self:
        if self.elapsed_seconds > self.cycle_minutes * 60:
            raise ValueError("Appliance elapsed time exceeds cycle.")
        if self.running and self.elapsed_seconds == self.cycle_minutes * 60:
            raise ValueError("Completed cycle cannot be running.")
        return self

    def start_cycle(self) -> Self:
        if self.running:
            raise AdapterError("Appliance is already running.")
        return changed(self, running=True, elapsed_seconds=0)

    def advance(self, seconds: float) -> Self:
        hours(seconds)
        if not self.running:
            return self
        elapsed = min(seconds, self.cycle_minutes * 60 - self.elapsed_seconds)
        total = self.elapsed_seconds + elapsed
        done = total >= self.cycle_minutes * 60
        return changed(
            self,
            elapsed_seconds=total,
            running=not done,
            energy_kwh=self.energy_kwh
            + elapsed / (self.cycle_minutes * 60) * self.cycle_kwh,
            completions=self.completions + int(done),
        )

    @property
    def power_kw(self) -> float:
        return self.cycle_kwh / (self.cycle_minutes / 60) if self.running else 0
