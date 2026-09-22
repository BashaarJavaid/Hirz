"""Deterministic, account-attributed intake and read-only household coordination."""

import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from pydantic import AwareDatetime

from hirz import db
from hirz.constitution.conditions import PolicyFacts
from hirz.constitution.evaluator import ApprovalRequirements, resolve
from hirz.constitution.schema import Constitution
from hirz.graph.context import ContextSnapshot
from hirz.graph.models import (
    Asset,
    ConstraintRecord,
    ConstraintSpec,
    GraphError,
    Model,
    Observation,
    utc,
    validate_observation_scope,
)
from hirz.pipeline.hashing import action_hash, digest
from hirz.pipeline.models import (
    Action,
    Decision,
    EventType,
    Plan,
    PlanConstraint,
    Principal,
    Requester,
    Target,
)
from hirz.planner.models import (
    MemberConstraint,
    PlannerInput,
    PlannerResult,
    SolverDiagnostics,
)
from hirz.planner.service import plan
from hirz.risk import CLASSES
from hirz.twin.physics import changed

if TYPE_CHECKING:
    from hirz.pipeline.service import Pipeline


class Clarification(ValueError):
    """A bounded request could not be resolved without asking the member."""


class Intake(Model):
    text: str
    horizon_end: AwareDatetime
    replaces: UUID | None = None
    manual: Observation | None = None


class IntakeResult(Model):
    decision: Decision | None = None
    constraint_id: UUID | None = None
    clarification: str | None = None


class Conflict(Model):
    requirements: tuple[PlanConstraint, ...]
    members: tuple[UUID, ...]
    reason: str
    relaxation: str


class Coordination(Model):
    result: PlannerResult
    conflicts: tuple[Conflict, ...]
    quorum: dict[str, ApprovalRequirements]
    pending: tuple[str, ...] = ()


def clean(row: dict[str, Any]) -> dict[str, Any]:
    return {
        k: v
        for k, v in row.items()
        if k not in {"valid_from", "valid_to", "staleness_seconds"}
    }


def records(snapshot: ContextSnapshot) -> tuple[ConstraintRecord, ...]:
    return tuple(
        ConstraintRecord.model_validate(clean(r)) for r in snapshot.data["constraints"]
    )


def active(record: ConstraintRecord, start: datetime, end: datetime) -> bool:
    return (
        (record.withdrawn_at is None or utc(start) < utc(record.withdrawn_at))
        and utc(record.spec.starts_at) < utc(end)
        and utc(start) < utc(record.spec.ends_at)
    )


def numbers(text: str) -> str:
    ones = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
    words = {word: i for i, word in enumerate(ones)}
    words.update(
        {
            word: 10 * i
            for i, word in enumerate(
                "twenty thirty forty fifty sixty seventy eighty ninety".split(), 2
            )
        }
    )
    pattern = (
        r"\b("
        + "|".join(words)
        + r")(?:[ -](one|two|three|four|five|six|seven|eight|nine))?\b"
    )

    def replace(match: re.Match[str]) -> str:
        first = words[match[1]]
        if match[2] and first < 20:
            return match[0]
        return str(first + (words[match[2]] if match[2] else 0))

    return re.sub(pattern, replace, text)


def time_at(text: str, at: datetime, end: datetime, timezone: str) -> datetime:
    if re.match(r"^\d{4}-\d{2}-\d{2}[ t]", text):
        try:
            explicit = datetime.fromisoformat(text)
            instant = utc(explicit)
            local = instant.astimezone(ZoneInfo(timezone))
            if explicit.utcoffset() != local.utcoffset() or not utc(
                at
            ) <= instant <= utc(end):
                raise ValueError
            return instant
        except ValueError:
            raise Clarification(
                "Please give a date and UTC offset valid in the household timezone and planning horizon."
            ) from None
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text.strip())
    if not match or (not match[3] and match[2] is None):
        raise Clarification("Please specify AM or PM, or a 24-hour time such as 23:00.")
    hour, minute = int(match[1]), int(match[2] or 0)
    if minute > 59 or hour > (12 if match[3] else 23) or (match[3] and hour == 0):
        raise Clarification("Please give a valid local time.")
    if match[3]:
        hour = hour % 12 + (12 if match[3] == "pm" else 0)
    zone = ZoneInfo(timezone)
    local = utc(at).astimezone(zone)
    possibilities = set()
    for day in range(3):
        wall = (local + timedelta(days=day)).replace(
            hour=hour, minute=minute, second=0, microsecond=0, tzinfo=None
        )
        instants = set()
        for fold in (0, 1):
            candidate = utc(wall.replace(tzinfo=zone, fold=fold))
            if candidate.astimezone(zone).replace(tzinfo=None) == wall:
                instants.add(candidate)
        relevant = {t for t in instants if utc(at) <= t <= utc(end)}
        if relevant and len(instants) != 1:
            raise Clarification(
                "That local time occurs twice; please clarify the date and UTC offset."
            )
        possibilities.update(relevant)
    if len(possibilities) != 1:
        raise Clarification(
            "Please clarify the date and time within this planning horizon; the local time may not exist."
        )
    return possibilities.pop()


