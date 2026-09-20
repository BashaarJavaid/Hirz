"""Synthetic energy reads; prices never impersonate a published tariff."""

from datetime import datetime

from hirz.adapters.base import PriceKind, PriceSeries, WeatherSeries
from hirz.graph.models import AdapterDomain, Observation, ObservationState
from hirz.twin.adapters import TwinAdapter
from hirz.twin.world import TwinWorld


class TwinEnergy(TwinAdapter):
    domain: AdapterDomain = "energy"
    capabilities = frozenset(
        {"get_prices", "get_weather", "get_battery", "get_solar", "get_tariff_state"}
    )

    def __init__(self, world: TwinWorld):
        super().__init__(world)
        if all(p.export_cents_per_kwh is not None for p in world.config.tariff.periods):
            self.capabilities = self.capabilities | {"has_export_price"}

    async def get_prices(
        self, start: datetime, end: datetime, kind: PriceKind
    ) -> PriceSeries:
        self.read()
        w = self.world
        slots = w.config.tariff.prices(
            start,
            end,
            kind,
            origin=w.config.start,
            horizon=w.config.end,
            timezone=w.household.timezone,
            seed=w.config.seed,
            home=w.household.id,
        )

        return PriceSeries(
            requested_start=start,
            requested_end=end,
            rate_plan="twin",
            kind=kind,
            basis="supply_plus_distribution",
            slots=slots,
            gaps=(),
            source="twin",
            source_label="twin (synthetic tariff)",
            source_urls=(),
            tariff_version=None,
            retrieved_at=None,
        )

    async def get_weather(self, start: datetime, end: datetime) -> WeatherSeries:
        self.read()
        self.world.check_range(start, end)
        return WeatherSeries(
            requested_start=start,
            requested_end=end,
            samples=self.world.config.weather.between(start, end),
            gaps=(),
            source="twin",
            source_label="twin (supplied weather)",
            source_urls=(),
            tariff_version=None,
            retrieved_at=None,
        )

    async def get_tariff_state(self) -> Observation:
        at, _ = self.read()
        band = self.world.config.tariff.period(at, self.world.household.timezone).band
        return self.world.observation(
            "energy",
            self.household_id,
            ObservationState(price_band=band, available=True),
            at,
        )

    async def get_battery(self, entity_id: str) -> Observation:
        return self.asset_state(entity_id, "home_battery")

    async def get_solar(self, entity_id: str) -> Observation:
        return self.asset_state(entity_id, "solar")
