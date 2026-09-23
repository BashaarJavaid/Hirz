"""Read-only planner smoke; no database, device writes or execution authority."""

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from uuid import UUID


async def live_weather() -> dict[str, object]:
    from hirz.adapters.energy.real import RealEnergy
    from hirz.adapters.energy.real.tariff import DELIVERY_CLASS
    from hirz.graph.models import Household, Location

    home = Household(
        id=UUID(int=17),
        name="Planner weather smoke",
        timezone="America/Chicago",
        locale="en-US",
        rate_plan="comed_time_of_day",
        location=Location(latitude=41.88, longitude=-87.63, source="declared"),
    )
    adapter = RealEnergy(
        home,
        delivery_class=DELIVERY_CLASS,
        tariff_path=Path("tariffs/comed-time-of-day.yaml"),
    )
    await adapter.start()
    try:
        start = datetime.now(UTC)
        weather = await adapter.get_weather(start, start + timedelta(hours=24))
        return {
            "label": "Live weather smoke only; excluded from historical figures",
            "weather": weather.model_dump(mode="json"),
        }
    finally:
        await adapter.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-weather", action="store_true")
    args = parser.parse_args()
    began = perf_counter()
    from hirz.planner.service import plan
    from hirz.planner.workload import demo_input

    import_seconds = perf_counter() - began
    p = demo_input()
    result = plan(p)
    cold_seconds = perf_counter() - began
    began = perf_counter()
    greedy = plan(p, cold_start=True)
    greedy_seconds = perf_counter() - began
    print(
        json.dumps(
            {
                "milp": result.model_dump(mode="json"),
                "import_seconds": import_seconds,
                "cold_seconds": cold_seconds,
                "greedy_seconds": greedy_seconds,
                "greedy_valid": greedy.plan is not None,
                "live": asyncio.run(live_weather()) if args.live_weather else None,
            },
            indent=2,
        )
    )
    return (
        0
        if result.plan is not None
        and greedy.plan is not None
        and result.diagnostics.elapsed_seconds < 2
        and greedy_seconds < 0.05
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
