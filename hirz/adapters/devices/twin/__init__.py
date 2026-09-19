"""Read-only simulated devices."""

from hirz.graph.models import ASSET_DOMAINS, AdapterDomain, Observation
from hirz.twin.adapters import TwinAdapter


class TwinDevices(TwinAdapter):
    domain: AdapterDomain = "devices"
    capabilities = frozenset({"list_entities", "get_state"})

    async def list_entities(self) -> tuple[str, ...]:
        self.read()
        return tuple(
            sorted(
                b.entity_id
                for i, b in self.world.bindings.items()
                if b.adapter == "twin"
                and ASSET_DOMAINS[self.world.assets[i].kind] == self.domain
            )
        )

    async def get_state(self, entity_id: str) -> Observation:
        return self.asset_state(entity_id)
