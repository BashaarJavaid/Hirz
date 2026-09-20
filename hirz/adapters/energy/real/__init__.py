"""Credential-free household energy reads; no ingestion, actuation, or fallback."""

import logging
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal
from uuid import uuid4

import httpx

from hirz.adapters.base import (
    AdapterError,
    AdapterUnavailable,
    Gap,
    PriceKind,
    PriceSeries,
    PriceSlot,
    WeatherSample,
    WeatherSeries,
    validate_range,
)
from hirz.adapters.energy.real import feeds
from hirz.adapters.energy.real.tariff import (
    CHICAGO,
    DELIVERY_CLASS,
    load_tariff,
    period,
)
from hirz.adapters.registry import Factory, Key
from hirz.graph.models import Household, Observation, ObservationState, now, utc
from hirz.pipeline.models import Action, Decision

log = logging.getLogger(__name__)

COMED = "https://hourlypricing.comed.com"
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
Basis = Literal["supply_plus_distribution", "supply_only"]


def intervals(
    start: datetime, end: datetime, minutes: int
) -> Iterator[tuple[datetime, datetime, datetime]]:
    """UTC-anchored buckets, carrying only their own value to a clipped start."""
    step = timedelta(minutes=minutes)
    at = start.replace(
        minute=start.minute // minutes * minutes, second=0, microsecond=0
    )
    while at < end:
        yield at, max(at, start), min(at + step, end)
        at += step


def add_gap(gaps: list[Gap], start: datetime, end: datetime, reason: str) -> None:
    if gaps and gaps[-1].end == start and gaps[-1].reason == reason:
        start = gaps.pop().start
    gaps.append(Gap(start=start, end=end, reason=reason))


