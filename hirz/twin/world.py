"""One household's explicit simulation state; no database or action execution."""

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Annotated, Self, TypeVar
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, Field, model_validator

from hirz.adapters.base import AdapterError, validate_range
from hirz.graph.context import ChannelSummary
from hirz.graph.models import (
    ASSET_DOMAINS,
    AdapterDomain,
    Asset,
    AssetBinding,
    Household,
    Member,
    Model,
    Observation,
    ObservationState,
    ScheduleEvent,
    TrustedContact,
    utc,
)
from hirz.twin.clock import SimClock
from hirz.twin.environment import Solar, Tariff, Weather, stream
from hirz.twin.people import (
    ContactScript,
    Device,
    InboundCall,
    Presence,
    Recovery,
    WeeklyTransition,
    local_instant,
    presence_change,
)
from hirz.twin.physics import EV, Appliance, Battery, Nonnegative, ThermalZone, changed

M = TypeVar("M", bound=Model)


class Coupling(Model):
    left: UUID
    right: UUID
    conductance: Nonnegative = 0.01


class Override(Model):
    at: AwareDatetime
    member_id: UUID
    presence: Presence | None = None
    recovery_score: Annotated[int, Field(ge=0, le=100)] | None = None

    @model_validator(mode="after")
    def one(self) -> Self:
        if (self.presence is None) == (self.recovery_score is None):
            raise ValueError("Override requires exactly one state.")
        return self


class TwinConfig(Model):
    start: AwareDatetime
    end: AwareDatetime
    seed: int
    base_load_kw: Nonnegative
    weather: Weather
    tariff: Tariff
    evs: dict[UUID, EV]
    batteries: dict[UUID, Battery]
    zones: dict[UUID, ThermalZone]
    solar: dict[UUID, Solar]
    appliances: dict[UUID, Appliance]
    devices: dict[UUID, Device]
    presence: dict[UUID, Presence]
    weekly: dict[UUID, tuple[WeeklyTransition, ...]]
    recovery: dict[UUID, Recovery]
    couplings: tuple[Coupling, ...]
    overrides: tuple[Override, ...]
    contact_scripts: tuple[ContactScript, ...]
    inbound_calls: tuple[InboundCall, ...]

    @model_validator(mode="after")
    def coverage(self) -> Self:
        if utc(self.start) >= utc(self.end):
            raise ValueError("Simulation needs a positive horizon.")
        if utc(self.weather.start) > utc(self.start) or utc(self.weather.end) < utc(
            self.end
        ):
            raise ValueError("Weather must cover simulation horizon.")
        if any(
            not utc(self.start) <= utc(o.at) <= utc(self.end) for o in self.overrides
        ):
            raise ValueError("Override outside simulation horizon.")
        return self


class State(Model):
    evs: dict[UUID, EV]
    batteries: dict[UUID, Battery]
    zones: dict[UUID, ThermalZone]
    appliances: dict[UUID, Appliance]
    devices: dict[UUID, Device]
    presence: dict[UUID, Presence]
    recovery: dict[UUID, Recovery]
    load_kwh: Nonnegative = 0
    pv_kwh: Nonnegative = 0
    import_kwh: Nonnegative = 0
    export_kwh: Nonnegative = 0
    events: tuple[tuple[datetime, str, UUID], ...] = ()


