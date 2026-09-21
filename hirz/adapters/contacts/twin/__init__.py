"""Redacted verified-channel reads; private calls and scripts never escape here."""

from uuid import UUID

from hirz.adapters.base import AdapterError
from hirz.graph.context import ChannelSummary
from hirz.graph.models import AdapterDomain, utc
from hirz.twin.adapters import TwinAdapter


class TwinContacts(TwinAdapter):
    domain: AdapterDomain = "contacts"
    capabilities = frozenset({"verified_channels"})

    async def verified_channels(self, contact_id: UUID) -> tuple[ChannelSummary, ...]:
        at, _ = self.read()
        if contact_id not in self.world.contacts:
            raise AdapterError("Unknown twin contact.")
        return tuple(
            c
            for c in self.world.channels
            if c.contact_id == contact_id
            and c.verified_at is not None
            and utc(c.verified_at) <= utc(at)
        )
