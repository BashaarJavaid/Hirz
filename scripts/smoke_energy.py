"""Item 14 read-only demonstration: recorded responses unless --live is explicit."""

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import httpx

from hirz.adapters.base import PriceSeries, WeatherSeries
from hirz.adapters.energy.real import RealEnergy
from hirz.adapters.energy.real.tariff import CHICAGO, DELIVERY_CLASS
from hirz.graph.models import Household, Location, now

FIXTURES = Path(__file__).resolve().parents[1] / "tests/fixtures/energy"
TARIFF = Path(__file__).resolve().parents[1] / "tariffs/comed-time-of-day.yaml"


def recorded(request: httpx.Request) -> httpx.Response:
    if request.url.host == "api.open-meteo.com":
        name = "weather.json"
    elif request.url.path == "/api":
        name = "realtime-20260801.json"
    else:
        name = "dayahead-20260801.txt"
    return httpx.Response(200, content=(FIXTURES / name).read_bytes())


def describe(name: str, series: PriceSeries | WeatherSeries) -> None:
    rows = series.slots if isinstance(series, PriceSeries) else series.samples
    covered = (
        series.requested_end
        - series.requested_start
        - sum((g.end - g.start for g in series.gaps), timedelta())
    )
    print(f"{name}: {series.source_label}")
    print(
        f"  requested=[{series.requested_start.isoformat()}, {series.requested_end.isoformat()}) count={len(rows)} gaps={len(series.gaps)} covered_hours={covered.total_seconds() / 3600:.6f} complete={series.complete}"
    )
    if isinstance(series, PriceSeries) and series.slots:
        print(
            f"  observed_bounds=[{series.slots[0].start.isoformat()}, {series.slots[-1].end.isoformat()}) basis={series.basis} tariff={series.tariff_version} retrieved_at={series.retrieved_at}"
        )
        prices = [p.import_cents_per_kwh for p in series.slots]
        print(
            f"  import_cents_per_kwh: first={prices[0]} min={min(prices)} max={max(prices)} export=None"
        )
    for gap in series.gaps:
        print(f"  gap=[{gap.start.isoformat()}, {gap.end.isoformat()}) {gap.reason}")


async def smoke(*, live: bool, history_month: str, tariff_path: Path) -> None:
    start = datetime.strptime(history_month, "%Y-%m").replace(tzinfo=CHICAGO)
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    weather_start = (
        datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        if live
        else datetime.fromisoformat(
            json.loads((FIXTURES / "weather.json").read_text())["hourly"]["time"][0]
        ).replace(tzinfo=UTC)
    )
    household = Household(
        id=UUID("00000000-0000-4000-8000-000000000014"),
        name="Energy read demonstration",
        timezone="America/Chicago",
        locale="en-US",
        rate_plan="comed_time_of_day",
        location=Location(latitude=41.8781, longitude=-87.6298, source="declared"),
    )
    transport = None if live else httpx.MockTransport(recorded)
    print("LIVE public feeds" if live else "RECORDED public feed fixtures (no network)")
    for plan in ("comed_time_of_day", "comed_hourly"):
        home = Household.model_validate(household.model_dump() | {"rate_plan": plan})
        adapter = RealEnergy(
            home,
            delivery_class=DELIVERY_CLASS,
            tariff_path=tariff_path,
            transport=transport,
            clock=now if live else lambda: weather_start,
        )
        await adapter.start()
        try:
            for kind in ("day_ahead", "realtime"):
                stop = (
                    end
                    if live and plan == "comed_hourly" and kind == "realtime"
                    else start + timedelta(days=1)
                )
                result = await adapter.get_prices(start, stop, kind)
                describe(f"{plan}/{kind}", result)
                assert result.slots, "Acceptance requires actual returned data"
            if plan == "comed_time_of_day":
                weather = await adapter.get_weather(
                    weather_start + timedelta(minutes=17),
                    weather_start + timedelta(hours=3),
                )
                describe("weather", weather)
                assert weather.samples, "Acceptance requires actual forecast data"
        finally:
            await adapter.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--history-month", default="2026-08")
    parser.add_argument("--tariff-file", type=Path, default=TARIFF)
    args = parser.parse_args()
    if not args.live and args.history_month != "2026-08":
        parser.error("recorded mode covers 2026-08 only")
    asyncio.run(
        smoke(
            live=args.live,
            history_month=args.history_month,
            tariff_path=args.tariff_file,
        )
    )


if __name__ == "__main__":
    main()