def asset_named(snapshot: ContextSnapshot, name: str, kind: str) -> UUID:
    aliases = {"ev": {"car", "ev"}, "appliance": {"kitchen", "dishwasher"}}
    assets = [r for r in snapshot.data["assets"] if r["kind"] == kind]
    matches = [r for r in assets if str(r["name"]).casefold() == name]
    if not matches and name in aliases.get(kind, set()):
        identities = {
            r["asset_id"]
            for r in snapshot.data["asset_bindings"]
            if r["entity_id"] == "dishwasher"
        }
        matches = (
            assets
            if kind == "ev"
            else [
                r
                for r in assets
                if r["id"] in identities or str(r["name"]).casefold() == "dishwasher"
            ]
        )
    if len(matches) != 1:
        raise Clarification("Please name one household device or room exactly.")
    return UUID(str(matches[0]["id"]))


def parse(
    text: str, snapshot: ContextSnapshot, end: datetime
) -> tuple[ConstraintSpec | None, str | None, bool, UUID | None]:
    at = utc(snapshot.as_of)
    if utc(end) <= at or utc(end) - at > timedelta(hours=25):
        raise Clarification(
            "Please supply the current planning horizon, at most 25 hours."
        )
    sentence = text.strip().rstrip(".").casefold().replace("’", "'")
    claimed = None
    attribution = re.fullmatch(r"(.+?) says[,:]? (.+)", sentence)
    if attribution:
        names = [
            str(r["display_name"])
            for r in snapshot.data["members"]
            if str(r["display_name"]).casefold() == attribution[1]
        ]
        if len(names) != 1:
            raise Clarification("Please clarify the claimed household member's name.")
        claimed, sentence = names[0], attribution[2]
    revision = sentence.startswith("change ")
    if revision:
        sentence = sentence[7:]
    release = re.fullmatch(r"release (?:the )?(.+?) (?:manual )?hold", sentence)
    if release:
        return None, claimed, False, asset_named(snapshot, release[1], "hvac_zone")
    sentence = numbers(sentence).replace("until i'm done in the kitchen at ", "until ")
    timezone = str(snapshot.data["households"][0]["timezone"])
    # Optional explicit duration; otherwise the request expires with this horizon.
    ending = re.fullmatch(r"(.+) until (\d{1,2}(?::\d{2})?\s*(?:am|pm)?)", sentence)
    if ending and (sentence.startswith("keep ") or sentence.startswith("prefer ")):
        end = time_at(ending[2], at, end, timezone)
        sentence = ending[1]
    data: dict[str, Any] = {"starts_at": at, "ends_at": utc(end)}
    match = re.fullmatch(
        r"(?:charge |set )?(?:the )?(.+?) (?:target )?to (\d{1,2})(?:%| percent)?(?: by (.+))?",
        sentence,
    )
    if match:
        data.update(
            kind="ev_target",
            asset_id=asset_named(snapshot, match[1], "ev"),
            value=int(match[2]) / 100,
        )
        if match[3]:
            # A target with a deadline is encoded as one requirement; the deadline
            # is its end, so it cannot silently outlive the request's window.
            data["ends_at"] = time_at(match[3], at, end, timezone)
    else:
        match = re.fullmatch(
            r"(?:don't|do not) charge (?:the )?(.+?) (?:past|above) (\d{1,2})(?:%| percent)?",
            sentence,
        )
        if match:
            data.update(
                kind="ev_ceiling",
                asset_id=asset_named(snapshot, match[1], "ev"),
                value=int(match[2]) / 100,
            )
        else:
            match = re.fullmatch(
                r"(?:don't|do not) (charge|run|start) (?:the )?(.+?) (?:before|until) (.+)",
                sentence,
            )
            kitchen = re.fullmatch(
                r"(?:the )?kitchen (?:is )?(?:busy|in use) until (.+)", sentence
            )
            if kitchen:
                data.update(
                    kind="appliance_not_before",
                    asset_id=asset_named(snapshot, "kitchen", "appliance"),
                    at=time_at(kitchen[1], at, end, timezone),
                )
            elif match:
                ev = match[1] == "charge"
                data.update(
                    kind="ev_not_before" if ev else "appliance_not_before",
                    asset_id=asset_named(
                        snapshot, match[2], "ev" if ev else "appliance"
                    ),
                    at=time_at(match[3], at, end, timezone),
                )
            else:
                match = re.fullmatch(
                    r"(?:the )?(.+?) (?:must be ready|deadline) (?:by|at) (.+)",
                    sentence,
                )
                if match:
                    ev = match[1] in {"car", "ev"} or any(
                        r["kind"] == "ev" and str(r["name"]).casefold() == match[1]
                        for r in snapshot.data["assets"]
                    )
                    data.update(
                        kind="ev_deadline" if ev else "appliance_deadline",
                        asset_id=asset_named(
                            snapshot, match[1], "ev" if ev else "appliance"
                        ),
                        at=time_at(match[2], at, end, timezone),
                    )
                else:
                    match = re.fullmatch(
                        r"(prefer|keep) (?:the )?(.+?) (?:at |between )?(\d{1,2})(?: and (\d{1,2}))? (?:f|fahrenheit|degrees fahrenheit)",
                        sentence,
                    )
                    if not match or (match[1] == "keep") != (match[4] is not None):
                        raise Clarification(
                            "Please specify a car target or limit, a start/deadline, a Fahrenheit preference or band, or a hold release."
                        )
                    data.update(
                        kind="temperature_band" if match[4] else "temperature",
                        asset_id=asset_named(snapshot, match[2], "hvac_zone"),
                        value=float(match[3]),
                        upper=float(match[4]) if match[4] else None,
                    )
    try:
        return ConstraintSpec.model_validate(data), claimed, revision, None
    except ValueError:
        raise Clarification(
            "Please use a supported EV target (0–80%) or an ordered, positive request window."
        ) from None


