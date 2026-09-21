"""doorbell contract. Methods do not implement or authorize operations."""

from collections.abc import Mapping
from typing import Protocol

from hirz.adapters.base import Adapter
from hirz.graph.models import Observation


class DoorbellAdapter(Adapter, Protocol):
    async def on_event(
        self, body: bytes, headers: Mapping[str, str]
    ) -> tuple[Observation, ...]: ...

    async def snapshot(self, entity_id: str) -> bytes | None: ...

    async def live_view_url(self, entity_id: str) -> str | None: ...
