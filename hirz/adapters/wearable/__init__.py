"""wearable contract. Methods do not implement or authorize operations."""

from typing import Protocol
from uuid import UUID

from hirz.adapters.base import Adapter
from hirz.graph.models import Observation


class WearableAdapter(Adapter, Protocol):
    async def get_recovery(self, member_id: UUID) -> Observation: ...
