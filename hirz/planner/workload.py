"""Approved synthetic daily workload, with explicit reusable physical state."""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID

from hirz.adapters.energy.real.tariff import CHICAGO, load_tariff
from hirz.pipeline.models import Requester
from hirz.planner.history import counterfactual_rate
from hirz.planner.models import PlannerInput, Slot, Zone, boundaries
from hirz.twin.environment import Solar
from hirz.twin.physics import EV, Appliance, Battery, ThermalZone

Configuration = Literal["solar_battery_ev", "ev_only", "solar_battery"]
CONFIGURATIONS: tuple[Configuration, ...] = (
    "solar_battery_ev",
    "ev_only",
    "solar_battery",
)


def comfort(at: datetime, entity: str) -> tuple[float, float, float]:
    local = at.astimezone(CHICAGO)
    minute = local.hour * 60 + local.minute
    if entity == "hvac.living_room":
        if 1050 <= minute < 1140:
            return 68, 72, 70
        if 1140 <= minute < 1380:
            return 71, 73, 72
        return 66, 76, 70
    if minute >= 1380 or minute < 420:
        return 71, 73, 72
    return 66, 76, 72


def workload(
    slots: tuple[Slot, ...],
    configuration: Configuration = "solar_battery_ev",
    *,
    household_id: UUID = UUID("413ef6f6-f221-4d32-aaee-c0b89e1846d7"),
    requester: Requester | None = None,
    ev: EV | None = None,
    battery: Battery | None = None,
    zones: tuple[ThermalZone, ...] | None = None,
    appliance: Appliance | None = None,
    target: float = 0.5,
    wear: float = 0.01,
    kitchen_restriction: bool = True,
) -> PlannerInput:
    local = slots[0].start.astimezone(CHICAGO)
    tomorrow = (local + timedelta(days=1)).replace(
        hour=8, minute=0, second=0, microsecond=0
    )
    specs = []
    for i, entity in enumerate(("hvac.living_room", "hvac.guest_room")):
        bands = [comfort(s.start, entity) for s in slots]
        physical = (
            zones[i]
            if zones is not None
            else ThermalZone(
                temp_f=70 if i == 0 else 67,
                target_f=70 if i == 0 else 72,
                mode="off",
                solar_gain_area_m2=0,
            )
        )
        specs.append(
            Zone(
                entity=entity,
                physical=physical,
                lower=tuple(b[0] for b in bands),
                upper=tuple(b[1] for b in bands),
                targets=tuple(b[2] for b in bands),
                occupants=tuple(0 for _ in slots),
                end_lower=comfort(slots[-1].end, entity)[0],
                end_upper=comfort(slots[-1].end, entity)[1],
            )
        )
    return PlannerInput(
        household_id=household_id,
        requester=requester
        or Requester(
            member_id="synthetic-household-manager", role="owner", surface="app"
        ),
        slots=slots,
        ev=(ev or EV(soc=0.34, plugged_in=True, charging=False, charge_limit=target))
        if configuration != "solar_battery"
        else None,
        ev_target=target,
        ev_deadline=tomorrow,
        battery=(battery or Battery(soc=0.55, dispatch_kw=0))
        if configuration != "ev_only"
        else None,
        zones=tuple(specs),
        appliance=appliance
        or Appliance(cycle_minutes=105, cycle_kwh=1.2, noise_dba=50, running=False),
        appliance_release=local.replace(hour=23, minute=0, second=0, microsecond=0)
        if kitchen_restriction
        else slots[0].start,
        appliance_deadline=tomorrow.replace(hour=7),
        base_load_kw=0.4,
        wear_per_kwh=wear,
        provenance=(
            "Approved synthetic workload; simulated devices",
            "Pinned 2026 tariff counterfactual: supply plus distribution",
        ),
    )


def demo_input() -> PlannerInput:
    # Supplied scenario weather; this smoke is not a historical savings claim.
    import yaml

    from hirz.twin.environment import Weather

    raw = yaml.safe_load(Path("scenarios/demo-evening.yaml").read_text())
    weather = Weather.model_validate(raw["initial"]["weather"])
    start = datetime.fromisoformat("2026-10-13T17:33:00-05:00")
    end = datetime.fromisoformat("2026-10-14T07:00:00-05:00")
    edges = boundaries(start, end)
    tariff = load_tariff(Path("tariffs/comed-time-of-day.yaml"))
    solar = Solar(tilt_degrees=30, orientation_degrees=180)
    slots = []
    for left, right in zip(edges, edges[1:]):
        w = weather.at(left)
        slots.append(
            Slot(
                start=left,
                end=right,
                price=counterfactual_rate(tariff, left),
                outdoor_f=w.temp_f,
                solar_kw=solar.kw_peak
                * solar.irradiance(left, 41.88, -87.63, w.cloud_cover_percent),
            )
        )
    return workload(tuple(slots), target=0.8, kitchen_restriction=False)