async def prepare(
    pipeline: "Pipeline", action: Action, at: datetime, principal: Principal
) -> tuple[
    ConstraintSpec | None, str | None, tuple[ConstraintRecord, ...], Observation | None
]:
    if action.scheduled_for is not None:
        raise Clarification(
            "Constraint intake is immediate; scheduled intake is not supported."
        )
    intake = Intake.model_validate(action.params)
    snapshot = await pipeline.snapshot(at)
    member = action.requested_by
    if member.member_id is None or member.role == "unknown":
        raise Clarification("A linked household account is required.")
    prior = records(snapshot)
    observation = intake.manual
    if observation is not None and (
        intake.replaces is not None
        or action.action_class != "governance.record_constraint"
    ):
        raise Clarification(
            "A manual event renews its device hold; do not combine it with another mutation."
        )
    release = None
    if (
        observation is None
        and action.action_class == "governance.withdraw_constraint"
        and intake.replaces is not None
    ):
        spec, claimed, revision = None, None, False
    elif observation is None:
        spec, claimed, revision, release = parse(
            intake.text, snapshot, intake.horizon_end
        )
    else:
        validate_observation_scope(
            observation,
            pipeline.household_id,
            {UUID(str(r["id"])) for r in snapshot.data["members"]},
            {
                UUID(str(r["id"])): Asset.model_validate(clean(r)).kind
                for r in snapshot.data["assets"]
            },
            at,
        )
        if (
            observation.source != "twin"
            or observation.domain != "devices"
            or observation.observed_at != at
            or observation.asset_id is None
            or observation.state.target_f is None
            or observation.state.mode is None
        ):
            raise Clarification(
                "An explicit current twin thermostat event with target and mode is required."
            )
        if not any(
            str(r["id"]) == str(observation.asset_id) and r["kind"] == "hvac_zone"
            for r in snapshot.data["assets"]
        ):
            raise Clarification("Manual holds require a thermostat.")
        spec = ConstraintSpec(
            kind="manual_hold",
            asset_id=observation.asset_id,
            starts_at=at,
            ends_at=at + timedelta(hours=2),
            value=observation.state.target_f,
            mode=observation.state.mode,
        )
        claimed, revision = None, False
    selected = []
    if release is not None or observation is not None:
        asset = release if release is not None else spec.asset_id if spec else None
        selected = [
            r
            for r in prior
            if r.asset_id == asset
            and r.spec.kind == "manual_hold"
            and active(r, at, at + timedelta(microseconds=1))
        ]
        if release is not None and len(selected) != 1:
            raise Clarification("There is no unique active hold to release.")
    elif intake.replaces is not None:
        selected = [
            r for r in prior if r.id == intake.replaces and r.withdrawn_at is None
        ]
        if len(selected) != 1:
            raise Clarification(
                "The constraint to replace or withdraw was not found in this household."
            )
    elif revision and spec:
        selected = [
            r
            for r in prior
            if str(r.member_id) == member.member_id
            and r.spec.kind == spec.kind
            and r.asset_id == spec.asset_id
            and active(r, at, intake.horizon_end)
        ]
        if len(selected) != 1:
            raise Clarification(
                "Please identify the single constraint you want to change."
            )
    for record in selected:
        if (
            record.spec.kind != "manual_hold"
            and str(record.member_id) != member.member_id
            and (
                member.role != "owner" or principal.claimed_role not in {None, "owner"}
            )
        ):
            raise Clarification(
                "Only the request's linked member or a household owner may withdraw it."
            )
    if action.action_class == "governance.withdraw_constraint":
        if not selected:
            raise Clarification("Please identify the constraint to withdraw.")
        spec = None
    elif release is not None:
        raise Clarification("Hold release requires the withdrawal operation.")
    return spec, claimed, tuple(selected), observation


