"""Strict parsers for recorded first-party feed formats. Never execute JavaScript."""

import json
import re
from datetime import UTC, date, datetime
from decimal import Decimal

from hirz.adapters.base import WeatherSample
from hirz.adapters.energy.real.tariff import CHICAGO
from hirz.constitution.conditions import number

# ComEd's chart encodes Chicago wall-clock labels as Date.UTC, not UTC instants.
# See retained prices-page.html and spring/fall fixtures; this is not a public API.
DATE = r"Date\.UTC\((\d{4}),(\d{1,2}),(\d{1,2}),(\d{1,2}),0,0\)"
VALUE = r"(?:null|-?\d+(?:\.\d+)?)"
ROW = rf"\[\s*{DATE}\s*,\s*{VALUE}\s*\]"
ARRAY = re.compile(rf"\s*\[\s*(?:{ROW}(?:\s*,\s*{ROW})*)?\s*\]\s*")


def put[T](values: dict[datetime, T], at: datetime, value: T) -> None:
    if at in values and values[at] != value:
        raise ValueError("Conflicting duplicate")
    values[at] = value


def local_instants(label: datetime) -> set[datetime]:
    """Zero for nonexistent time, two for a folded hour, otherwise one."""
    return {
        instant
        for fold in (0, 1)
        if (instant := label.replace(tzinfo=CHICAGO, fold=fold).astimezone(UTC))
        .astimezone(CHICAGO)
        .replace(tzinfo=None)
        == label
    }


def day_ahead(text: str, day: date) -> dict[datetime, Decimal | None]:
    if ARRAY.fullmatch(text) is None:
        raise ValueError("Invalid day-ahead array")
    translated = re.sub(DATE, r"[\1,\2,\3,\4]", text)
    rows = json.loads(translated, parse_float=Decimal)
    labels: dict[datetime, Decimal | None] = {}
    for (year, month, dom, hour), value in rows:
        label = datetime(year, month + 1, dom, hour)
        if label.date() != day:
            raise ValueError("Wrong day-ahead date")
        put(labels, label, None if value is None else number(value))
    result: dict[datetime, Decimal | None] = {}
    for label, value in labels.items():
        instants = local_instants(label)
        if not instants:
            raise ValueError("Nonexistent day-ahead hour")
        for at in instants:
            # No offset/fold in the upstream row: neither occurrence is knowable.
            result[at] = value if len(instants) == 1 else None
    return result


def realtime(text: str) -> dict[datetime, Decimal | None]:
    rows = json.loads(text, parse_float=Decimal)
    if not isinstance(rows, list):
        raise ValueError("Invalid five-minute array")
    result: dict[datetime, Decimal | None] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"millisUTC", "price"}:
            raise ValueError("Invalid five-minute row")
        millis = row["millisUTC"]
        if (
            isinstance(millis, bool)
            or not isinstance(millis, (str, int))
            or re.fullmatch(r"\d+", str(millis)) is None
            or int(millis) % 300000
        ):
            raise ValueError("Invalid five-minute timestamp")
        at = datetime.fromtimestamp(int(millis) // 1000, UTC)
        value = row["price"]
        put(result, at, None if value is None else number(value))
    return result


def weather(text: str) -> dict[datetime, WeatherSample | None]:
    body = json.loads(text)
    if (
        not isinstance(body, dict)
        or type(body.get("utc_offset_seconds")) is not int
        or body["utc_offset_seconds"] != 0
    ):
        raise ValueError("Weather is not UTC")
    if body.get("hourly_units") != {
        "time": "iso8601",
        "temperature_2m": "°F",
        "cloud_cover": "%",
    }:
        raise ValueError("Invalid weather units")
    hourly = body["hourly"]
    times, temps, clouds = (
        hourly[k] for k in ("time", "temperature_2m", "cloud_cover")
    )
    if (
        not all(isinstance(v, list) for v in (times, temps, clouds))
        or len(times) != len(temps)
        or len(times) != len(clouds)
    ):
        raise ValueError("Invalid weather arrays")
    result: dict[datetime, WeatherSample | None] = {}
    for stamp, temp, cloud in zip(times, temps, clouds, strict=True):
        if (
            not isinstance(stamp, str)
            or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:00", stamp) is None
        ):
            raise ValueError("Invalid weather timestamp")
        at = datetime.fromisoformat(stamp).replace(tzinfo=UTC)
        # Validate present fields even when the other field is missing.
        sample = WeatherSample(
            at=at,
            temp_f=0 if temp is None else temp,
            cloud_cover_percent=0 if cloud is None else cloud,
        )
        put(result, at, None if temp is None or cloud is None else sample)
    return result
