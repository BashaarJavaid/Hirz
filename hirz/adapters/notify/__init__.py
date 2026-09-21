"""notify contract. Methods do not implement or authorize operations."""

from typing import Protocol

from hirz.adapters.base import Adapter
from hirz.pipeline.models import Action, Decision


class NotifyAdapter(Adapter, Protocol):
    async def push(self, action: Action, decision: Decision) -> None: ...

    async def email(self, action: Action, decision: Decision) -> None: ...