async def commit_constraint(
    pipeline: "Pipeline",
    action: Action,
    decision: Decision,
    at: datetime,
    principal: Principal,
) -> None:
    """Called only inside Pipeline's grant transaction; any failure rolls it all back."""
    spec, claimed, previous, observation = await prepare(
        pipeline, action, at, principal
    )
    assert decision.audit_id is not None and action.requested_by.member_id is not None
    intake = Intake.model_validate(action.params)
    for record in previous:
        seq = await pipeline.audit.append(
            pipeline.connection,
            pipeline.household_id,
            at,
            EventType.CONSTRAINT_WITHDRAWN,
            {
                "constraint_id": str(record.id),
                "action_id": action.action_id,
                "decision_seq": decision.audit_id,
                "member_id": action.requested_by.member_id,
            },
        )
        current = await pipeline.repo.get("constraints", {"id": record.id})
        assert current is not None
        await pipeline.repo.put(
            "constraints",
            changed(
                record,
                withdrawn_at=at,
                withdrawn_seq=seq,
                withdrawal_decision_seq=decision.audit_id,
            ),
            expected_version=current["valid_from"],
        )
    if spec is not None:
        provenance = PlanConstraint(
            member_id=UUID(action.requested_by.member_id),
            source="manual:device"
            if observation
            else "member:" + action.requested_by.member_id,
            surface=action.requested_by.surface,
            claimed_author=claimed,
            recorded_at=at,
            text=intake.text,
            encoded=spec.model_dump(mode="json"),
        )
        constraint_id = uuid5(pipeline.household_id, action.action_id)
        seq = await pipeline.audit.append(
            pipeline.connection,
            pipeline.household_id,
            at,
            EventType.CONSTRAINT_RECORDED,
            {
                "constraint_id": str(constraint_id),
                "action_id": action.action_id,
                "decision_seq": decision.audit_id,
                "member_id": action.requested_by.member_id,
                "provenance": provenance.model_dump(mode="json"),
            },
        )
        await pipeline.repo.put(
            "constraints",
            ConstraintRecord(
                household_id=pipeline.household_id,
                id=constraint_id,
                member_id=UUID(action.requested_by.member_id),
                asset_id=spec.asset_id,
                provenance=provenance,
                action_id=action.action_id,
                decision_seq=decision.audit_id,
                recorded_seq=seq,
                replaces=previous[0].id if len(previous) == 1 else None,
            ),
        )
        if observation:
            current = await pipeline.repo.get("observations", {"id": observation.id})
            await pipeline.repo.put(
                "observations",
                observation,
                expected_version=current["valid_from"] if current else None,
            )


