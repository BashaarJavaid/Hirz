"""Synthetic recovery reads, separate from presence."""

from uuid import UUID

from hirz.graph.models import AdapterDomain, Observation, ObservationState
from hirz.twin.adapters import TwinAdapter


class TwinWearable(TwinAdapter):
    domain: AdapterDomain = "wearable"
    capabilities = frozenset({"get_recovery"})

    async def get_recovery(self, member_id: UUID) -> Observation:
        at, state = self.read()
        self.member(member_id)
        return self.world.observation(
            "wearable",
            member_id,
            ObservationState(
                recovery_score=state.recovery[member_id].score, available=True
            ),
            at,
        )
