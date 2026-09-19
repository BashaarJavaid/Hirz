"""presence contract. Methods do not implement or authorize operations."""

from typing import Protocol

from hirz.adapters.base import Adapter
from hirz.graph.models import Observation


class PresenceAdapter(Adapter, Protocol):
    async def who_is_home(self) -> tuple[Observation, ...]: ...
