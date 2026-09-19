"""Shared adapter lifecycle and typed price/weather values. No transport code."""

from datetime import datetime
from typing import Literal, Protocol, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from hirz.constitution.schema import Numeric
from hirz.graph.models import Model, PolicyNumber, utc

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
    if utc(start) >= utc(end):
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