class RealEnergy:
    def __init__(
        self,
        household: Household,
        *,
        delivery_class: str,
        tariff_path: Path,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], datetime] = now,
    ):
        self.household = Household.model_validate(household.model_dump())
        self.household_id = self.household.id
        if (
            self.household.rate_plan not in ("comed_time_of_day", "comed_hourly")
            or delivery_class != DELIVERY_CLASS
        ):
            raise AdapterError("Unsupported ComEd rate plan or delivery class.")
        self.tariff = load_tariff(tariff_path)
        self.transport = transport
        self.clock = clock
        self.client: httpx.AsyncClient | None = None
        self.capabilities = frozenset({"get_prices", "get_supply_history"})
        if self.household.rate_plan == "comed_time_of_day":
            self.capabilities |= {"get_tariff_state"}
        if self.household.location is not None:
            self.capabilities |= {"get_weather"}

    async def start(self) -> None:
        if self.client is not None:
            raise AdapterError("Energy adapter is already started.")
        self.client = httpx.AsyncClient(timeout=10, transport=self.transport)

    async def close(self) -> None:
        if self.client is not None:
            await self.client.aclose()
            self.client = None

    def ready(self) -> httpx.AsyncClient:
        if self.client is None:
            raise AdapterUnavailable("Energy adapter is not started.")
        return self.client

    async def fetch(self, url: str, params: dict[str, str]) -> tuple[str, str]:
        try:
            response = await self.ready().get(url, params=params)
            response.raise_for_status()
            return response.text, str(response.url)
        except httpx.HTTPError as exc:
            log.error("RealEnergy.fetch error=%s", type(exc).__name__)
            raise AdapterUnavailable("Energy feed request failed.") from None

    async def get_prices(
        self, start: datetime, end: datetime, kind: PriceKind
    ) -> PriceSeries:
        return await self.prices(start, end, kind, "supply_plus_distribution")

    async def get_supply_history(
        self, start: datetime, end: datetime, kind: PriceKind
    ) -> PriceSeries:
        return await self.prices(start, end, kind, "supply_only")

    async def prices(
        self, start: datetime, end: datetime, kind: PriceKind, basis: Basis
    ) -> PriceSeries:
        self.ready()
        validate_range(start, end)
        start, end = utc(start), utc(end)
        if kind not in ("day_ahead", "realtime") or end - start > timedelta(days=366):
            raise AdapterError("Prices require a supported kind and at most 366 days.")
        hourly = self.household.rate_plan == "comed_hourly"
        step = 60 if kind == "day_ahead" else 5
        buckets = list(intervals(start, end, step))
        # Validate the whole requested tariff range before issuing any request.
        for _, left, _ in buckets:
            if not hourly:
                self.tariff.row(left, "supply")
            if basis == "supply_plus_distribution":
                self.tariff.row(left, "distribution", hourly=hourly)
        values: dict[datetime, Decimal | None] = {}
        urls: list[str] = []
        if hourly:
            day = start.astimezone(CHICAGO).date()
            last_day = (end - timedelta(microseconds=1)).astimezone(CHICAGO).date()
            while day <= last_day:
                if kind == "day_ahead":
                    text, url = await self.fetch(
                        COMED + "/rrtp/ServletFeed",
                        {"type": "daynexttoday", "date": day.strftime("%Y%m%d")},
                    )
                else:
                    # Upstream bounds are inclusive local calendar labels. Fetch
                    # full days (including both folded hours), then filter in UTC.
                    text, url = await self.fetch(
                        COMED + "/api",
                        {
                            "type": "5minutefeed",
                            "datestart": day.strftime("%Y%m%d") + "0000",
                            "dateend": (day + timedelta(days=1)).strftime("%Y%m%d")
                            + "0000",
                        },
                    )
                urls.append(url)
                try:
                    parsed = (
                        feeds.day_ahead(text, day)
                        if kind == "day_ahead"
                        else feeds.realtime(text)
                    )
                    for at, value in parsed.items():
                        feeds.put(values, at, value)
                except (
                    ValueError,
                    TypeError,
                    KeyError,
                    OverflowError,
                    OSError,
                    RecursionError,
                ) as exc:
                    log.error("RealEnergy.prices error=%s", type(exc).__name__)
                    raise AdapterUnavailable("Invalid ComEd feed response.") from None
                day += timedelta(days=1)
        slots: list[PriceSlot] = []
        gaps: list[Gap] = []
        for at, left, right in buckets:
            supply = (
                values.get(at)
                if hourly
                else self.tariff.row(left, "supply").cents_per_kwh
            )
            if supply is None:
                ambiguous = (
                    kind == "day_ahead"
                    and len(
                        feeds.local_instants(
                            at.astimezone(CHICAGO).replace(tzinfo=None)
                        )
                    )
                    == 2
                )
                add_gap(
                    gaps,
                    left,
                    right,
                    "ambiguous Chicago fall-back hour"
                    if ambiguous
                    else "missing or unpublished supply price",
                )
                continue
            distribution = (
                self.tariff.row(left, "distribution", hourly=hourly).cents_per_kwh
                if basis == "supply_plus_distribution"
                else Decimal(0)
            )
            try:
                slot = PriceSlot(
                    start=left, end=right, import_cents_per_kwh=supply + distribution
                )
            except ValueError as exc:
                log.error("RealEnergy.prices error=%s", type(exc).__name__)
                error = AdapterUnavailable if hourly else AdapterError
                raise error(
                    "ComEd scheduling price exceeds the supported numeric range."
                ) from None
            slots.append(slot)
        if not hourly or basis == "supply_plus_distribution":
            urls += [
                r.source_url
                for r in self.tariff.rows
                if (not hourly or r.component == "distribution")
                and (basis != "supply_only" or r.component == "supply")
            ]
        label = (
            "real (published ComEd rate)"
            if not hourly
            else (
                "real (ComEd day-ahead forecast; publication time unknown)"
                if kind == "day_ahead"
                else "real (ComEd realtime quoted supply; not finalized hourly billing)"
            )
        )
        return PriceSeries(
            requested_start=start,
            requested_end=end,
            rate_plan="comed_hourly" if hourly else "comed_time_of_day",
            kind=kind,
            basis=basis,
            slots=tuple(slots),
            gaps=tuple(gaps),
            source="real",
            source_label=label,
            source_urls=tuple(dict.fromkeys(urls)),
            tariff_version=self.tariff.version
            if not hourly or basis != "supply_only"
            else None,
            retrieved_at=utc(self.clock()) if hourly else None,
        )

    async def get_weather(self, start: datetime, end: datetime) -> WeatherSeries:
        self.ready()
        validate_range(start, end)
        start, end = utc(start), utc(end)
        location = self.household.location
        if location is None:
            raise AdapterUnavailable("Household weather coordinates are unavailable.")
        today = datetime.combine(utc(self.clock()).date(), time(), UTC)
        if start < today or end > today + timedelta(days=16):
            raise AdapterError(
                "Weather requires dates within the current 16-day UTC forecast horizon."
            )
        text, url = await self.fetch(
            OPEN_METEO,
            {
                "latitude": str(location.latitude),
                "longitude": str(location.longitude),
                "hourly": "temperature_2m,cloud_cover",
                "temperature_unit": "fahrenheit",
                "timezone": "UTC",
                "forecast_days": "16",
            },
        )
        try:
            values = feeds.weather(text)
        except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
            log.error("RealEnergy.get_weather error=%s", type(exc).__name__)
            raise AdapterUnavailable("Invalid Open-Meteo forecast response.") from None
        samples: list[WeatherSample] = []
        gaps: list[Gap] = []
        for at, left, right in intervals(start, end, 60):
            sample = values.get(at)
            if sample is None:
                add_gap(gaps, left, right, "missing forecast hour")
            else:
                samples.append(
                    WeatherSample(
                        at=left,
                        temp_f=sample.temp_f,
                        cloud_cover_percent=sample.cloud_cover_percent,
                    )
                )
        return WeatherSeries(
            requested_start=start,
            requested_end=end,
            samples=tuple(samples),
            gaps=tuple(gaps),
            source="real",
            source_label="real (Open-Meteo forecast)",
            source_urls=(url,),
            tariff_version=None,
            retrieved_at=utc(self.clock()),
        )

    async def get_tariff_state(self) -> Observation:
        self.ready()
        if "get_tariff_state" not in self.capabilities:
            raise AdapterUnavailable("Hourly Pricing has no fixed tariff band.")
        at = utc(self.clock())
        self.tariff.row(at, "supply")
        self.tariff.row(at, "distribution")
        return Observation(
            id=uuid4(),
            household_id=self.household_id,
            domain="energy",
            observed_at=at,
            source="real",
            state=ObservationState(price_band=period(at), available=True),
        )

    async def get_battery(self, entity_id: str) -> Observation:
        raise AdapterUnavailable(
            "Real battery/solar state unavailable; actual state unknown."
        )

    get_solar = get_battery

    async def dispatch_battery(self, action: Action, decision: Decision) -> None:
        raise AdapterUnavailable("Real energy action execution is unavailable.")


def factories(*, delivery_class: str, tariff_path: Path) -> dict[Key, Factory]:
    return {
        ("energy", "real"): lambda household: RealEnergy(
            household, delivery_class=delivery_class, tariff_path=tariff_path
        )
    }