class Coordinator:
    def __init__(self, pipeline: "Pipeline"):
        self.pipeline = pipeline

    async def intake(
        self,
        principal: Principal,
        *,
        action_id: str,
        text: str,
        horizon_end: datetime,
        replaces: UUID | None = None,
        manual: Observation | None = None,
        withdraw: bool = False,
    ) -> IntakeResult:
        p = self.pipeline
        request = Intake(
            text=text, horizon_end=horizon_end, replaces=replaces, manual=manual
        )
        withdraw = withdraw or bool(
            re.fullmatch(r"release .+ hold\.?", text.strip(), re.IGNORECASE)
        )
        action = Action.model_validate(
            dict(
                action_id=action_id,
                **{
                    "class": "governance.withdraw_constraint"
                    if withdraw
                    else "governance.record_constraint"
                },
                target=Target(adapter="household", entity=str(p.household_id)),
                params=request.model_dump(mode="json"),
                requested_by=Requester(
                    member_id=None, role="unknown", surface=principal.surface
                ),
                reason="Member constraint intake",
                content_hash="",
            )
        )
        action = action.model_copy(update={"content_hash": action_hash(action)})
        try:
            async with p.repo.write(p.clock):
                # Re-deliver identical raw input without reinterpreting relative times.
                existing = await p.connection.scalar(
                    sa.select(db.actions.c.grant_seq).where(
                        p.scope(db.actions), db.actions.c.action_id == action_id
                    )
                )
                if existing is None:
                    await prepare(
                        p,
                        action.model_copy(
                            update={"requested_by": await p.requester(principal)}
                        ),
                        utc(p.clock()),
                        principal,
                    )
        except Clarification as exc:
            return IntakeResult(clarification=str(exc))
        decision = await p.redeem(action, principal)
        return IntakeResult(
            decision=decision,
            constraint_id=uuid5(p.household_id, action_id)
            if decision.decision == "execute" and not withdraw
            else None,
        )

    async def plan(
        self,
        principal: Principal,
        inputs: PlannerInput,
        *,
        previous: Plan | None = None,
    ) -> Coordination:
        pipeline = self.pipeline
        if inputs.household_id != pipeline.household_id:
            raise GraphError("Planner input belongs to another household")
        async with pipeline.repo.write(pipeline.clock):
            snapshot = await pipeline.snapshot(utc(pipeline.clock()))
            requester = await pipeline.requester(principal)
        result = coordinate(
            changed(inputs, requester=requester),
            snapshot,
            pipeline.bundle.policy(),
            previous=previous,
        )
        if principal.claimed_role is not None and result.result.plan is not None:
            for action in result.result.actions:
                lowered = action.model_copy(
                    update={
                        "requested_by": requester.model_copy(
                            update={"role": principal.claimed_role}
                        )
                    }
                )
                outcome = resolve(
                    pipeline.bundle.policy(),
                    lowered,
                    PolicyFacts(pipeline.bundle.policy().household, snapshot.as_of, {}),
                )
                if outcome.effective_mode == "never":
                    raise GraphError(
                        "Claimed role cannot authorize this planning workload"
                    )
        return result


def comfort_rank(
    record: ConstraintRecord, snapshot: ContextSnapshot
) -> tuple[int, float]:
    spec = record.spec
    threshold = CLASSES["energy.hvac_adjust"]["freshness_seconds"]
    for row in snapshot.data["observations"]:
        observation = Observation.model_validate(clean(row))
        age = (utc(snapshot.as_of) - utc(observation.observed_at)).total_seconds()
        if (
            observation.domain == "presence"
            and observation.member_id == record.member_id
            and observation.state.available is not False
            and observation.state.present is True
            and observation.state.zone_id == record.asset_id
            and 0 <= age <= threshold
        ):
            return 0, 0
    arrivals = [
        utc(datetime.fromisoformat(str(r["expected_at"])))
        for r in snapshot.data["schedule_events"]
        if r.get("member_id") == str(record.member_id)
        and r.get("zone_id") == str(record.asset_id)
        and r["kind"] == "arrival"
        and r.get("expected_at") is not None
    ]
    arrivals = [
        t
        for t in arrivals
        if max(utc(spec.starts_at), utc(snapshot.as_of)) <= t < utc(spec.ends_at)
    ]
    return (1, min(arrivals).timestamp()) if arrivals else (2, 0)


def split_slots(
    p: PlannerInput, constraints: tuple[ConstraintRecord, ...]
) -> PlannerInput:
    edges = {
        utc(t)
        for c in constraints
        for t in (c.spec.starts_at, c.spec.ends_at, c.spec.at, c.withdrawn_at)
        if t is not None
    }
    slots, indices = [], []
    for i, slot in enumerate(p.slots):
        boundaries = sorted(
            {utc(slot.start), utc(slot.end)}
            | {t for t in edges if utc(slot.start) < t < utc(slot.end)}
        )
        for left, right in zip(boundaries, boundaries[1:]):
            slots.append(changed(slot, start=left, end=right))
            indices.append(i)
    zones = tuple(
        changed(
            z,
            **{
                name: tuple(getattr(z, name)[i] for i in indices)
                for name in ("lower", "upper", "targets", "occupants")
            },
        )
        for z in p.zones
    )
    return changed(p, slots=tuple(slots), zones=zones)


