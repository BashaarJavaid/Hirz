"""Serialize local execution and recover preauthorized endings without the cloud."""

import asyncio
import math
from collections.abc import Awaitable, Callable
from datetime import datetime

from pydantic import JsonValue

from hirz.graph.models import now
from hirz.link.command import Envelope
from hirz.link.store import Store
from hirz.pipeline.models import Action


class Agent:
    def __init__(
        self,
        store: Store,
        apply: Callable[[Envelope, Action], Awaitable[dict[str, JsonValue]]],
        *,
        clock: Callable[[], datetime] = now,
    ):
        self.store, self.apply, self.clock = store, apply, clock
        self.lock = store.execution_lock

    async def _apply(
        self, envelope: Envelope, action: Action, *, reverting: bool
    ) -> bool:
        matched = False
        try:
            async with asyncio.timeout(10):
                observed = await self.apply(envelope, action)
            effect = action.expected_effect
            assert effect is not None
            actual = observed.get(effect.attr)
            if type(effect.value) is bool:
                matched = type(actual) is bool and actual == effect.value
            elif type(effect.value) in (int, float) and type(actual) in (int, float):
                matched = math.isclose(
                    float(str(actual)),
                    float(str(effect.value)),
                    abs_tol=1e-6,
                    rel_tol=0,
                )
            else:
                matched = actual == effect.value
        except Exception:
            # Keep uncertain openings consumed and failed endings pending for retry.
            matched = False
        self.store.complete(
            envelope.command.action.action_id,
            self.clock(),
            matched=matched,
            reverting=reverting,
        )
        return matched

    async def _recover(self) -> None:
        for envelope, action in self.store.due(self.clock()):
            await self._apply(envelope, action, reverting=True)

    async def recover(self) -> None:
        async with self.lock:
            await self._recover()

    async def receive(self, value: object) -> bool:
        async with self.lock:
            await self._recover()
            envelope = self.store.reserve(value, self.clock())
            return await self._apply(envelope, envelope.command.action, reverting=False)
