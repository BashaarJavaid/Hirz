"""ev contract. Methods do not implement or authorize operations."""

from typing import Protocol

from hirz.adapters.base import Adapter
from hirz.graph.models import Observation
from hirz.pipeline.models import Action, Decision


class EVAdapter(Adapter, Protocol):
    async def get_charge_state(self, entity_id: str) -> Observation: ...

    async def set_charge_limit(self, action: Action, decision: Decision) -> None: ...

    async def start_charge(self, action: Action, decision: Decision) -> None: ...

    async def stop_charge(self, action: Action, decision: Decision) -> None: ...

    async def set_schedule(self, action: Action, decision: Decision) -> None: ...
