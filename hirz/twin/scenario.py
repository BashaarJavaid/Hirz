"""Offline scenario inputs and reports. No persistence, authority or tool execution."""

import asyncio
import math
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Any, Literal, Self, cast
from uuid import UUID
from zoneinfo import ZoneInfo

import yaml
from pydantic import AwareDatetime, Field, StrictInt, model_validator

from hirz.adapters.doorbell.twin import TwinDoorbell, TwinDoorbellEvent
from hirz.adapters.energy.twin import TwinEnergy
from hirz.adapters.presence.twin import TwinPresence
from hirz.adapters.wearable.twin import TwinWearable
from hirz.constitution.boundary import Dogwood
from hirz.constitution.compiler import compile_policy
from hirz.constitution.preview import preview
from hirz.constitution.schema import Constitution, ConstitutionLoader, loads
from hirz.graph.context import ChannelSummary
from hirz.graph.models import (
    ASSET_DOMAINS,
    AdapterDomain,
    Asset,
    AssetBinding,
    Household,
    Member,
    MemberAccount,
    Model,
    Observation,
    ObservationState,
    ScheduleEvent,
    TrustedContact,
    utc,
)
from hirz.graph.seeds import UniqueLoader, read_seed
from hirz.twin.adapters import TwinAdapter, registry
from hirz.twin.clock import SimClock
from hirz.twin.people import ContactScript, InboundCall, local_instant
from hirz.twin.physics import changed
from hirz.twin.world import TwinConfig, TwinWorld

TOOLS = frozenset(
    {
        "what_can_you_do",
        "get_household_context",
        "get_household_plan",
        "revise_household_plan",
        "explain_plan",
        "approve_action",
        "execute_household_action",
        "assess_request_risk",
        "verify_trusted_identity",
        "get_action_audit",
        "propose_household_rule",
        "evaluate_permission",
    }
)
WORLD_EVENTS = {
    "presence.arrive": ({"member"}, {"zone", "note"}),
    "presence.leave": ({"member"}, set()),
    "presence.sleep": ({"member", "zone"}, set()),
    "presence.wake": ({"member"}, set()),
    "wearable.recovery": ({"member", "score"}, set()),
    "doorbell.press": ({"entity"}, {"expected_visitor"}),
    "doorbell.motion": ({"entity", "classification"}, set()),
    "call.inbound": ({"presented_number", "claim"}, set()),
    "contact.checkin_reply": ({"contact", "reply", "requested_at", "deadline"}, set()),
    "voice": ({"member", "text", "script"}, set()),
    "constitution.activate": ({"member", "patch"}, set()),
}
FUTURE_EVENTS = frozenset(
    {
        "app.approve",
        "app.deny",
        "calendar.add",
        "calendar.remove",
        "tariff.spike",
        "tariff.update",
        "weather.update",
        "ev.drive",
        "ev.plug",
        "ev.unplug",
        "device.fail",
        "device.manual_change",
        "link.replay",
        "link.tamper",
        "link.readdress",
        "link.offline",
        "clock.jump",
    }
)
Text = Annotated[str, Field(min_length=1)]


class Clock(Model):
    start: AwareDatetime
    end: AwareDatetime
    speed: float = Field(gt=0, allow_inf_nan=False)


class Event(Model):
    at: Text
    event: Text
    member: str | None = None
    zone: str | None = None
    note: str | None = None
    entity: str | None = None
    expected_visitor: str | None = None
    classification: Literal["human", "animal", "vehicle"] | None = None
    score: Annotated[StrictInt, Field(ge=0, le=100)] | None = None
    presented_number: str | None = None
    claim: str | None = None
    contact: str | None = None
    reply: Literal["genuine", "not_genuine", "will_call", "no_answer"] | None = None
    requested_at: str | None = None
    deadline: str | None = None
    text: str | None = None
    script: tuple[str, ...] = ()
    patch: str | None = None
    deferred: Text | None = None
    payload: dict[str, Any] | None = None

    @model_validator(mode="after")
    def shape(self) -> Self:
        supplied = self.model_fields_set - {"at", "event"}
        if self.event in WORLD_EVENTS:
            required, optional = WORLD_EVENTS[self.event]
            if not required <= supplied or supplied - required - optional:
                raise ValueError("Incorrect scenario event fields.")
            nullable = {"presented_number"}
            if any(getattr(self, key) is None for key in required - nullable):
                raise ValueError("Missing scenario event value.")
            if self.event == "voice" and (
                not self.script or not set(self.script) <= TOOLS
            ):
                raise ValueError("Voice requires an explicit known tool script.")
        elif self.event in FUTURE_EVENTS:
            if not self.deferred or supplied - {"deferred", "member", "payload"}:
                raise ValueError("Future events require an explicit deferral.")
        else:
            raise ValueError("Unknown scenario event.")
        return self


