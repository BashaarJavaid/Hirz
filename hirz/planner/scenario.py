"""Read-only planning snapshots alongside, never applied to, the scenario world."""

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hirz.adapters.energy.real.tariff import CHICAGO, load_tariff
from hirz.pipeline.models import PlanConstraint, Requester
from hirz.planner.history import counterfactual_rate, hourly, persistence, read_raw
from hirz.planner.models import MemberConstraint, PlannerInput, Slot, boundaries
from hirz.planner.service import plan
from hirz.planner.workload import workload
from hirz.twin.physics import changed

if TYPE_CHECKING:
    from hirz.twin.scenario import LoadedScenario, PlanningSnapshot


def workload_input(
    loaded: "LoadedScenario", spec: "PlanningSnapshot", *, end: datetime | None = None
) -> PlannerInput:
    from hirz.adapters.energy.real import feeds

    world = loaded.world
    at, state = world.read()
    member = loaded.ref("members", spec.member)
    edges = boundaries(at, end) if end is not None else boundaries(at)
    tariff = load_tariff(Path("tariffs/comed-time-of-day.yaml"))
    quotes: dict[datetime, Decimal | None] = {}
    if loaded.spec.rate_plan == "comed_hourly":
        for lag in range(8):
            day = at.astimezone(CHICAGO).date() - timedelta(days=lag)
            path = Path("scripts/backtest-data/raw") / f"realtime-{day:%Y%m%d}.json.gz"
            for when, value in feeds.realtime(read_raw(path.parent, path.name)).items():
                feeds.put(quotes, when, value)
    history = hourly(quotes)
    slots = []
    for left, right in zip(edges, edges[1:]):
        w = world.config.weather.at(left)
        price_source = None
        if loaded.spec.rate_plan == "comed_hourly":
            price, price_source = persistence(history, left, at)
            price = counterfactual_rate(tariff, left, hourly_supply=price)
        else:
            price = sum(
                float(tariff.row(left, c).cents_per_kwh) / 100
                for c in ("supply", "distribution")
            )
        solar = (
            sum(
                m.kw_peak
                * m.irradiance(
                    left,
                    world.household.location.latitude,
                    world.household.location.longitude,
                    w.cloud_cover_percent,
                )
                for m in world.solar.values()
            )
            if world.household.location
            else 0
        )
        slots.append(
            Slot(
                start=left,
                end=right,
                price=price,
                outdoor_f=w.temp_f,
                solar_kw=solar,
                price_source=price_source,
            )
        )
    requester = Requester(
        member_id=str(member), role=world.members[member].role, surface="alexa"
    )
    p = workload(
        tuple(slots),
        household_id=world.household.id,
        requester=requester,
        ev=next(iter(state.evs.values())),
        battery=next(iter(state.batteries.values())),
        zones=tuple(
            state.zones[loaded.ref("assets", e)]
            for e in ("hvac.living_room", "hvac.guest_room")
        ),
        appliance=next(iter(state.appliances.values())),
        target=spec.ev_target,
        kitchen_restriction=False,
    )
    p = changed(
        p,
        base_load_kw=world.config.base_load_kw,
        constraints=(
            MemberConstraint(
                kind="ev_target",
                value=spec.ev_target,
                provenance=PlanConstraint(
                    source="member:" + str(member),
                    surface="alexa",
                    recorded_at=at,
                    text=f"EV target {spec.ev_target:.0%} by 08:00",
                    encoded={"ev.soc_min": spec.ev_target, "by": "08:00"},
                ),
            ),
        ),
        provenance=(
            "Simulated devices; supplied scenario weather",
            "Published ComEd tariff"
            if loaded.spec.rate_plan == "comed_time_of_day"
            else "Pinned 2026 tariff counterfactual; lagged persistence supply forecast",
        ),
    )
    return p


def snapshot(loaded: "LoadedScenario", spec: "PlanningSnapshot") -> dict[str, Any]:
    p = workload_input(loaded, spec)
    at = loaded.world.clock()
    result = plan(p)
    data = result.model_dump(mode="json")
    # Measurements are kept in smoke/backtest artifacts; scenario equality is stable.
    data["diagnostics"].pop("elapsed_seconds")
    summary = result.plan.summary if result.plan else None
    passed = result.plan is not None and result.plan.comparison_validity.valid
    if spec.expected_savings is not None:
        passed = (
            passed
            and summary is not None
            and summary.estimated_savings_usd is not None
            and abs(summary.estimated_savings_usd - spec.expected_savings) <= 1e-6
        )
    if spec.expected_peak is not None:
        passed = (
            passed
            and summary is not None
            and summary.peak_kwh_avoided is not None
            and abs(summary.peak_kwh_avoided - spec.expected_peak) <= 1e-6
        )
    return {
        "at": at.isoformat(),
        "source": "twin",
        "price_source": "real (published ComEd rate)"
        if loaded.spec.rate_plan == "comed_time_of_day"
        else "real historical API; persistence forecast; pinned tariff counterfactual",
        "status": "passed" if passed else "failed",
        "result": data,
    }
