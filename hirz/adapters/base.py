"""Shared adapter lifecycle and typed price/weather values. No transport code."""

from datetime import datetime
from typing import Literal, Protocol, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, computed_field, model_validator

from hirz.constitution.schema import Numeric
from hirz.graph.models import Model, PolicyNumber, RatePlan, Source, Text, utc

PriceKind = Literal["day_ahead", "realtime"]


class AdapterError(ValueError):
    """Safe configuration or adapter-contract failure; no private payloads."""


class AdapterUnavailable(AdapterError):
    """Unavailable capability or adapter; actual state is unknown."""


class Adapter(Protocol):
    @property
    def household_id(self) -> UUID: ...

    @property
    def capabilities(self) -> frozenset[str]: ...

    async def start(self) -> None: ...
    async def close(self) -> None: ...


def validate_range(start: datetime, end: datetime) -> None:
    try:
        valid = utc(start) < utc(end)
    except ValueError:
        valid = False
    if not valid:
        raise AdapterError("A positive half-open time range is required.")


class PriceSlot(Model):
    start: AwareDatetime
    end: AwareDatetime
    import_cents_per_kwh: Numeric
    export_cents_per_kwh: Numeric | None = None

    @model_validator(mode="after")
    def ordered(self) -> Self:
        validate_range(self.start, self.end)
        return self


class WeatherSample(Model):
    at: AwareDatetime
    temp_f: PolicyNumber
    cloud_cover_percent: PolicyNumber = Field(ge=0, le=100)


class Gap(Model):
    start: AwareDatetime
    end: AwareDatetime
    reason: Text

    @model_validator(mode="after")
    def ordered(self) -> Self:
        validate_range(self.start, self.end)
        return self


class Series(Model):
    requested_start: AwareDatetime
    requested_end: AwareDatetime
    gaps: tuple[Gap, ...]
    source: Source
    source_label: Text
    source_urls: tuple[str, ...]
    tariff_version: str | None
    retrieved_at: AwareDatetime | None

    @model_validator(mode="after")
    def ordered(self) -> Self:
        validate_range(self.requested_start, self.requested_end)
        cursor = utc(self.requested_start)
        for gap in self.gaps:
            if utc(gap.start) < cursor or utc(gap.end) > utc(self.requested_end):
                raise ValueError("Gaps must be ordered within requested bounds.")
            cursor = utc(gap.end)
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def complete(self) -> bool:
        return not self.gaps


class PriceSeries(Series):
    rate_plan: RatePlan
    kind: PriceKind
    basis: Literal["supply_plus_distribution", "supply_only"]
    slots: tuple[PriceSlot, ...]

    @model_validator(mode="after")
    def coverage(self) -> Self:
        intervals = [(utc(s.start), utc(s.end)) for s in self.slots]
        if intervals != sorted(intervals):
            raise ValueError("Price slots must be ordered.")
        intervals += [(utc(g.start), utc(g.end)) for g in self.gaps]
        cursor = utc(self.requested_start)
        for start, end in sorted(intervals):
            if start != cursor:
                raise ValueError("Slots and gaps must partition requested bounds.")
            cursor = end
        if cursor != utc(self.requested_end):
            raise ValueError("Price coverage is incomplete without explicit gaps.")
        return self


class WeatherSeries(Series):
    samples: tuple[WeatherSample, ...]

    @model_validator(mode="after")
    def coverage(self) -> Self:
        times = [utc(s.at) for s in self.samples]
        if times != sorted(set(times)) or any(
            not utc(self.requested_start) <= t < utc(self.requested_end)
            or any(utc(g.start) <= t < utc(g.end) for g in self.gaps)
            for t in times
        ):
            raise ValueError("Weather samples must be ordered outside gaps.")
        # Values hold to the next sample, gap, or requested end. After a gap,
        # a new sample is mandatory; a value never carries across missing hours.
        starts = {utc(self.requested_start)} | {utc(g.end) for g in self.gaps}
        for start in starts:
            if (
                start < utc(self.requested_end)
                and not any(utc(g.start) <= start < utc(g.end) for g in self.gaps)
                and start not in times
            ):
                raise ValueError("Weather coverage requires a sample after each gap.")
        return self