class Check(Model):
    at: Text
    kind: Literal["observation", "policy", "contact", "call"]
    subject: str | None = None
    domain: AdapterDomain | None = None
    equals: dict[str, Any] = Field(min_length=1)


class DeferredCheck(Model):
    expectation: Text
    reason: Text


class Assertions(Model):
    checks: tuple[Check, ...]
    deferred: tuple[DeferredCheck, ...]


class Scenario(Model):
    id: Text
    seed: StrictInt
    household: Text
    clock: Clock
    rate_plan: Literal["twin"]
    adapters: dict[AdapterDomain, Literal["twin"]] = Field(min_length=1)
    initial: dict[str, Any]
    timeline: tuple[Event, ...]
    assertions: Assertions = Field(alias="assert")


class Patch(Model):
    base_version: StrictInt
    version: StrictInt
    autonomy: dict[str, dict[str, dict[str, Any]]] = Field(min_length=1)


def instant(value: str, start: datetime, timezone: str) -> datetime:
    match = re.fullmatch(r"(?:\+(\d+)d )?([01]\d|2[0-3]):([0-5]\d)", value)
    if match is None:
        raise ValueError("Scenario time must be HH:MM or +Nd HH:MM.")
    day, hour, minute = (int(part or 0) for part in match.groups())
    date = start.astimezone(ZoneInfo(timezone)).date() + timedelta(days=day)
    return local_instant(date, hour * 60 + minute, timezone)