class TwinWorld:
    def __init__(
        self,
        household: Household,
        *,
        members: tuple[Member, ...],
        assets: tuple[Asset, ...],
        bindings: tuple[AssetBinding, ...],
        contacts: tuple[TrustedContact, ...],
        channels: tuple[ChannelSummary, ...],
        calendar: tuple[ScheduleEvent, ...],
        config: TwinConfig,
        clock: SimClock,
    ):
        self.household = Household.model_validate(household.model_dump())
        # Preserve which physical parameters were explicitly supplied, for precedence.
        self.config = TwinConfig.model_validate(config.model_dump(exclude_unset=True))
        config = self.config
        self.clock = clock
        self.members = {m.id: Member.model_validate(m.model_dump()) for m in members}
        self.assets = {a.id: Asset.model_validate(a.model_dump()) for a in assets}
        self.bindings = {
            b.asset_id: AssetBinding.model_validate(b.model_dump()) for b in bindings
        }
        self.contacts = {
            c.id: TrustedContact.model_validate(c.model_dump()) for c in contacts
        }
        self.channels = tuple(
            ChannelSummary.model_validate(c.model_dump()) for c in channels
        )
        self.calendar = tuple(
            ScheduleEvent.model_validate(e.model_dump()) for e in calendar
        )
        for rows in (members, assets, bindings, contacts, channels, calendar):
            if len({r.id for r in rows}) != len(rows) or any(
                r.household_id != household.id for r in rows
            ):
                raise AdapterError("Duplicate or cross-household twin input.")
        if (
            len(self.bindings) != len(bindings)
            or not self.bindings.keys() <= self.assets.keys()
        ):
            raise AdapterError("Invalid twin bindings.")
        if any(
            c.contact_id not in self.contacts or c.source != "twin" for c in channels
        ):
            raise AdapterError("Invalid simulated contact channel.")
        if any(
            e.member_id is not None
            and e.member_id not in self.members
            or e.zone_id is not None
            and e.zone_id not in config.zones
            for e in calendar
        ):
            raise AdapterError("Invalid calendar subject.")
        if household.rate_plan != "twin":
            raise AdapterError("Synthetic tariff requires an explicit twin rate plan.")
        self._validate_models()
        self._scheduled = self._schedule()
        self._at = utc(config.start)
        self._last_read = self._at
        self._state = State(
            evs=self._physical(config.evs),
            batteries=self._physical(config.batteries),
            zones=self._physical(config.zones),
            appliances=self._physical(config.appliances),
            devices=dict(config.devices),
            presence=dict(config.presence),
            recovery=dict(config.recovery),
        )
        self.solar = self._physical(config.solar)
        self._validate_thermal()
        self._state = self._events(self._state, self._at)
        self._check_at(clock.now())

    def _physical(self, models: dict[UUID, M]) -> dict[UUID, M]:
        result = {}
        for ident, model in models.items():
            physical = self.assets[ident].physical
            graph = physical.model_dump(exclude_none=True) if physical else {}
            graph = {k: v for k, v in graph.items() if k in type(model).model_fields}
            result[ident] = type(model).model_validate(
                graph | model.model_dump(exclude_unset=True)
            )
        return result

    def _validate_models(self) -> None:
        c = self.config
        groups: list[tuple[Mapping[UUID, Model], set[str]]] = [
            (c.evs, {"ev"}),
            (c.batteries, {"home_battery"}),
            (c.zones, {"hvac_zone"}),
            (c.solar, {"solar"}),
            (c.appliances, {"appliance"}),
            (c.devices, {"lock", "camera", "light", "shade", "doorbell"}),
        ]
        represented: set[UUID] = set()
        for models, kinds in groups:
            if any(
                i not in self.assets or self.assets[i].kind not in kinds for i in models
            ):
                raise AdapterError("Twin model does not match household asset kind.")
            represented.update(models)
        selected = {i for i, b in self.bindings.items() if b.adapter == "twin"}
        if not selected <= represented:
            raise AdapterError("A twin binding requires explicit initial model state.")
        if (
            set(c.presence) != set(self.members)
            or set(c.weekly) != set(self.members)
            or set(c.recovery) != set(self.members)
        ):
            raise AdapterError(
                "Each member requires explicit presence, schedules and recovery."
            )
        for p in [
            *c.presence.values(),
            *(o.presence for o in c.overrides if o.presence is not None),
        ]:
            if p.zone_id is not None and p.zone_id not in c.zones:
                raise AdapterError("Unknown presence zone.")
        if any(o.member_id not in self.members for o in c.overrides):
            raise AdapterError("Unknown override member.")
        pairs = set()
        for link in c.couplings:
            pair = frozenset((link.left, link.right))
            if len(pair) != 2 or pair in pairs or not pair <= c.zones.keys():
                raise AdapterError("Invalid or duplicate thermal coupling.")
            pairs.add(pair)
        if c.solar and self.household.location is None:
            raise AdapterError("Solar requires an explicit location.")
        if (
            any(z.solar_gain_area_m2 for z in c.zones.values())
            and self.household.location is None
        ):
            raise AdapterError("Solar heat gain requires an explicit location.")
        if any(s.contact_id not in self.contacts for s in c.contact_scripts):
            raise AdapterError("Unknown scripted contact.")
        if any(
            not utc(c.start) <= utc(call.at) <= utc(c.end) for call in c.inbound_calls
        ):
            raise AdapterError("Inbound call is outside the simulation horizon.")
        if any(
            not utc(c.start) <= utc(s.requested_at) < utc(s.deadline) <= utc(c.end)
            for s in c.contact_scripts
        ):
            raise AdapterError("Contact script is outside the simulation horizon.")
        for i, device in c.devices.items():
            kind = self.assets[i].kind
            required = {
                "lock": "locked",
                "camera": "camera_armed",
                "light": "on",
                "shade": "cover_position_percent",
            }.get(kind)
            if device.state.available is None or (
                device.state.available
                and required
                and getattr(device.state, required) is None
            ):
                raise AdapterError(
                    "Device initial availability and state must be explicit."
                )
            if device.pending_at is not None:
                if not utc(c.start) <= utc(device.pending_at) <= utc(c.end):
                    raise AdapterError(
                        "Pending device transition is outside the horizon."
                    )
                assert device.pending_state is not None
                self._validate_device(i, device.pending_state, device.pending_at)
            if kind == "lock" and any(
                device.delays.get(k) != 1.5 for k in ("lock", "unlock")
            ):
                raise AdapterError(
                    "Lock transitions require the approved 1.5 second delay."
                )
            if kind == "camera" and device.delays.get("arm") != 0.5:
                raise AdapterError("Camera arm requires the approved 0.5 second delay.")
            self._validate_device(i, device.state, utc(c.start))

    def _validate_thermal(self) -> None:
        for ident, zone in self._state.zones.items():
            conductance = 1 / zone.resistance_f_per_kw + sum(
                link.conductance
                for link in self.config.couplings
                if ident in (link.left, link.right)
            )
            if conductance / zone.thermal_mass_kwh_per_f / 60 > 1:
                raise AdapterError(
                    "Thermal configuration is unstable at a one-minute step."
                )

    def _schedule(self) -> tuple[tuple[datetime, UUID, WeeklyTransition], ...]:
        c = self.config
        tz = self.household.timezone
        events = []
        for member, transitions in c.weekly.items():
            seen = set()
            for t in transitions:
                key = (
                    t.weekday,
                    t.minute,
                    "presence" if t.kind in {"arrive", "leave"} else "sleep",
                )
                if key in seen or t.zone_id is not None and t.zone_id not in c.zones:
                    raise AdapterError("Conflicting schedule or unknown sleep zone.")
                seen.add(key)
                margin = 1 + t.jitter_minutes // 1440
                day = utc(c.start).astimezone(ZoneInfo(tz)).date() - timedelta(
                    days=margin
                )
                end = utc(c.end).astimezone(ZoneInfo(tz)).date() + timedelta(
                    days=margin
                )
                while day <= end:
                    if day.weekday() == t.weekday:
                        rng = stream(
                            c.seed,
                            self.household.id,
                            "presence",
                            str(member),
                            f"{day}:{t.kind}:{t.minute}",
                        )
                        at = local_instant(day, t.minute, tz) + timedelta(
                            minutes=rng.randint(-t.jitter_minutes, t.jitter_minutes)
                        )
                        if utc(c.start) <= at <= utc(c.end):
                            events.append((at, member, t))
                    day += timedelta(days=1)
        events.sort(key=lambda e: (e[0], str(e[1]), e[2].kind))
        occupied = set()
        for at, member, t in events:
            event_key = (
                at,
                member,
                "presence" if t.kind in {"arrive", "leave"} else "sleep",
            )
            if event_key in occupied:
                raise AdapterError("Jitter produced conflicting scheduled transitions.")
            occupied.add(event_key)
        return tuple(events)

    def _check_at(self, at: datetime) -> datetime:
        at = utc(at)
        if not self._last_read <= at <= utc(self.config.end):
            raise AdapterError("Simulation time is backwards or outside its horizon.")
        return at

    def check_range(self, start: datetime, end: datetime) -> None:
        validate_range(start, end)
        if utc(start) < utc(self.config.start) or utc(end) > utc(self.config.end):
            raise AdapterError("Requested range is outside the simulation horizon.")

    def _events(self, state: State, at: datetime) -> State:
        people, recovery, devices = (
            dict(state.presence),
            dict(state.recovery),
            dict(state.devices),
        )
        events = list(state.events)
        local = at.astimezone(ZoneInfo(self.household.timezone))
        if at > utc(self.config.start) and at == local_instant(
            local.date(), 0, self.household.timezone
        ):
            recovery = {
                m: r.next_day(local.date(), self.config.seed, self.household.id, m)
                for m, r in recovery.items()
            }
        for when, member, transition in self._scheduled:
            if when == at:
                people[member] = presence_change(people[member], transition)
                events.append((at, f"presence.{transition.kind}", member))
        for override in self.config.overrides:
            if utc(override.at) == at:
                if override.presence is not None:
                    people[override.member_id] = override.presence
                else:
                    recovery[override.member_id] = changed(
                        recovery[override.member_id], score=override.recovery_score
                    )
                events.append((at, "override", override.member_id))
        for ident, device in devices.items():
            after = device.advance(at)
            if after != device:
                events.append(
                    (
                        at,
                        "device.failed"
                        if after.failed > device.failed
                        else "device.changed",
                        ident,
                    )
                )
                devices[ident] = after
        return changed(
            state,
            presence=people,
            recovery=recovery,
            devices=devices,
            events=tuple(events),
        )

    def _boundary(self) -> datetime:
        # ponytail: scan small timelines; index event times if long replays become slow.
        start = utc(self.config.start)
        minute = timedelta(minutes=1)
        candidates = [
            start + ((self._at - start) // minute + 1) * minute,
            utc(self.config.end),
        ]
        candidates += [
            utc(s.at) for s in self.config.weather.samples if utc(s.at) > self._at
        ]
        candidates += [t for t, _, _ in self._scheduled if t > self._at]
        candidates += [utc(o.at) for o in self.config.overrides if utc(o.at) > self._at]
        candidates += [
            utc(d.pending_at)
            for d in self._state.devices.values()
            if d.pending_at is not None and utc(d.pending_at) > self._at
        ]
        candidates += [
            self._at + timedelta(seconds=a.cycle_minutes * 60 - a.elapsed_seconds)
            for a in self._state.appliances.values()
            if a.running
        ]
        storage: tuple[EV | Battery, ...] = (
            *self._state.evs.values(),
            *self._state.batteries.values(),
        )
        for model in storage:
            seconds = model.seconds_to_limit()
            if seconds is not None:
                candidates.append(self._at + timedelta(seconds=seconds))
        tomorrow = self._at.astimezone(
            ZoneInfo(self.household.timezone)
        ).date() + timedelta(days=1)
        candidates.append(local_instant(tomorrow, 0, self.household.timezone))
        return min(t for t in candidates if t > self._at)

    def solar_power(self, ident: UUID, at: datetime) -> float:
        location = self.household.location
        if location is None or ident not in self.solar:
            raise AdapterError("Solar subject or location unavailable.")
        model = self.solar[ident]
        return model.kw_peak * model.irradiance(
            at,
            location.latitude,
            location.longitude,
            self.config.weather.at(at).cloud_cover_percent,
        )

    def _step(self, state: State, start: datetime, end: datetime) -> State:
        seconds = (end - start).total_seconds()
        if seconds == 0:
            return state
        weather = self.config.weather.at(start)
        evs = {i: m.advance(seconds) for i, m in state.evs.items()}
        batteries = {i: m.advance(seconds) for i, m in state.batteries.items()}
        appliances = {i: m.advance(seconds) for i, m in state.appliances.items()}
        coupling = dict.fromkeys(state.zones, 0.0)
        for link in self.config.couplings:
            flow = (
                state.zones[link.right].temp_f - state.zones[link.left].temp_f
            ) * link.conductance
            coupling[link.left] += flow
            coupling[link.right] -= flow
        # Horizontal irradiance supplies zone solar gain; PV has its own orientation.
        irradiance = 0.0
        if any(z.solar_gain_area_m2 for z in state.zones.values()):
            location = self.household.location
            if location is None:
                raise AdapterError("Solar heat gain requires an explicit location.")
            irradiance = Solar(tilt_degrees=0, orientation_degrees=0).irradiance(
                start,
                location.latitude,
                location.longitude,
                weather.cloud_cover_percent,
            )
        zones = {
            i: z.advance(
                seconds,
                weather.temp_f,
                occupants=sum(
                    p.present and p.zone_id == i for p in state.presence.values()
                ),
                irradiance_kw_m2=irradiance,
                coupling_kw=coupling[i],
            )
            for i, z in state.zones.items()
        }
        load = (
            self.config.base_load_kw * seconds / 3600
            + sum(e.grid_kwh - state.evs[i].grid_kwh for i, e in evs.items())
            + sum(
                a.energy_kwh - state.appliances[i].energy_kwh
                for i, a in appliances.items()
            )
            + sum(
                z.electricity_kwh - state.zones[i].electricity_kwh
                for i, z in zones.items()
            )
        )
        pv = sum(self.solar_power(i, start) for i in self.solar) * seconds / 3600
        battery_in = sum(
            b.input_kwh - state.batteries[i].input_kwh for i, b in batteries.items()
        )
        battery_out = sum(
            b.output_kwh - state.batteries[i].output_kwh for i, b in batteries.items()
        )
        net = load + battery_in - battery_out - pv
        events = state.events + tuple(
            (end, "appliance.completed", i)
            for i, a in appliances.items()
            if a.completions > state.appliances[i].completions
        )
        return changed(
            state,
            evs=evs,
            batteries=batteries,
            appliances=appliances,
            zones=zones,
            load_kwh=state.load_kwh + load,
            pv_kwh=state.pv_kwh + pv,
            import_kwh=state.import_kwh + max(0, net),
            export_kwh=state.export_kwh + max(0, -net),
            events=events,
        )

    def advance_to(self, at: datetime) -> State:
        at = self._check_at(at)
        while self._at < at:
            boundary = self._boundary()
            if boundary > at:
                projected = self._step(self._state, self._at, at)
                self._last_read = at
                return projected
            state = self._events(self._step(self._state, self._at, boundary), boundary)
            self._state, self._at = state, boundary
        self._last_read = at
        return self._state

    def read(self) -> tuple[datetime, State]:
        at = self.clock.now()
        return at, self.advance_to(at)

    def member_event(
        self,
        member: UUID,
        kind: str,
        zone: UUID | None = None,
        score: int | None = None,
    ) -> None:
        """Apply a hypothetical world input, never an adapter action or graph write."""
        if (
            member not in self.members
            or zone is not None
            and zone not in self.config.zones
        ):
            raise AdapterError("Unknown scenario member or zone.")
        at, state = self.read()
        if kind == "sleep" and not state.presence[member].present:
            raise AdapterError("Absent member cannot sleep.")
        if kind == "recovery":
            recovery = dict(state.recovery)
            recovery[member] = changed(recovery[member], score=score)
            state = changed(state, recovery=recovery)
        else:
            transition = WeeklyTransition.model_validate(
                dict(weekday=0, minute=0, kind=kind, zone_id=zone, jitter_minutes=0)
            )
            people = dict(state.presence)
            # Waking a member who is not sleeping may leave presence unchanged.
            people[member] = presence_change(people[member], transition)
            state = changed(state, presence=people)
        self._state, self._at = (
            changed(state, events=state.events + ((at, kind, member),)),
            utc(at),
        )

    def observation(
        self,
        domain: AdapterDomain,
        subject: UUID,
        state: ObservationState,
        at: datetime,
    ) -> Observation:
        values: dict[str, UUID] = {}
        if subject in self.assets:
            values["asset_id"] = subject
        elif subject in self.members:
            values["member_id"] = subject
        elif subject != self.household.id:
            raise AdapterError("Unknown twin observation subject.")
        row = Observation(
            id=uuid5(
                self.household.id,
                f"twin:{utc(self.config.start).isoformat()}:{self.config.seed}:{domain}:{subject}",
            ),
            household_id=self.household.id,
            domain=domain,
            observed_at=at,
            source="twin",
            state=state,
            **values,
        )
        from hirz.graph.models import validate_observation_scope

        validate_observation_scope(
            row,
            self.household.id,
            self.members.keys(),
            {i: a.kind for i, a in self.assets.items()},
            at,
        )
        return row

    def entity(self, entity: str, domain: AdapterDomain) -> UUID:
        matches = [
            i
            for i, b in self.bindings.items()
            if b.entity_id == entity
            and b.adapter == "twin"
            and ASSET_DOMAINS[self.assets[i].kind] == domain
        ]
        if len(matches) != 1:
            raise AdapterError("Unknown or ambiguous twin entity.")
        return matches[0]

    def _validate_device(
        self, ident: UUID, state: ObservationState, at: datetime
    ) -> None:
        self.observation(ASSET_DOMAINS[self.assets[ident].kind], ident, state, at)

    def doorbell_event(
        self, entity: str, at: datetime | None, kind: str, classification: str | None
    ) -> Observation:
        ident = self.entity(entity, "doorbell")
        now, state = self.read()
        # Interactive events sample the running clock once. Scripted events
        # still have to match their explicit simulation instant exactly.
        if at is not None and utc(at) != utc(now):
            raise AdapterError(
                "Twin event must occur at the current simulation instant."
            )
        device = state.devices[ident]
        if kind in {"press", "motion"} and device.state.available is False:
            raise AdapterError("Doorbell is offline.")
        values: dict[str, object] = {}
        if kind == "press":
            values["last_press_at"] = now
        elif kind == "motion":
            values.update(last_motion_at=now, motion_classification=classification)
        elif kind in {"online", "offline"}:
            values["available"] = kind == "online"
        else:
            raise AdapterError("Unknown twin doorbell event.")
        new = ObservationState.model_validate(device.state.model_dump() | values)
        devices = dict(state.devices) | {ident: changed(device, state=new)}
        # A world input is an actual event boundary, unlike a polling read.
        self._state, self._at = (
            changed(
                state,
                devices=devices,
                events=state.events + ((now, f"doorbell.{kind}", ident),),
            ),
            utc(now),
        )
        return self.observation(
            "doorbell",
            ident,
            new if new.available is not False else ObservationState(available=False),
            now,
        )