def coordinate(
    p: PlannerInput,
    snapshot: ContextSnapshot,
    policy: Constitution,
    *,
    previous: Plan | None = None,
    _probe: bool = True,
) -> Coordination:
    """A proposal and per-class approval requirements; never grants execution."""
    if (
        snapshot.household_id != p.household_id
        or snapshot.stale
        or snapshot.scope != "all"
        or utc(snapshot.as_of) != utc(p.slots[0].start)
    ):
        raise GraphError("Coordination requires the current household snapshot")
    members = {str(r["id"]): r for r in snapshot.data["members"]}
    if (
        p.requester.member_id not in members
        or members[p.requester.member_id]["role"] != p.requester.role
    ):
        raise GraphError("Planner requester must match household membership")
    if previous is not None and previous.household_id != p.household_id:
        raise GraphError("Previous plan belongs to another household")
    selected = tuple(
        r for r in records(snapshot) if active(r, p.slots[0].start, p.slots[-1].end)
    )
    original = p
    p = split_slots(p, selected)
    conflicts: list[Conflict] = []
    quorum: dict[str, ApprovalRequirements] = {}
    pending = set()

    def conflict(
        rows: tuple[ConstraintRecord, ...], reason: str, relaxation: str
    ) -> None:
        conflicts.append(
            Conflict(
                requirements=tuple(r.provenance for r in rows),
                members=tuple(dict.fromkeys(r.member_id for r in rows)),
                reason=reason,
                relaxation=relaxation,
            )
        )

    bindings = {
        UUID(str(r["asset_id"])): str(r["entity_id"])
        for r in snapshot.data["asset_bindings"]
        if r["adapter"] == "twin"
    }
    for record in selected:
        if (
            record.provenance.recorded_at > snapshot.as_of
            or record.household_id != p.household_id
            or str(record.member_id) not in members
        ):
            raise GraphError("Invalid constraint provenance")
        kind = record.spec.kind
        entity = bindings.get(record.asset_id)
        if (
            entity is None
            or (kind.startswith("ev_") and (entity != "ev" or p.ev is None))
            or (
                kind.startswith("appliance_")
                and (entity != "dishwasher" or p.appliance is None)
            )
            or (
                kind in {"manual_hold", "temperature", "temperature_band"}
                and entity not in {z.entity for z in p.zones}
            )
        ):
            conflict(
                (record,),
                "The request's device is absent from this planning workload.",
                "Include that device in the workload or explicitly withdraw this request.",
            )
    ev_rows = tuple(r for r in selected if r.spec.kind == "ev_target")
    targets = {r.spec.value for r in ev_rows}
    if len(targets) > 1:
        conflict(
            ev_rows,
            "Exact EV targets disagree.",
            f"Explicitly revise or withdraw '{ev_rows[-1].provenance.text}' to match the other target.",
        )
    target = next(iter(targets)) if len(targets) == 1 else p.ev_target
    assert target is not None
    ev_deadline = min(
        [
            p.ev_deadline,
            p.slots[-1].end,
            *(r.spec.ends_at for r in ev_rows),
            *(
                r.spec.at
                for r in selected
                if r.spec.kind == "ev_deadline" and r.spec.at is not None
            ),
        ]
    )
    appliance_deadline = min(
        [
            p.appliance_deadline,
            *(
                r.spec.at
                for r in selected
                if r.spec.kind == "appliance_deadline" and r.spec.at is not None
            ),
        ]
    )
    mapped = tuple(
        MemberConstraint(
            provenance=r.provenance,
            kind=r.spec.kind,
            starts_at=r.spec.starts_at,
            ends_at=r.spec.ends_at,
            at=min(r.spec.at, r.spec.ends_at)
            if r.spec.at is not None and r.spec.kind.endswith("not_before")
            else r.spec.at,
            value=r.spec.value if r.spec.kind in {"ev_target", "ev_ceiling"} else None,
        )
        for r in selected
    )
    p = p.model_copy(
        update=dict(
            constraints=(*p.constraints, *mapped),
            ev_target=target,
            ev_deadline=ev_deadline,
            appliance_deadline=appliance_deadline,
        )
    )
    from hirz.planner.heuristic import appliance_windows
    from hirz.planner.replay import effective

    _, ev_start, _ = effective(p)
    if p.ev:
        if target < p.ev.soc:
            conflict(
                ev_rows,
                "The requested target is below the car's existing charge.",
                f"Raise the target to at least {p.ev.soc:.1%}; Hirz cannot discharge the car.",
            )
        possible = sum(
            p.ev.charger_kw * s.hours * p.ev.efficiency / p.ev.capacity_kwh
            for s in p.slots
            if s.start >= ev_start and s.end <= ev_deadline
        )
        if p.ev.soc + possible + 1e-9 < target:
            conflict(
                tuple(r for r in selected if r.spec.kind.startswith("ev_")),
                "The EV deadline is unreachable at the installed charging power.",
                f"Extend the {ev_deadline.isoformat()} deadline or explicitly lower the {target:.0%} target; no requirement was dropped.",
            )
        for r in selected:
            spec = r.spec
            if (
                spec.kind == "ev_ceiling"
                and spec.value is not None
                and (
                    p.ev.soc > spec.value
                    or (
                        spec.starts_at <= ev_deadline <= spec.ends_at
                        and target > spec.value
                    )
                )
            ):
                conflict(
                    (*ev_rows, r),
                    "The EV ceiling conflicts with the required charge.",
                    f"Raise the ceiling to {max(target, p.ev.soc):.0%}, or explicitly revise the target; a ceiling does not lower it.",
                )
    if p.appliance and not appliance_windows(p):
        conflict(
            tuple(r for r in selected if r.spec.kind.startswith("appliance_")),
            "No complete dishwasher cycle fits its allowed window.",
            f"Extend the deadline to allow a {p.appliance.cycle_minutes:g}-minute cycle after the requested start.",
        )
    zones = []
    for zone in p.zones:
        related = tuple(r for r in selected if bindings.get(r.asset_id) == zone.entity)
        lower, upper, preferences, held_targets, held_modes = (
            list(zone.lower),
            list(zone.upper),
            [],
            [],
            [],
        )
        for i, slot in enumerate(p.slots):
            rows = tuple(r for r in related if active(r, slot.start, slot.end))
            bands = tuple(r for r in rows if r.spec.kind == "temperature_band")
            lower[i] = max(
                [
                    lower[i],
                    *(float(r.spec.value) for r in bands if r.spec.value is not None),
                ]
            )
            upper[i] = min(
                [
                    upper[i],
                    *(float(r.spec.upper) for r in bands if r.spec.upper is not None),
                ]
            )
            if lower[i] > upper[i]:
                conflict(
                    bands,
                    "Hard temperature bands do not overlap.",
                    "Widen or withdraw the most recent hard band for this room.",
                )
            soft = tuple(r for r in rows if r.spec.kind == "temperature")
            ranked = (
                tuple(
                    r
                    for r in soft
                    if comfort_rank(r, snapshot)
                    == min(comfort_rank(c, snapshot) for c in soft)
                )
                if soft
                else ()
            )
            values = {r.spec.value for r in ranked}
            if len(values) > 1:
                conflict(
                    ranked,
                    "Equally ranked comfort preferences disagree.",
                    f"Explicitly revise or withdraw '{ranked[-1].provenance.text}' for this window.",
                )
            preferences.append(next(iter(values)) if len(values) == 1 else None)
            holds = tuple(r for r in rows if r.spec.kind == "manual_hold")
            if len(holds) > 1:
                conflict(
                    holds,
                    "Multiple active thermostat holds overlap.",
                    "Release one hold explicitly.",
                )
            held_targets.append(holds[0].spec.value if holds else None)
            held_modes.append(holds[0].spec.mode if holds else None)
        zones.append(
            changed(
                zone,
                asset_id=next(
                    (
                        ident
                        for ident, entity in bindings.items()
                        if entity == zone.entity
                    ),
                    None,
                ),
                lower=tuple(lower),
                upper=tuple(upper),
                targets=tuple(
                    min(
                        upper[i],
                        max(
                            lower[i],
                            float(preferences[i] or 0)
                            if preferences[i] is not None
                            else t,
                        ),
                    )
                    for i, t in enumerate(zone.targets)
                ),
                preferences=tuple(preferences),
                held_targets=tuple(held_targets),
                held_modes=tuple(held_modes),
            )
        )
    p = p.model_copy(update={"zones": tuple(zones)})
    # Resolve the existing policy's known class/bound restrictions, retaining
    # unresolved conditions for the execution-time pipeline instead of inventing facts.
    checks: list[tuple[str, str, dict[str, Any], tuple[ConstraintRecord, ...]]] = []
    if p.ev:
        checks.append(
            (
                "energy.ev_charge",
                "ev",
                {"ev_soc_floor": target},
                tuple(r for r in selected if r.spec.kind.startswith("ev_")),
            )
        )
    if p.appliance:
        checks.append(
            (
                "energy.appliance_start",
                "dishwasher",
                {},
                tuple(r for r in selected if r.spec.kind.startswith("appliance_")),
            )
        )
    if p.battery:
        checks.append(("energy.battery_dispatch", "home_battery", {}, ()))
    for zone in p.zones:
        rows = tuple(r for r in selected if bindings.get(r.asset_id) == zone.entity)
        values = {t for t in (*zone.targets, *zone.held_targets) if t is not None}
        for value in values:
            checks.append(
                ("energy.hvac_adjust", zone.entity, {"target_f": value}, rows)
            )
    for name, entity, params, rows in checks:
        action = Action.model_validate(
            dict(
                action_id="coordinator-preview",
                **{"class": name},
                target=Target(adapter="twin", entity=entity),
                params=params,
                requested_by=p.requester,
                reason="Known policy precheck",
                content_hash="",
            )
        )
        outcome = resolve(
            policy, action, PolicyFacts(policy.household, snapshot.as_of, {})
        )
        quorum[name] = outcome.approval
        if outcome.effective_mode == "never" and any(
            d.code != "POLICY_ERROR" for d in outcome.diagnostics
        ):
            conflict(
                rows,
                f"The constitution prohibits {name} or its requested bounds.",
                "Withdraw or revise the request to stay within the household's written rule.",
            )
        if outcome.diagnostics or not outcome.conditions_met:
            pending.add(
                name
                + ": current conditions must be evaluated by the execution pipeline"
            )
    if conflicts:
        result = PlannerResult(
            plan=None,
            schedule=None,
            replay=None,
            diagnostics=SolverDiagnostics(
                status="infeasible", elapsed_seconds=0, message="Coordinator precheck"
            ),
            unresolved_conflict=True,
            previous_feasible_reference=previous,
            reference_label="Previous feasible proposal only; no execution authority or new savings claim"
            if previous
            else None,
            input_hash=digest(p.model_dump(mode="json")),
            provenance=p.provenance,
        )
    else:
        result = plan(p, previous=previous, probe_constraints=False)
        if result.plan is not None:
            for action in result.actions:
                outcome = resolve(
                    policy,
                    action,
                    PolicyFacts(
                        policy.household, action.scheduled_for or snapshot.as_of, {}
                    ),
                    hard_only=True,
                )
                if outcome.effective_mode == "never" and any(
                    d.code != "POLICY_ERROR" for d in outcome.diagnostics
                ):
                    conflict(
                        tuple(
                            r
                            for r in selected
                            if bindings.get(r.asset_id) == action.target.entity
                        ),
                        "A proposed device setting exceeds a known constitution restriction.",
                        "Revise the requested workload to fit the household's written bounds.",
                    )
            if conflicts:
                result = result.model_copy(
                    update=dict(
                        plan=None,
                        actions=(),
                        schedule=None,
                        replay=None,
                        baselines={},
                        diagnostics=result.diagnostics.model_copy(
                            update={
                                "status": "infeasible",
                                "message": "Known policy restriction",
                            }
                        ),
                        previous_feasible_reference=previous,
                        reference_label="Previous feasible proposal only; no execution authority or new savings claim"
                        if previous
                        else None,
                    )
                )
        if (
            result.plan is None
            and result.diagnostics.status == "infeasible"
            and not conflicts
        ):
            if _probe:
                for record in sorted(
                    selected, key=lambda r: r.provenance.recorded_at, reverse=True
                ):
                    reduced = changed(
                        snapshot,
                        data=snapshot.data
                        | {
                            "constraints": [
                                r
                                for r in snapshot.data["constraints"]
                                if str(r["id"]) != str(record.id)
                            ]
                        },
                    )
                    candidate = coordinate(original, reduced, policy, _probe=False)
                    if candidate.result.plan is not None:
                        conflict(
                            (record,),
                            "The remaining physical requirements are infeasible together.",
                            f"Explicitly withdraw or relax '{record.provenance.text}' and request a new plan.",
                        )
            if not conflicts:
                conflict(
                    selected,
                    "The physical workload is infeasible; no single member request was proven to resolve it.",
                    "Extend the planning window or revise a hard comfort or energy requirement explicitly.",
                )
    # Deduplicate repeated slot evidence, keeping every independently owned request.
    unique = {c.model_dump_json(): c for c in conflicts}
    return Coordination(
        result=result,
        conflicts=tuple(unique.values()),
        quorum=quorum,
        pending=tuple(sorted(pending)),
    )