class LoadedScenario:
    def __init__(self, path: Path):
        raw = path.read_bytes()
        self.spec = spec = Scenario.model_validate(yaml.load(raw, Loader=UniqueLoader))
        seed_path = path.parent / spec.household
        seed = read_seed(seed_path)
        self.hashes = {
            "scenario": sha256(raw).hexdigest(),
            "household": sha256(seed_path.read_bytes()).hexdigest(),
        }
        self.policy = loads(seed.yaml)
        rows = seed.models(spec.clock.start)
        household = changed(cast(Household, rows["households"][0]), rate_plan="twin")
        self.references: dict[str, dict[str, UUID]] = {}
        for kind in ("members", "assets", "trusted_contacts"):
            self.references[kind] = {
                raw["id"]: cast(UUID, getattr(model, "id"))
                for raw, model in zip(seed.graph.get(kind, []), rows[kind], strict=True)
            }
        self.accounts = {
            str(cast(MemberAccount, row).member_id) for row in rows["member_accounts"]
        }
        self.timezone = household.timezone
        self.times = tuple(self.time(event.at) for event in spec.timeline)
        if list(self.times) != sorted(self.times):
            raise ValueError("Scenario timeline must be nondecreasing.")
        self.check_times = tuple(
            self.time(check.at) for check in spec.assertions.checks
        )
        if not spec.assertions.checks:
            raise ValueError("Scenario requires active observation-stage checks.")
        initial = dict(spec.initial)
        if {"start", "end", "seed"} & initial.keys():
            raise ValueError("Initial state must use the scenario clock and seed.")
        for key in (
            "evs",
            "batteries",
            "zones",
            "solar",
            "appliances",
            "devices",
            "presence",
            "weekly",
            "recovery",
        ):
            kind = "members" if key in {"presence", "weekly", "recovery"} else "assets"
            if not isinstance(initial.get(key), dict):
                raise ValueError("Initial model groups must be explicit mappings.")
            initial[key] = {
                self.ref(kind, slug): value for slug, value in initial[key].items()
            }
        for value in initial["presence"].values():
            if not isinstance(value, dict):
                raise ValueError("Presence state must be a mapping.")
            if value.get("zone_id") is not None:
                value["zone_id"] = self.ref("assets", value["zone_id"])
        for transitions in initial["weekly"].values():
            if not isinstance(transitions, list):
                raise ValueError("Weekly schedules must be explicit lists.")
            for transition in transitions:
                if not isinstance(transition, dict):
                    raise ValueError("Weekly transition must be a mapping.")
                if transition.get("zone_id") is not None:
                    transition["zone_id"] = self.ref("assets", transition["zone_id"])
        if not isinstance(initial.get("couplings"), list):
            raise ValueError("Couplings must be an explicit list.")
        for link in initial["couplings"]:
            if not isinstance(link, dict):
                raise ValueError("Coupling must be a mapping.")
            for key in ("left", "right"):
                link[key] = self.ref("assets", link[key])
        # Timeline is the sole author of these private world inputs.
        if any(
            initial.get(key) != []
            for key in ("overrides", "contact_scripts", "inbound_calls")
        ):
            raise ValueError(
                "Supply overrides, calls and contact replies in the timeline."
            )
        calls, contacts = [], []
        self.patches: dict[int, Patch] = {}
        for index, event in enumerate(spec.timeline):
            if event.member is not None:
                member = self.ref("members", event.member)
                if (
                    event.event
                    in {"voice", "constitution.activate", "app.approve", "app.deny"}
                    and str(member) not in self.accounts
                ):
                    raise ValueError("Scripted member has no linked demo account.")
            if event.zone is not None:
                self.ref("assets", event.zone)
            if event.expected_visitor is not None:
                self.ref("members", event.expected_visitor)
            if event.event == "call.inbound":
                calls.append(
                    InboundCall(
                        at=self.times[index],
                        presented_number=event.presented_number,
                        summary=cast(str, event.claim),
                    )
                )
            if event.event == "contact.checkin_reply":
                contacts.append(
                    ContactScript(
                        contact_id=self.ref("trusted_contacts", event.contact),
                        requested_at=self.time(cast(str, event.requested_at)),
                        deadline=self.time(cast(str, event.deadline)),
                        reply_at=None
                        if event.reply == "no_answer"
                        else self.times[index],
                        reply=cast(Any, event.reply),
                    )
                )
            if event.patch is not None:
                patch_raw = (path.parent / event.patch).read_bytes()
                self.hashes[f"patch:{index}"] = sha256(patch_raw).hexdigest()
                self.patches[index] = Patch.model_validate(
                    yaml.load(patch_raw, Loader=ConstitutionLoader)
                )
        if len({c.contact_id for c in contacts}) != len(contacts):
            raise ValueError("Only one explicit check-in per contact is supported.")
        config = TwinConfig.model_validate(
            initial
            | {
                "start": spec.clock.start,
                "end": spec.clock.end,
                "seed": spec.seed,
                "inbound_calls": calls,
                "contact_scripts": contacts,
            }
        )
        self.world = TwinWorld(
            household,
            members=tuple(cast(Member, m) for m in rows["members"]),
            assets=tuple(cast(Asset, a) for a in rows["assets"]),
            bindings=tuple(cast(AssetBinding, b) for b in rows["asset_bindings"]),
            contacts=tuple(cast(TrustedContact, c) for c in rows["trusted_contacts"]),
            channels=tuple(
                ChannelSummary.model_validate(c.model_dump(exclude={"value_hash"}))
                for c in rows["contact_channels"]
            ),
            calendar=tuple(cast(ScheduleEvent, s) for s in rows["schedule_events"]),
            config=config,
            clock=SimClock(spec.clock.start, 0),
        )
        self.registry = registry(
            self.world, ",".join(f"{domain}:twin" for domain in spec.adapters)
        )
        for event in spec.timeline:
            domain = {"call": "contacts", "contact": "contacts"}.get(
                event.event.split(".")[0], event.event.split(".")[0]
            )
            if (
                event.event in WORLD_EVENTS
                and domain in {"presence", "wearable", "doorbell", "contacts"}
                and domain not in spec.adapters
            ):
                raise ValueError("Scenario event requires an explicit adapter domain.")
            if (
                event.event == "contact.checkin_reply"
                and event.reply == "no_answer"
                and self.time(event.at) != self.time(cast(str, event.deadline))
            ):
                raise ValueError("No-answer event must occur at its deadline.")
            if event.entity is not None:
                self.world.entity(event.entity, "doorbell")
            if (
                event.zone is not None
                and self.ref("assets", event.zone) not in config.zones
            ):
                raise ValueError("Scenario zone must identify a thermal zone.")
        for check in spec.assertions.checks:
            self.validate_check(check)

    def time(self, value: str) -> datetime:
        at = instant(value, self.spec.clock.start, self.timezone)
        if not utc(self.spec.clock.start) <= at <= utc(self.spec.clock.end):
            raise ValueError("Scenario time is outside the horizon.")
        return at

    def ref(self, kind: str, slug: str | None) -> UUID:
        if slug not in self.references[kind]:
            raise ValueError("Unknown scenario subject in this household.")
        return self.references[kind][slug]

    def validate_check(self, check: Check) -> None:
        fields = set(check.equals)
        if check.kind == "observation":
            if check.domain not in self.spec.adapters:
                raise ValueError("Assertion domain is unavailable.")
            if check.subject == "household":
                if check.domain != "energy":
                    raise ValueError("Household observations require energy domain.")
            else:
                kind = (
                    "members" if check.domain in {"presence", "wearable"} else "assets"
                )
                ident = self.ref(kind, check.subject)
                if (
                    kind == "assets"
                    and ASSET_DOMAINS[self.world.assets[ident].kind] != check.domain
                ):
                    raise ValueError("Assertion subject/domain mismatch.")
            if not fields <= ObservationState.model_fields.keys():
                raise ValueError("Unknown observation assertion field.")
            values = dict(check.equals)
            if values.get("zone_id") is not None:
                values["zone_id"] = self.ref("assets", values["zone_id"])
            ObservationState.model_validate(values)
        elif check.kind == "policy":
            if (
                check.subject is not None
                or check.domain is not None
                or fields != {"version"}
                or type(check.equals["version"]) is not int
            ):
                raise ValueError("Policy assertions require only a version.")
        elif check.kind == "contact":
            ident = self.ref("trusted_contacts", check.subject)
            if (
                check.domain is not None
                or fields != {"status"}
                or check.equals["status"]
                not in {"pending", "genuine", "not_genuine", "will_call", "no_answer"}
            ):
                raise ValueError("Invalid contact model assertion.")
            if not any(
                s.contact_id == ident for s in self.world.config.contact_scripts
            ):
                raise ValueError("Missing contact model script.")
        elif (
            check.subject is not None
            or check.domain is not None
            or fields != {"count"}
            or type(check.equals["count"]) is not int
            or check.equals["count"] < 0
        ):
            raise ValueError("Call assertions require a nonnegative count.")

    async def observations(self) -> tuple[Observation, ...]:
        reg, world = self.registry, self.world
        readings = []
        for ident, asset in world.assets.items():
            domain = ASSET_DOMAINS[asset.kind]
            if domain in self.spec.adapters:
                adapter = cast(TwinAdapter, reg.resolve(domain, asset_id=ident))
                readings.append(adapter.asset_state(world.bindings[ident].entity_id))
        if "energy" in self.spec.adapters:
            readings.append(
                await cast(TwinEnergy, reg.resolve("energy")).get_tariff_state()
            )
        if "presence" in self.spec.adapters:
            readings.extend(
                await cast(TwinPresence, reg.resolve("presence")).who_is_home()
            )
        if "wearable" in self.spec.adapters:
            wearable = cast(TwinWearable, reg.resolve("wearable"))
            for member in world.members:
                readings.append(await wearable.get_recovery(member))
        return tuple(
            reg.stamp(
                cast(AdapterDomain, row.domain), "twin", row, at=world.clock.now()
            )
            for row in readings
        )

    def check(self, check: Check, readings: tuple[Observation, ...]) -> bool:
        expected = dict(check.equals)
        actual: dict[str, Any]
        if check.kind == "policy":
            actual = {"version": self.policy.version}
        elif check.kind == "call":
            actual = {
                "count": sum(
                    utc(c.at) <= self.world.clock.now()
                    for c in self.world.config.inbound_calls
                )
            }
        elif check.kind == "contact":
            script = next(
                s
                for s in self.world.config.contact_scripts
                if s.contact_id == self.ref("trusted_contacts", check.subject)
            )
            actual = {"status": script.status(self.world.clock.now())}
        else:
            if check.subject == "household":
                ident = self.world.household.id
            else:
                kind = (
                    "members" if check.domain in {"presence", "wearable"} else "assets"
                )
                ident = self.ref(kind, check.subject)
            row = next(
                (
                    r
                    for r in readings
                    if r.domain == check.domain
                    and ident
                    in (
                        r.asset_id,
                        r.member_id,
                        r.household_id
                        if check.subject == "household"
                        and r.asset_id is None
                        and r.member_id is None
                        else None,
                    )
                ),
                None,
            )
            if row is None or row.source != "twin":
                return False
            actual = row.state.model_dump(mode="json")
            if expected.get("zone_id") is not None:
                expected["zone_id"] = str(self.ref("assets", expected["zone_id"]))
            expected = ObservationState.model_validate(expected).model_dump(
                mode="json", exclude_unset=True
            )
        return all(actual.get(key) == value for key, value in expected.items())

    async def apply(
        self, index: int, proposals: set[UUID], dogwood: Dogwood
    ) -> dict[str, Any]:
        event = self.spec.timeline[index]
        world = self.world
        result: dict[str, Any] = {
            "index": index,
            "at": self.times[index].isoformat(),
            "event": event.event,
            "status": "simulated",
        }
        member = self.ref("members", event.member) if event.member is not None else None
        if member is not None:
            result.update(
                linked_member=str(member),
                surface="alexa"
                if event.event == "voice"
                else "app"
                if event.event in {"constitution.activate", "app.approve", "app.deny"}
                else "scenario",
            )
        if event.event in FUTURE_EVENTS:
            result.update(status="deferred", reason=event.deferred)
        elif event.event == "voice":
            result.update(
                status="deferred",
                tools=[
                    {
                        "name": name,
                        "status": "deferred",
                        "reason": "Tool execution awaits later phases.",
                    }
                    for name in event.script
                ],
            )
            if "propose_household_rule" in event.script:
                proposals.add(cast(UUID, member))
        elif event.event == "constitution.activate":
            if member not in proposals or world.members[member].role != "owner":
                raise ValueError(
                    "Simulated activation requires the linked owner's preceding proposal."
                )
            patch = self.patches[index]
            if (
                patch.base_version != self.policy.version
                or patch.version != patch.base_version + 1
            ):
                raise ValueError("Recorded patch version mismatch.")
            data = self.policy.model_dump(by_alias=True)
            for domain, rules in patch.autonomy.items():
                if not rules:
                    raise ValueError("Recorded patch must replace complete rules.")
                data["autonomy"].setdefault(domain, {}).update(rules)
            data["version"] = patch.version
            candidate = Constitution.model_validate(data)
            await dogwood.validate(compile_policy(candidate, "hirz-local"))
            result.update(
                recorded=True,
                preview=preview(self.policy, candidate),
                engine="dogwood-local",
                authenticated=False,
            )
            self.policy = candidate
            proposals.remove(member)
        elif event.event.startswith("presence.") or event.event == "wearable.recovery":
            world.member_event(
                cast(UUID, member),
                event.event.split(".")[1],
                self.ref("assets", event.zone) if event.zone else None,
                event.score,
            )
        elif event.event.startswith("doorbell."):
            adapter = cast(TwinDoorbell, self.registry.resolve("doorbell"))
            payload = TwinDoorbellEvent(
                kind=cast(Any, event.event.split(".")[1]),
                entity_id=cast(str, event.entity),
                at=world.clock.now(),
                classification=event.classification,
            )
            await adapter.on_event(payload.model_dump_json().encode(), {})
        # Calls/contact replies are private, time-indexed model data, not observations.
        return result


