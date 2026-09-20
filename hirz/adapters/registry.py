"""Explicit household configuration, lifecycle and observation provenance."""

import os
from asyncio import CancelledError
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import cast, get_args
from uuid import UUID

from hirz.adapters.base import Adapter, AdapterError, AdapterUnavailable
from hirz.graph.models import (
    ADAPTER_DOMAINS,
    ASSET_DOMAINS,
    AdapterDomain,
    Asset,
    AssetBinding,
    Household,
    Member,
    Observation,
    Source,
    now,
    observation_subject,
    validate_observation_scope,
)

CAPABILITIES: dict[AdapterDomain, frozenset[str]] = {
    "devices": frozenset(
        {
            "list_entities",
            "get_state",
            "subscribe",
            "set_climate",
            "set_light",
            "set_cover",
        }
    ),
    "ev": frozenset(
        {
            "get_charge_state",
            "set_charge_limit",
            "start_charge",
            "stop_charge",
            "set_schedule",
        }
    ),
    "energy": frozenset(
        {
            "get_prices",
            "get_supply_history",
            "get_tariff_state",
            "get_weather",
            "get_battery",
            "dispatch_battery",
            "get_solar",
            "has_export_price",
        }
    ),
    "wearable": frozenset({"get_recovery"}),
    "calendar": frozenset({"list_events", "expected_arrivals"}),
    "contacts": frozenset({"verified_channels", "send_checkin", "callback"}),
    "doorbell": frozenset({"on_event", "snapshot", "live_view_url"}),
    "notify": frozenset({"push", "email"}),
    "presence": frozenset({"who_is_home"}),
}
Key = tuple[AdapterDomain, str]
Factory = Callable[[Household], Adapter]


def parse_config(value: str | None = None) -> dict[AdapterDomain, str]:
    """None reads the environment; an explicit empty string enables no defaults."""
    text = os.environ.get("HIRZ_ADAPTERS", "") if value is None else value
    result: dict[AdapterDomain, str] = {}
    if not text.strip():
        return result
    for entry in text.split(","):
        parts = [part.strip() for part in entry.split(":")]
        if len(parts) != 2 or parts[0] not in ADAPTER_DOMAINS or not parts[1]:
            raise AdapterError("Invalid HIRZ_ADAPTERS entry.")
        domain = cast(AdapterDomain, parts[0])
        if domain in result:
            raise AdapterError("Duplicate adapter domain.")
        result[domain] = parts[1]
    return result


