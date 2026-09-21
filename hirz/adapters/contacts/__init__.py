"""contacts contract. Methods do not implement or authorize operations."""

from typing import Protocol
from uuid import UUID

from hirz.adapters.base import Adapter
from hirz.graph.context import ChannelSummary
from hirz.pipeline.models import Action, Decision


class ContactsAdapter(Adapter, Protocol):
    async def verified_channels(
        self, contact_id: UUID
    ) -> tuple[ChannelSummary, ...]: ...

    async def send_checkin(self, action: Action, decision: Decision) -> None: ...

    async def callback(self, action: Action, decision: Decision) -> None: ...
