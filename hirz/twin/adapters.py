"""Shared read lifecycle and the plain factory map for household twin adapters."""

from collections.abc import AsyncIterator
from datetime import datetime
from uuid import UUID

from hirz.adapters.base import Adapter, AdapterError, AdapterUnavailable
from hirz.adapters.registry import Factory, Key, Registry
from hirz.graph.models import AdapterDomain, Household, Observation, ObservationState
from hirz.pipeline.models import Action, Decision
from hirz.twin.world import State, TwinWorld


class TwinAdapter:
    domain: AdapterDomain
    capabilities: frozenset[str]

    def __init__(self, world: TwinWorld):
        self.world = world
        self.household_id = world.household.id
        self.started = False

    async def start(self) -> None:
        self.started = True

    async def close(self) -> None:
        self.started = False

    def read(self) -> tuple[datetime, State]:
        if not self.started:
            raise AdapterUnavailable("Twin adapter is not started.")
        return self.world.read()

    async def unavailable(self, action: Action, decision: Decision) -> None:
        raise AdapterUnavailable("Twin action execution is not implemented.")

    set_climate = set_light = set_cover = unavailable
    set_charge_limit = start_charge = stop_charge = set_schedule = unavailable
    dispatch_battery = send_checkin = callback = unavailable

    def subscribe(self) -> AsyncIterator[Observation]:
        raise AdapterUnavailable("Twin subscriptions are not implemented.")

    def asset_state(self, entity_id: str, expected: str | None = None) -> Observation:
        at, state = self.read()
        ident = self.world.entity(entity_id, self.domain)
        kind = self.world.assets[ident].kind
        if expected is not None and kind != expected:
            raise AdapterError("Entity does not support this read.")
        if ident in state.evs:
            ev = state.evs[ident]
            values = ObservationState(
                charging=ev.charging,
                charge_limit=ev.charge_limit,
                soc=ev.soc,
                plugged_in=ev.plugged_in,
                power_kw=ev.power_kw,
                available=True,
            )
        elif ident in state.batteries:
            b = state.batteries[ident]
            power = min(abs(b.dispatch_kw), b.power_kw)
            power = (
                (power if b.soc > b.reserve_soc else 0)
                if b.dispatch_kw >= 0
                else (-power if b.soc < 1 else 0)
            )
            values = ObservationState(
                soc=b.soc, power_kw=power, dispatch_kw=b.dispatch_kw, available=True
            )
        elif ident in state.zones:
            z = state.zones[ident]
            values = ObservationState(
                temp_f=z.temp_f, target_f=z.target_f, mode=z.mode, available=True
            )
        elif ident in state.appliances:
            a = state.appliances[ident]
            values = ObservationState(on=a.running, power_kw=a.power_kw, available=True)
        elif ident in self.world.solar:
            values = ObservationState(
                power_kw=self.world.solar_power(ident, at), available=True
            )
        else:
            values = state.devices[ident].state
            if values.available is False:
                values = ObservationState(available=False)
        return self.world.observation(self.domain, ident, values, at)

    def member(self, member_id: UUID) -> None:
        if member_id not in self.world.members:
            raise AdapterError("Unknown twin member.")


def factories(world: TwinWorld) -> dict[Key, Factory]:
    from hirz.adapters.calendar.twin import TwinCalendar
    from hirz.adapters.contacts.twin import TwinContacts
    from hirz.adapters.devices.twin import TwinDevices
    from hirz.adapters.doorbell.twin import TwinDoorbell
    from hirz.adapters.energy.twin import TwinEnergy
    from hirz.adapters.ev.twin import TwinEV
    from hirz.adapters.presence.twin import TwinPresence
    from hirz.adapters.wearable.twin import TwinWearable

    classes = (
        TwinDevices,
        TwinEV,
        TwinEnergy,
        TwinPresence,
        TwinWearable,
        TwinCalendar,
        TwinContacts,
        TwinDoorbell,
    )

    def factory(cls: type[TwinAdapter]) -> Factory:
        def create(household: Household) -> Adapter:
            # Live policy activation and pause change governance, not which
            # physical twin these factories belong to. A mixed home also keeps
            # its real rate plan while its explicit simulation uses twin prices.
            runtime = {"rate_plan", "constitution_version", "autonomy_paused"}
            if household.model_dump(exclude=runtime) != world.household.model_dump(
                exclude=runtime
            ):
                raise AdapterError("Twin factory belongs to another household.")
            return cls(world)

        return create

    return {(cls.domain, "twin"): factory(cls) for cls in classes}


def registry(world: TwinWorld, config: str | None = None) -> Registry:
    return Registry(
        world.household,
        members=tuple(world.members.values()),
        assets=tuple(world.assets.values()),
        bindings=tuple(world.bindings.values()),
        factories=factories(world),
        sources={},
        config=config,
        clock=world.clock,
    )
