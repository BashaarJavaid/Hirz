"""energy contract. Methods do not implement or authorize operations."""

from datetime import datetime
from typing import Protocol

from hirz.adapters.base import Adapter, PriceKind, PriceSeries, WeatherSeries
from hirz.graph.models import Observation
from hirz.pipeline.models import Action, Decision


class EnergyAdapter(Adapter, Protocol):
    async def get_tariff_state(self) -> Observation: ...

    async def get_prices(
        self, start: datetime, end: datetime, kind: PriceKind
    ) -> PriceSeries: ...

    async def get_weather(self, start: datetime, end: datetime) -> WeatherSeries: ...

    async def get_battery(self, entity_id: str) -> Observation: ...

    async def get_solar(self, entity_id: str) -> Observation: ...

    async def dispatch_battery(self, action: Action, decision: Decision) -> None: ...
