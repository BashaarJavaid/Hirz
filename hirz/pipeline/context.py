"""Select policy and risk facts from one fresh, complete household snapshot."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from hirz.constitution.conditions import PolicyFacts, parse
from hirz.constitution.schema import Constitution
from hirz.graph.context import ContextSnapshot
from hirz.graph.models import (
    ASSET_DOMAINS,
    Observation,
    observation_subject,
    validate_observation_scope,
)
from hirz.pipeline.models import Action, SupplementalEvidence
from hirz.risk.engine import RiskFacts

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class ContextError(ValueError):
    pass


class NewerDoorbellPress(ContextError):
    pass


def quiet_hours(policy: Constitution, name: str, at: datetime) -> bool:
    for period in policy.quiet_hours:
        if name not in period.affects and name.split(".")[1] not in period.affects:
            continue
        time = at.strftime("%H:%M")
        crosses = period.from_time > period.to_time
        start = at - timedelta(days=1) if crosses and time < period.to_time else at
        if DAYS[start.weekday()] not in period.days:
            continue
        if (
            period.from_time <= time < period.to_time
            if not crosses
            else time >= period.from_time or time < period.to_time
        ):
            return True
    return False


@dataclass(frozen=True)
class Facts:
    policy: PolicyFacts
    risk: RiskFacts
    paused: bool
    quiet: bool


def extract(
    snapshot: ContextSnapshot,
    policy: Constitution,
    action: Action,
    evidence: tuple[SupplementalEvidence, ...],
    used: Decimal,
    bound_press: dict[str, Any] | None = None,
) -> Facts:
    if snapshot.stale or snapshot.scope != "all":
        raise ContextError("A complete fresh snapshot is required")
    data: Any = snapshot.data
    home = data["households"][0]
    at = snapshot.as_of
    local = at.astimezone(ZoneInfo(home["timezone"]))
    members = {r["id"]: r for r in data["members"]}
    assets = {r["id"]: r for r in data["assets"]}
    zones = tuple(k for k, r in assets.items() if r["kind"] == "hvac_zone")
    if action.target.zone is not None and action.target.zone not in zones:
        raise ContextError("Invalid household zone")
    name = action.action_class
    aggregate = name in {"energy.optimize_cost", "environment.comfort_profile"}
    device = name.startswith(("energy.", "environment.", "security.")) and not aggregate
    target_asset = None
    required: set[str] = set()
    if device:
        bindings = [
            r
            for r in data["asset_bindings"]
            if r["adapter"] == action.target.adapter
            and r["entity_id"] == action.target.entity
        ]
        if len(bindings) != 1 or bindings[0]["asset_id"] not in assets:
            raise ContextError("Invalid or ambiguous household device binding")
        target_asset = bindings[0]["asset_id"]
        required.add(target_asset)
    elif (
        aggregate
        or name.startswith(("governance.", "finance."))
        or name
        in {"health.medical_decisions", "communication.contact_emergency_services"}
    ):
        if (
            action.target.entity != str(snapshot.household_id)
            or action.target.adapter != "household"
        ):
            raise ContextError("Invalid household target")
        if aggregate:
            required.update(assets)
    elif name in {
        "communication.notify_member",
        "health.routine_reminders",
        "health.comfort_preferences",
    }:
        if action.target.adapter != "member" or action.target.entity not in members:
            raise ContextError("Invalid household member target")
    elif name == "communication.contact_trusted_contact":
        if action.target.adapter != "contacts" or action.target.entity not in {
            r["id"] for r in data["trusted_contacts"]
        }:
            raise ContextError("Invalid household contact target")
    else:
        raise ContextError("Unsupported target")
    # Domain streams coexist; never fill missing fields from an older reading.
    streams: dict[tuple[str, str], dict[str, Any]] = {}
    member_ids = {UUID(m) for m in members}
    asset_kinds = {UUID(k): a["kind"] for k, a in assets.items()}
    for raw in data["observations"]:
        row = Observation.model_validate(
            {
                k: v
                for k, v in raw.items()
                if k not in {"valid_from", "valid_to", "staleness_seconds"}
            }
        )
        validate_observation_scope(
            row,
            snapshot.household_id,
            member_ids,
            asset_kinds,
            at,
        )
        if row.domain is None:
            continue
        key = (str(observation_subject(row)), row.domain)
        value = row.model_dump(mode="json", exclude_none=True)
        previous = streams.get(key)
        if previous:
            previous_at = datetime.fromisoformat(previous["observed_at"])
            if previous_at == row.observed_at and (
                previous["state"] != value["state"] or previous["source"] != row.source
            ):
                raise ContextError("Conflicting simultaneous observations")
            if previous_at >= row.observed_at:
                continue
        streams[key] = value
    observations = {
        subject: streams[(subject, domain)]
        for subject, domain in (
            *((k, ASSET_DOMAINS[r["kind"]]) for k, r in assets.items()),
            *((k, "presence") for k in members),
        )
        if (subject, domain) in streams
    }
    scam_pattern = None
    ages: list[float] = []
    for supplied in evidence:
        item = SupplementalEvidence.model_validate(supplied.model_dump())
        if item.household_id != snapshot.household_id or item.observed_at > at:
            raise ContextError("Invalid supplemental scope or time")
        if scam_pattern is not None and scam_pattern != item.scam_pattern:
            raise ContextError("Conflicting supplemental facts")
        scam_pattern = item.scam_pattern
        ages.append((at - item.observed_at).total_seconds())
    occupancy: dict[str, Any] = {}
    people = [observations[m] for m in members if m in observations]
    rows = [
        dict(r["state"], member_id=r["member_id"])
        for r in people
        if r["state"].get("available") is not False
    ]
    complete = len(rows) == len(members) and all(
        type(r.get("present")) is bool for r in rows
    )
    at_home = [r for r in rows if r.get("present") is True]

    def any_known(
        field: str, selected: list[dict[str, Any]], complete_set: bool
    ) -> bool | None:
        if any(r.get(field) is True for r in selected):
            return True
        if complete_set and all(type(r.get(field)) is bool for r in selected):
            return False
        return None

    sleeping = any_known("sleeping", at_home, complete)
    zone_sleeping = None
    if action.target.zone:
        zone_sleeping = any_known(
            "sleeping",
            [r for r in at_home if r.get("zone_id") == action.target.zone],
            complete and all(r.get("zone_id") in zones for r in at_home),
        )
    if sleeping is not None:
        occupancy["sleeping_any"] = sleeping
    if complete:
        occupancy["present_members"] = [r["member_id"] for r in rows if r["present"]]
        occupancy["members"] = rows
    required.update(r["member_id"] for r in people)
    doorbell = None
    context_extra: dict[str, Any] = {}
    arrivals = [r for r in data["schedule_events"] if r["kind"] == "arrival"]
    bells = [k for k, r in assets.items() if r["kind"] == "doorbell"]
    press_binding = None
    if bound_press is not None and (
        name != "security.door_unlock"
        or bells != [bound_press["asset_id"]]
        or type(bound_press["expected"]) is not bool
    ):
        raise ContextError("Invalid bound doorbell press")
    if name == "security.door_unlock" and len(bells) == 1:
        required.add(bells[0])
        bell = observations.get(bells[0], {}).get("state", {})
        doorbell = bell.get("available")
        press_text = bell.get("last_press_at")
        press = datetime.fromisoformat(press_text) if press_text else None
        if bound_press is not None:
            bound_at = datetime.fromisoformat(bound_press["last_press_at"])
            if bound_at > at:
                raise ContextError("Future bound doorbell press")
            if press is not None and press > bound_at:
                raise NewerDoorbellPress("a newer doorbell press")
            press_binding = bound_press
        elif press is not None and 0 <= (at - press).total_seconds() <= 60:
            press_binding = {
                "asset_id": bells[0],
                "last_press_at": press_text,
                "expected": any(
                    datetime.fromisoformat(r["starts_at"])
                    <= press
                    < datetime.fromisoformat(r["ends_at"])
                    for r in arrivals
                ),
            }
        if press_binding is not None:
            context_extra["unexpected_visitor"] = not press_binding["expected"]
    rule = policy.rule(name, action.requested_by.role)
    needs_price = any(
        node.kind == "attr" and node.value == "context.price_band"
        for expression in (*rule.conditions, *(o.when for o in rule.overrides))
        for node in parse(expression).walk()
    )
    if needs_price and (tariff := streams.get((str(snapshot.household_id), "energy"))):
        observations[str(snapshot.household_id)] = tariff
        required.add(str(snapshot.household_id))
        if (
            tariff["state"].get("available") is not False
            and tariff["state"].get("price_band") is not None
        ):
            context_extra["price_band"] = tariff["state"]["price_band"]
    missing = not required <= observations.keys()
    for subject in sorted(required & observations.keys()):
        ages.append(
            (
                at - datetime.fromisoformat(observations[subject]["observed_at"])
            ).total_seconds()
        )
    prefs = [
        r["value"]
        for r in data["preferences"]
        if r["member_id"] == action.requested_by.member_id
        and r["key"] == "temperature_target_f"
    ]
    state = observations.get(target_asset or "", {}).get("state", {})
    policies = [r for r in data["asset_policies"] if r["asset_id"] == target_asset]
    quiet = quiet_hours(policy, name, local)
    values: dict[str, Any] = {
        "context": {
            "hour": local.hour,
            "weekday": DAYS[local.weekday()],
            "time": local.strftime("%H:%M"),
            "is_quiet_hours": quiet,
            **context_extra,
        },
        "occupancy": occupancy,
        "asset": {
            "state": state,
            "policy": policies[0] if len(policies) == 1 else {},
            "room_kind": assets.get(target_asset, {}).get("room_kind"),
        },
        "household": {"budget_used_today": used},
        "schedule": {
            "arrival_windows": arrivals,
            "arrivals": [
                dict(member_id=r["member_id"], expected_at=r["expected_at"])
                for r in data["schedule_events"]
                if r["kind"] == "arrival"
                and r.get("expected_at")
                and r.get("member_id")
            ],
        },
    }
    graph_guest = any_known(
        "present",
        [r for r in rows if members[r["member_id"]]["role"] == "guest"],
        complete,
    )
    values["observations"] = [
        observations[k] for k in sorted(required & observations.keys())
    ]
    if press_binding is not None:
        values["doorbell"] = press_binding
    values["supplemental"] = [e.model_dump(mode="json") for e in evidence]
    risk = RiskFacts(
        observation_ages_seconds=None if missing else tuple(ages),
        sleeping_any=sleeping,
        sleeping_in_target_zone=zone_sleeping,
        target_is_bedroom=(assets[target_asset]["room_kind"] == "bedroom")
        if target_asset and assets[target_asset].get("room_kind") is not None
        else None,
        guest_present=graph_guest,
        doorbell_online=doorbell,
        baseline_target_f=prefs[0] if len(prefs) == 1 else None,
        scam_pattern=scam_pattern,
    )
    return Facts(
        PolicyFacts(policy.household, at, values, tuple(members), zones),
        risk,
        home.get("autonomy_paused", False),
        quiet,
    )