class Registry:
    def __init__(
        self,
        household: Household,
        *,
        members: tuple[Member, ...] = (),
        assets: tuple[Asset, ...] = (),
        bindings: tuple[AssetBinding, ...] = (),
        factories: Mapping[Key, Factory],
        sources: Mapping[tuple[AdapterDomain, str, UUID], Source],
        config: str | None = None,
        scenario_mode: bool = False,
        fallback_bindings: tuple[AssetBinding, ...] = (),
    ):
        self.household = Household.model_validate(household.model_dump())
        self.members = {m.id: Member.model_validate(m.model_dump()) for m in members}
        self.assets = {a.id: Asset.model_validate(a.model_dump()) for a in assets}
        self.bindings = {
            b.asset_id: AssetBinding.model_validate(b.model_dump()) for b in bindings
        }
        if (
            len(self.members) != len(members)
            or len(self.assets) != len(assets)
            or len(self.bindings) != len(bindings)
        ):
            raise AdapterError("Duplicate household adapter subject or binding.")
        if any(
            row.household_id != household.id
            for row in (
                *self.members.values(),
                *self.assets.values(),
                *self.bindings.values(),
            )
        ):
            raise AdapterError("Invalid adapter household scope.")
        if not self.bindings.keys() <= self.assets.keys():
            raise AdapterError("Binding names an unknown household asset.")
        self.defaults = parse_config(config)
        self.factories = dict(factories)
        self.sources = dict(sources)
        self.instances: dict[Key, Adapter] = {}
        self.started = False
        self.selected: set[Key] = set(self.defaults.items())
        self.selected.update(
            (ASSET_DOMAINS[self.assets[b.asset_id].kind], b.adapter)
            for b in self.bindings.values()
        )
        self.fallback_bindings = {
            b.asset_id: AssetBinding.model_validate(b.model_dump())
            for b in fallback_bindings
        }
        if (
            type(scenario_mode) is not bool
            or fallback_bindings
            and not scenario_mode
            or len(self.fallback_bindings) != len(fallback_bindings)
            or any(
                b.household_id != household.id
                or b.adapter != "twin"
                or b.asset_id not in self.bindings
                or self.bindings[b.asset_id].adapter == "twin"
                or ASSET_DOMAINS[self.assets[b.asset_id].kind] != "devices"
                for b in fallback_bindings
            )
        ):
            raise AdapterError("Invalid scenario fallback binding.")
        self.fallback_keys: set[Key] = (
            {("devices", "twin")} if fallback_bindings else set()
        )
        if not self.selected | self.fallback_keys <= self.factories.keys():
            raise AdapterError("Selected adapter implementation is not registered.")
        for (domain, implementation, subject), source in self.sources.items():
            if (
                domain,
                implementation,
            ) not in self.selected | self.fallback_keys or source not in get_args(
                Source
            ):
                raise AdapterError("Invalid adapter source registration.")
            if subject not in {*self.members, *self.assets, household.id}:
                raise AdapterError("Unknown source-registration subject.")
            if implementation == "twin" and source != "twin":
                raise AdapterError("Twin provenance cannot be relabeled.")

    async def start(self) -> None:
        if self.started or self.instances:
            raise AdapterError("Registry is already started.")
        try:
            for key in sorted(self.selected | self.fallback_keys):
                adapter = self.factories[key](self.household)
                # Register before start so partial initialization is also closed.
                self.instances[key] = adapter
                if adapter.household_id != self.household.id:
                    raise AdapterError("Adapter belongs to another household.")
                capabilities = adapter.capabilities
                if (
                    not isinstance(capabilities, frozenset)
                    or not capabilities <= CAPABILITIES[key[0]]
                ):
                    raise AdapterError("Invalid adapter capabilities.")
                if any(
                    not callable(getattr(adapter, name, None))
                    for name in capabilities - {"has_export_price"}
                ):
                    raise AdapterError("Advertised adapter method is missing.")
                await adapter.start()
            self.started = True
        except BaseException as exc:
            try:
                await self.close()
            finally:
                if isinstance(exc, (CancelledError, KeyboardInterrupt, SystemExit)):
                    raise exc
                # Never expose a factory/transport exception containing credentials.
                raise AdapterError("Adapter startup failed; registry closed.") from None

    async def close(self) -> None:
        failed = False
        instances, self.instances = self.instances, {}
        self.started = False
        for adapter in reversed(tuple(instances.values())):
            try:
                await adapter.close()
            except Exception:
                failed = True
        if failed:
            raise AdapterError("Adapter cleanup failed.")

    def key(self, domain: AdapterDomain, asset_id: UUID | None = None) -> Key:
        implementation = self.defaults.get(domain)
        if asset_id is not None:
            asset = self.assets.get(asset_id)
            if asset is None or ASSET_DOMAINS[asset.kind] != domain:
                raise AdapterError("Invalid adapter asset/domain.")
            if binding := self.bindings.get(asset_id):
                implementation = binding.adapter
        if implementation is None:
            raise AdapterUnavailable("Adapter unavailable; actual state unknown.")
        return domain, implementation

    def resolve(
        self,
        domain: AdapterDomain,
        *,
        asset_id: UUID | None = None,
        capability: str | None = None,
    ) -> Adapter:
        if not self.started:
            raise AdapterUnavailable("Adapter registry is not started.")
        adapter = self.instances[self.key(domain, asset_id)]
        if capability is not None and capability not in adapter.capabilities:
            raise AdapterUnavailable("Capability is not available in this home.")
        return adapter

    async def get_state(self, asset_id: UUID) -> Observation:
        """Scenario-only read fallback; resolve() and write routing stay primary."""
        from hirz.adapters.devices import DevicesAdapter

        adapter = cast(
            DevicesAdapter,
            self.resolve("devices", asset_id=asset_id, capability="get_state"),
        )
        binding = self.bindings.get(asset_id)
        if binding is None:
            raise AdapterError("State reads require an explicit asset binding.")
        try:
            row = self.stamp(
                "devices",
                binding.adapter,
                await adapter.get_state(binding.entity_id),
                at=now(),
            )
            if row.asset_id != asset_id:
                raise AdapterError("Adapter returned another asset.")
            if row.state.available is False:
                raise AdapterUnavailable("Adapter unavailable; actual state unknown.")
            return row
        except AdapterUnavailable:
            fallback = self.fallback_bindings.get(asset_id)
            if fallback is None:
                raise AdapterUnavailable(
                    "Adapter unavailable; actual state unknown."
                ) from None
        twin = cast(DevicesAdapter, self.instances[("devices", "twin")])
        if "get_state" not in twin.capabilities:
            raise AdapterUnavailable("Scenario fallback state unavailable.")
        try:
            row = Observation.model_validate(
                (await twin.get_state(fallback.entity_id)).model_dump()
            )
            validate_observation_scope(
                row,
                self.household.id,
                self.members.keys(),
                {i: a.kind for i, a in self.assets.items()},
                now(),
            )
            if (
                row.source != "twin"
                or row.asset_id != asset_id
                or row.domain != "devices"
            ):
                raise ValueError
            return row
        except (ValueError, KeyError):
            raise AdapterError("Invalid scenario fallback provenance.") from None

    def stamp(
        self,
        domain: AdapterDomain,
        implementation: str,
        observation: Observation,
        *,
        at: datetime,
    ) -> Observation:
        """Validate and stamp a whole reading; this never persists graph state."""
        try:
            row = Observation.model_validate(observation.model_dump())
            validate_observation_scope(
                row,
                self.household.id,
                self.members.keys(),
                {i: a.kind for i, a in self.assets.items()},
                at,
            )
            key = self.key(domain, row.asset_id)
            if not self.started or key != (domain, implementation):
                raise AdapterError("Observation does not match the selected adapter.")
            source = (
                "twin"
                if implementation == "twin"
                else self.sources.get(
                    (domain, implementation, observation_subject(row))
                )
            )
            if source is None or row.source != source or row.domain != domain:
                raise AdapterError(
                    "Observation provenance conflicts with registration."
                )
            return Observation.model_validate(
                row.model_dump() | {"domain": domain, "source": source}
            )
        except (ValueError, KeyError):
            raise AdapterError(
                "Invalid adapter observation; payload withheld."
            ) from None
