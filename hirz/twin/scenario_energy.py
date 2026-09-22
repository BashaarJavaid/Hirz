"""Published local Time-of-Day rates and supplied weather; no network client."""

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from hirz.adapters.base import PriceKind, PriceSeries, PriceSlot
from hirz.adapters.energy.real.tariff import load_tariff, period
from hirz.adapters.energy.twin import TwinEnergy
from hirz.graph.models import Observation, ObservationState
from hirz.planner.models import boundaries


class ScenarioEnergy(TwinEnergy):
    async def get_prices(
        self, start: datetime, end: datetime, kind: PriceKind
    ) -> PriceSeries:
        self.read()
        self.world.check_range(start, end)
        tariff = load_tariff(Path("tariffs/comed-time-of-day.yaml"))
        edges = boundaries(start, end)
        return PriceSeries(
            requested_start=start,
            requested_end=end,
            rate_plan="comed_time_of_day",
            kind=kind,
            basis="supply_plus_distribution",
            slots=tuple(
                PriceSlot(
                    start=a,
                    end=b,
                    import_cents_per_kwh=Decimal(
                        sum(
                            tariff.row(a, c).cents_per_kwh
                            for c in ("supply", "distribution")
                        )
                    ),
                )
                for a, b in zip(edges, edges[1:])
            ),
            gaps=(),
            source="real",
            source_label="real (published ComEd rate)",
            source_urls=tuple(s.url for s in tariff.sources),
            tariff_version=tariff.version,
            retrieved_at=None,
        )

    async def get_tariff_state(self) -> Observation:
        at, _ = self.read()
        return self.world.observation(
            "energy",
            self.household_id,
            ObservationState(price_band=period(at), available=True),
            at,
        ).model_copy(update={"source": "real"})