async def run_scenario(
    loaded: LoadedScenario,
    *,
    headless: bool = False,
    assertions: bool = False,
    speed: float | None = None,
    to: str | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    progress: Callable[[str], None] | None = None,
    dogwood: Dogwood | None = None,
) -> dict[str, Any]:
    spec, world = loaded.spec, loaded.world
    pace = spec.clock.speed if speed is None else speed
    if not math.isfinite(pace) or pace <= 0:
        raise ValueError("Scenario speed must be positive and finite.")
    stop = loaded.time(to) if to is not None else utc(spec.clock.end)
    report: dict[str, Any] = {
        "scenario": spec.id,
        "seed": spec.seed,
        "source": "twin",
        "input_hashes": loaded.hashes,
        "adapters": spec.adapters,
        "start": utc(spec.clock.start).isoformat(),
        "end": stop.isoformat(),
        "events": [],
        "snapshots": [],
        "checks": [],
        "deferred": [check.model_dump() for check in spec.assertions.deferred],
        "limitations": [
            "No tool execution, device actions, authentication or audit.",
            "No persistence; prices and weather are synthetic.",
        ],
    }
    proposals: set[UUID] = set()
    times = sorted(
        {
            utc(spec.clock.start),
            stop,
            *[t for t in loaded.times if t <= stop],
            *[t for t in loaded.check_times if t <= stop],
        }
    )
    await loaded.registry.start()
    try:
        # ponytail: scan the small demo timelines; index events/checks by time
        # if long scenario corpora make this quadratic traversal measurable.
        for at in times:
            if not headless and to is None:
                remaining = (at - world.clock.now()).total_seconds() / pace
                while remaining > 0:
                    delay = min(remaining, 30)
                    await sleep(delay)
                    remaining -= delay
            world.clock.jump(at)
            world.read()
            if to is None or at < stop:
                for index, when in enumerate(loaded.times):
                    if when == at:
                        try:
                            event_result = await loaded.apply(
                                index, proposals, dogwood or Dogwood()
                            )
                        except (ValueError, OSError):
                            report["events"].append(
                                {
                                    "index": index,
                                    "at": at.isoformat(),
                                    "event": spec.timeline[index].event,
                                    "status": "failed",
                                }
                            )
                            raise
                        report["events"].append(event_result)
                        if progress:
                            progress(
                                f"{at.isoformat()} {event_result['event']}: {event_result['status']}"
                            )
            readings = await loaded.observations()
            report["snapshots"].append(
                {
                    "at": at.isoformat(),
                    "policy_version": loaded.policy.version,
                    "observations": [row.model_dump(mode="json") for row in readings],
                }
            )
            for index, when in enumerate(loaded.check_times):
                if when == at and (to is None or at < stop):
                    status = (
                        "unchecked"
                        if not assertions
                        else "passed"
                        if loaded.check(spec.assertions.checks[index], readings)
                        else "failed"
                    )
                    report["checks"].append(
                        {
                            "index": index,
                            "kind": spec.assertions.checks[index].kind,
                            "at": at.isoformat(),
                            "status": status,
                        }
                    )
        reached = {check["index"] for check in report["checks"]}
        report["checks"].extend(
            {
                "index": i,
                "kind": check.kind,
                "at": loaded.check_times[i].isoformat(),
                "status": "not_reached",
            }
            for i, check in enumerate(spec.assertions.checks)
            if i not in reached
        )
        report["status"] = (
            "failed"
            if any(c["status"] == "failed" for c in report["checks"])
            else "stopped"
            if to is not None
            else "item16_observations_passed"
            if assertions
            else "completed_unchecked"
        )
    except (ValueError, OSError):
        report.update(
            status="failed",
            error="Scenario execution failed; input and upstream details withheld.",
        )
    finally:
        await loaded.registry.close()
    return report
