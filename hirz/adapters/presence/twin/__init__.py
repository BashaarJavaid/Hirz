"""One explicit presence reading per household member."""

from hirz.graph.models import AdapterDomain, Observation, ObservationState
from hirz.twin.adapters import TwinAdapter


class TwinPresence(TwinAdapter):
    domain: AdapterDomain = "presence"
    capabilities = frozenset({"who_is_home"})

    async def who_is_home(self) -> tuple[Observation, ...]:
        at, state = self.read()
        return tuple(
            self.world.observation(
                "presence",
                i,
                ObservationState(
                    present=p.present,
                    sleeping=p.sleeping,
                    zone_id=p.zone_id,
                    available=True,
                ),
                at,
            )
            for i, p in sorted(state.presence.items())
        )
