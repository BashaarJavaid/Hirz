"""Pinned ComEd scheduling charges; calendar months approximate billing periods."""

from datetime import date, datetime
from pathlib import Path
from typing import Literal, Self
from zoneinfo import ZoneInfo

import yaml
from pydantic import Field, model_validator

from hirz.adapters.base import AdapterError
from hirz.constitution.schema import Numeric
from hirz.graph.models import Model, Text

CHICAGO = ZoneInfo("America/Chicago")
DELIVERY_CLASS = "residential_single_family_without_electric_space_heat"
PERIODS = {
    "morning": (6, 13),
    "mid_day_peak": (13, 19),
    "evening": (19, 21),
    "overnight": (21, 6),
}


def period(at: datetime) -> str:
    hour = at.astimezone(CHICAGO).hour
    return next(
        (name for name, (start, end) in PERIODS.items() if start <= hour < end),
        "overnight",
    )


class RateRow(Model):
    component: Literal["supply", "distribution"]
    period: Literal["morning", "mid_day_peak", "evening", "overnight", "flat"]
    season: Literal["summer", "nonsummer", "all"]
    start_hour: int
    end_hour: int
    cents_per_kwh: Numeric
    source_url: Text
    document_effective_date: date
    billing_start: date
    billing_end: date | None
    verified_on: date

    def supports(self, at: datetime) -> bool:
        day = at.astimezone(CHICAGO).date()
        return self.billing_start <= day and (
            self.billing_end is None or day < self.billing_end
        )


class SourceDocument(Model):
    file: Text
    url: Text
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Tariff(Model):
    version: Text
    delivery_class: Literal["residential_single_family_without_electric_space_heat"]
    timezone: Literal["America/Chicago"]
    unit: Literal["cents_per_kwh"]
    basis: Literal["supply_plus_distribution"]
    billing_period_approximation: Text
    exclusions: tuple[Text, ...]
    included_adjustments: Text
    delivery_vintage_note: Text
    sources: tuple[SourceDocument, ...]
    rows: tuple[RateRow, ...]

    @model_validator(mode="after")
    def reviewed_shape(self) -> Self:
        expected = {("supply", p, s) for p in PERIODS for s in ("summer", "nonsummer")}
        expected |= {("distribution", p, "all") for p in (*PERIODS, "flat")}
        if (
            len(self.rows) != len(expected)
            or {(r.component, r.period, r.season) for r in self.rows} != expected
        ):
            raise ValueError(
                "Tariff must contain every supported period and season once."
            )
        for row in self.rows:
            if (row.start_hour, row.end_hour) != (
                (0, 24) if row.period == "flat" else PERIODS[row.period]
            ):
                raise ValueError("Unsupported tariff period hours.")
            if (
                row.billing_end is not None and row.billing_end <= row.billing_start
            ) or (row.component == "supply" and row.billing_end is None):
                raise ValueError("Invalid tariff validity.")
            if row.source_url not in {s.url for s in self.sources}:
                raise ValueError("Tariff row lacks a source document.")
        return self

    def row(self, at: datetime, component: str, *, hourly: bool = False) -> RateRow:
        band = "flat" if hourly else period(at)
        season = (
            ("summer" if 6 <= at.astimezone(CHICAGO).month <= 9 else "nonsummer")
            if component == "supply"
            else "all"
        )
        row = next(
            r
            for r in self.rows
            if (r.component, r.period, r.season) == (component, band, season)
        )
        if not row.supports(at):
            raise AdapterError(
                "Requested dates are outside the pinned tariff validity."
            )
        return row


def load_tariff(path: Path) -> Tariff:
    try:
        return Tariff.model_validate(yaml.safe_load(path.read_text()))
    except (OSError, ValueError, yaml.YAMLError):
        raise AdapterError("Invalid or unreadable ComEd tariff file.") from None
