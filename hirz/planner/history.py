"""Archived public inputs, strict hourly billing, and lagged persistence forecasts."""

import gzip
import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TypeVar

import httpx

from hirz.adapters.energy.real import COMED, feeds
from hirz.adapters.energy.real.tariff import CHICAGO, Tariff, period

T = TypeVar("T")
START = date(2025, 9, 1)
END = date(2026, 9, 1)


def hourly(quotes: dict[datetime, Decimal | None]) -> dict[datetime, float | None]:
    """Feed-based estimate, not a reconciled final bill (ComEd live-prices docs)."""
    result = {}
    for hour in sorted({at.replace(minute=0) for at in quotes}):
        values = [quotes.get(hour + timedelta(minutes=5 * i)) for i in range(12)]
        result[hour] = (
            None
            if any(v is None for v in values)
            else float(sum(v for v in values if v is not None) / 12 / 100)
        )
    return result


def persistence(
    values: dict[datetime, T | None], target: datetime, decision: datetime
) -> tuple[T, datetime]:
    local = target.astimezone(CHICAGO)
    cutoff = decision.astimezone(UTC) - timedelta(hours=24)
    # Matching *wall hour*, with neither fold admitted as an ambiguous source.
    day = decision.astimezone(CHICAGO).date()
    for lag in range(8):
        label = datetime.combine(
            day - timedelta(days=lag), datetime.min.time()
        ).replace(hour=local.hour)
        candidates = feeds.local_instants(label)
        if len(candidates) != 1:
            continue
        at = candidates.pop()
        if decision - timedelta(days=7) <= at and at + timedelta(hours=1) <= cutoff:
            value = values.get(at)
            if value is not None:
                return value, at
    raise ValueError(
        f"No eligible persistence source for {target.isoformat()} at {decision.isoformat()}"
    )


def counterfactual_rate(
    tariff: Tariff, at: datetime, *, hourly_supply: float | None = None
) -> float:
    """Explicit research counterfactual; never calls or weakens production row()."""
    band = period(at)
    season = "summer" if 6 <= at.astimezone(CHICAGO).month <= 9 else "nonsummer"
    if hourly_supply is None:
        return sum(
            float(r.cents_per_kwh) / 100
            for r in tariff.rows
            if r.period == band
            and (r.component == "distribution" or r.season == season)
        )
    delivery = next(
        r for r in tariff.rows if r.component == "distribution" and r.period == "flat"
    )
    return hourly_supply + float(delivery.cents_per_kwh) / 100


def read_raw(root: Path, name: str) -> str:
    manifest = json.loads((root / "manifest.json").read_text())
    raw = gzip.decompress((root / name).read_bytes())
    if hashlib.sha256(raw).hexdigest() != manifest[name]["sha256"]:
        raise ValueError(f"Archive checksum mismatch: {name}")
    return raw.decode()


async def fetch_archive(root: Path, start: date = START, end: date = END) -> None:
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    async with httpx.AsyncClient(timeout=45, follow_redirects=True) as client:

        async def fetch(name: str, url: str, params: dict[str, str]) -> None:
            if name in manifest and (root / name).exists():
                read_raw(root, name)
                return
            response = await client.get(url, params=params)
            response.raise_for_status()
            raw = response.content
            (root / name).write_bytes(gzip.compress(raw, mtime=0))
            manifest[name] = {
                "url": str(response.url),
                "retrieved_at": datetime.now(UTC).isoformat(),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
            temp = root / "manifest.tmp"
            temp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            temp.replace(manifest_path)

        day = start - timedelta(days=8)
        while day <= end + timedelta(days=1):
            stamp = day.strftime("%Y%m%d")
            await fetch(
                f"dayahead-{stamp}.txt.gz",
                COMED + "/rrtp/ServletFeed",
                {"type": "daynexttoday", "date": stamp},
            )
            await fetch(
                f"realtime-{stamp}.json.gz",
                COMED + "/api",
                {
                    "type": "5minutefeed",
                    "datestart": stamp + "0000",
                    "dateend": (day + timedelta(days=1)).strftime("%Y%m%d") + "0000",
                },
            )
            print(f"Archived {day}", flush=True)
            day += timedelta(days=1)
        await fetch(
            "weather.json.gz",
            "https://archive-api.open-meteo.com/v1/archive",
            {
                "latitude": "41.88",
                "longitude": "-87.63",
                "start_date": (start - timedelta(days=8)).isoformat(),
                "end_date": (end + timedelta(days=1)).isoformat(),
                "hourly": "temperature_2m,cloud_cover",
                "temperature_unit": "fahrenheit",
                "timezone": "UTC",
            },
        )
