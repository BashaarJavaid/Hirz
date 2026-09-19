"""devices contract. Methods do not implement or authorize operations."""

from collections.abc import AsyncIterator
from typing import Protocol

from hirz.adapters.base import Adapter
from hirz.graph.models import Observation
from hirz.pipeline.models import Action, Decision


class DevicesAdapter(Adapter, Protocol):
    async def list_entities(self) -> tuple[str, ...]: ...

    async def get_state(self, entity_id: str) -> Observation: ...

    def subscribe(self) -> AsyncIterator[Observation]: ...

    async def set_climate(self, action: Action, decision: Decision) -> None: ...

    async def set_light(self, action: Action, decision: Decision) -> None: ...

    async def set_cover(self, action: Action, decision: Decision) -> None: ...
