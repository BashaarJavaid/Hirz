"""Home-only HA transport; the signed journal replaces a cloud device credential."""

import asyncio
import math
from collections.abc import Callable
from datetime import datetime

from pydantic import JsonValue

from hirz.adapters.base import AdapterError
from hirz.adapters.devices.ha import HomeAssistant, fahrenheit
from hirz.graph.models import now
from hirz.link.command import Envelope
from hirz.link.store import Store
from hirz.pipeline.models import Action


class Devices:
    def __init__(
        self,
        adapter: HomeAssistant,
        store: Store,
        *,
        clock: Callable[[], datetime] = now,
    ):
        if adapter.household_id != store.home_id or adapter.pipeline is not None:
            raise ValueError("Link owns an unprivileged HA reader for its pinned home")
        self.adapter, self.store, self.clock = adapter, store, clock

    async def __call__(
        self, envelope: Envelope, action: Action
    ) -> dict[str, JsonValue]:
        self.store.authorized(envelope, action, self.clock())
        binding = self.adapter.binding(action.target.entity)
        if action.target.adapter != "ha" or (
            action.target.zone is not None
            and action.target.zone != str(binding.asset_id)
        ):
            raise AdapterError("Signed target does not match the local HA binding")
        climate = action.action_class == "energy.hvac_adjust"
        domain = action.target.entity.split(".")[0]
        if (climate and domain != "climate") or (
            not climate
            and (
                action.action_class != "environment.lights"
                or domain not in {"light", "switch"}
            )
        ):
            raise AdapterError("Unsupported Link device class")
        if climate:
            params = await self.adapter.climate_params(action)
            service = "set_temperature"
        else:
            before = await self.adapter.raw_state(action.target.entity)
            if before["state"] not in {"on", "off"}:
                raise AdapterError("Home Assistant unavailable; actual state unknown")
            params = {}
            service = "turn_on" if action.params["on"] else "turn_off"
        # Recheck expiry after reads; only the home has this HA token.
        self.store.authorized(envelope, action, self.clock())
        await self.adapter.request(
            "POST",
            f"/api/services/{domain}/{service}",
            {"entity_id": action.target.entity, **params},
        )
        async with asyncio.timeout(5):
            while True:
                result = await self.adapter.raw_state(action.target.entity)
                if climate:
                    target = fahrenheit(
                        result["attributes"]["temperature"],
                        await self.adapter.temperature_unit(),
                    )
                    observed: dict[str, JsonValue] = {"target_f": target}
                    matched = math.isclose(
                        target,
                        float(str(action.params["target_f"])),
                        abs_tol=1e-6,
                        rel_tol=0,
                    )
                else:
                    if result["state"] not in {"on", "off"}:
                        raise AdapterError(
                            "Home Assistant unavailable; actual state unknown"
                        )
                    observed = {"on": result["state"] == "on"}
                    matched = observed["on"] is action.params["on"]
                if matched:
                    return observed
                await asyncio.sleep(0.1)
