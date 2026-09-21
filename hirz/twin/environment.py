"""Supplied weather, synthetic tariffs, and a small solar-position model."""

import calendar
import math
import random
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Annotated, Self
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, Field, model_validator

from hirz.adapters.base import (
    AdapterError,
    PriceKind,
    PriceSlot,
    WeatherSample,
    validate_range,
)
from hirz.constitution.schema import Numeric
from hirz.graph.models import Model, utc
from hirz.twin.physics import Fraction, Positive


def stream(
    seed: int, home: UUID, model: str, subject: str, bucket: str
) -> random.Random:
    # Length-prefix the components so separators inside a name cannot collide.
    parts = [str(seed), str(home), model, subject, bucket]
    key = "".join(f"{len(part)}:{part}" for part in parts)
    return random.Random(int.from_bytes(sha256(key.encode()).digest(), "big"))


class Weather(Model):
    start: AwareDatetime
    end: AwareDatetime
    samples: tuple[WeatherSample, ...]

    @model_validator(mode="after")
    def coverage(self) -> Self:
        validate_range(self.start, self.end)
        times = [utc(s.at) for s in self.samples]
        if (
            not times
            or times[0] != utc(self.start)
            or times != sorted(set(times))
            or times[-1] >= utc(self.end)
        ):
            raise ValueError(
                "Weather must cover its declared range in timestamp order."
            )
        return self

    def at(self, at: datetime) -> WeatherSample:
        at = utc(at)
        if not utc(self.start) <= at <= utc(self.end):
            raise AdapterError("Weather outside supplied coverage.")
        return next(s for s in reversed(self.samples) if utc(s.at) <= at)

    def between(self, start: datetime, end: datetime) -> tuple[WeatherSample, ...]:
        validate_range(start, end)
        if utc(start) < utc(self.start) or utc(end) > utc(self.end):
            raise AdapterError("Weather outside supplied coverage.")
        initial = self.at(start)
        return (
            WeatherSample(
                at=start,
                temp_f=initial.temp_f,
                cloud_cover_percent=initial.cloud_cover_percent,
            ),
        ) + tuple(s for s in self.samples if utc(start) < utc(s.at) < utc(end))


class Period(Model):
    start_minute: Annotated[int, Field(ge=0, lt=1440)]
    end_minute: Annotated[int, Field(gt=0, le=1440)]
    import_cents_per_kwh: Numeric
    export_cents_per_kwh: Numeric | None = None
    band: Annotated[str, Field(min_length=1)]


class Tariff(Model):
    periods: tuple[Period, ...]
    slot_minutes: Annotated[int, Field(gt=0)]
    spike_probability: Fraction
    spike_min_cents: Numeric
    spike_max_cents: Numeric

    @model_validator(mode="after")
    def complete(self) -> Self:
        end = 0
        for period in self.periods:
            if period.start_minute != end or period.end_minute <= end:
                raise ValueError(
                    "Tariff periods must cover each local day exactly once."
                )
            end = period.end_minute
        if (
            end != 1440
            or self.spike_min_cents < 0
            or self.spike_max_cents < self.spike_min_cents
        ):
            raise ValueError("Invalid tariff coverage or spike range.")
        return self

    def period(self, at: datetime, timezone: str) -> Period:
        local = utc(at).astimezone(ZoneInfo(timezone))
        minute = local.hour * 60 + local.minute
        return next(p for p in self.periods if p.start_minute <= minute < p.end_minute)

    def prices(
        self,
        start: datetime,
        end: datetime,
        kind: PriceKind,
        *,
        origin: datetime,
        horizon: datetime,
        timezone: str,
        seed: int,
        home: UUID,
    ) -> tuple[PriceSlot, ...]:
        start, end, origin, horizon = map(utc, (start, end, origin, horizon))
        validate_range(start, end)
        if start < origin or end > horizon or kind not in {"day_ahead", "realtime"}:
            raise AdapterError("Invalid price range or kind.")
        step = timedelta(minutes=self.slot_minutes)
        index = (start - origin) // step
        at = origin + index * step
        result = []
        while at < end:
            period = self.period(at, timezone)
            price = period.import_cents_per_kwh
            rng = stream(seed, home, "tariff", "household", str(index))
            if kind == "realtime" and rng.random() < self.spike_probability:
                price += (
                    self.spike_min_cents
                    + Decimal(str(rng.random()))
                    * (self.spike_max_cents - self.spike_min_cents)
                ).quantize(Decimal("0.0001"))
            result.append(
                PriceSlot(
                    start=max(start, at),
                    end=min(end, at + step),
                    import_cents_per_kwh=price,
                    export_cents_per_kwh=period.export_cents_per_kwh,
                )
            )
            at += step
            index += 1
        return tuple(result)


def sun_vector(
    at: datetime, latitude: float, longitude: float
) -> tuple[float, float, float]:
    """East, north, up; NOAA fractional-year equations, without refraction.

    https://gml.noaa.gov/grad/solcalc/solareqns.PDF
    """
    at = utc(at)
    if not (
        math.isfinite(latitude)
        and math.isfinite(longitude)
        and -90 <= latitude <= 90
        and -180 <= longitude <= 180
    ):
        raise AdapterError("Invalid solar location.")
    hour = at.hour + at.minute / 60 + at.second / 3600
    gamma = (
        2
        * math.pi
        / (366 if calendar.isleap(at.year) else 365)
        * (at.timetuple().tm_yday - 1 + (hour - 12) / 24)
    )
    eq = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma)
    )
    decl = (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma)
        + 0.00148 * math.sin(3 * gamma)
    )
    angle = math.radians((hour * 60 + eq + 4 * longitude) / 4 - 180)
    lat = math.radians(latitude)
    return (
        -math.cos(decl) * math.sin(angle),
        math.cos(lat) * math.sin(decl)
        - math.sin(lat) * math.cos(decl) * math.cos(angle),
        math.sin(lat) * math.sin(decl)
        + math.cos(lat) * math.cos(decl) * math.cos(angle),
    )


class Solar(Model):
    kw_peak: Positive = 6
    tilt_degrees: Annotated[float, Field(ge=0, le=90)]
    orientation_degrees: Annotated[float, Field(ge=0, lt=360)]
    cloud_coefficient: Fraction = 0.8

    def irradiance(
        self, at: datetime, latitude: float, longitude: float, cloud: float
    ) -> float:
        if not math.isfinite(cloud) or not 0 <= cloud <= 100:
            raise AdapterError("Invalid cloud cover.")
        east, north, up = sun_vector(at, latitude, longitude)
        if up <= 0:
            return 0
        tilt, orientation = map(
            math.radians, (self.tilt_degrees, self.orientation_degrees)
        )
        incidence = (
            east * math.sin(tilt) * math.sin(orientation)
            + north * math.sin(tilt) * math.cos(orientation)
            + up * math.cos(tilt)
        )
        # ponytail: synthetic direct-beam/cloud approximation; calibrate against measured PV before real forecasting.
        return max(0, min(1, incidence)) * (1 - self.cloud_coefficient * cloud / 100)
