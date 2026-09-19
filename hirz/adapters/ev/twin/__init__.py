"""Read-only simulated EV."""

from hirz.graph.models import AdapterDomain, Observation
from hirz.twin.adapters import TwinAdapter


class TwinEV(TwinAdapter):
    domain: AdapterDomain = "ev"
    capabilities = frozenset({"get_charge_state"})

    async def get_charge_state(self, entity_id: str) -> Observation:
        return self.asset_state(entity_id, "ev")
