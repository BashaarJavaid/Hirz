"""Read-only presentation of already-authorized household results."""

from datetime import datetime, timedelta
from typing import Any

import sqlalchemy as sa

from hirz import db
from hirz.executor.contracts import SUPPORTED
from hirz.explainer.core import context, display_name, local_time
from hirz.graph.context import ContextSnapshot
from hirz.mcp.contracts import Result
from hirz.mcp.presentation import (
    Annualized,
    ApprovalCard,
    Counts,
    DoorbellCard,
    PlanCard,
    PlanRow,
    Scorecard,
    VerificationCard,
)
from hirz.pipeline.context import active_doorbell_press
from hirz.pipeline.models import Action, Plan
from hirz.pipeline.service import Pipeline
from hirz.risk import CLASSES


def action_label(action: Action) -> str:
    values: dict[str, Any] = action.params
    match action.action_class:
        case "energy.battery_dispatch":
            return f"Battery: {values.get('dispatch_kw', 0):.2f} kW dispatch"
        case "energy.hvac_adjust":
            return f"Comfort: set temperature to {values['target_f']:.1f}°F"
        case "energy.ev_charge":
            return (
                f"Car: charge up to {float(values.get('charge_limit', 0)) * 100:.0f}%"
                if values.get("charging")
                else "Car: stop charging"
            )
        case "environment.lights":
            return "Turn the light on" if values.get("on") else "Turn the light off"
        case "energy.appliance_start":
            return "Start the appliance"
        case "security.door_unlock":
            return "Request a temporary door unlock"
        case _:
            return "Household request"


def doorbell(snapshot: ContextSnapshot) -> DoorbellCard | None:
    data: dict[str, Any] = snapshot.data
    bells = [a for a in data["assets"] if a["kind"] == "doorbell"]
    locks = [a for a in data["assets"] if a["kind"] == "lock"]
    if snapshot.stale or len(bells) != 1:
        return None
    at = snapshot.as_of
    threshold = CLASSES["security.door_unlock"]["freshness_seconds"]

    def observation(asset: dict[str, Any], domain: str) -> dict[str, Any] | None:
        rows = [
            r
            for r in data["observations"]
            if r.get("asset_id") == asset["id"] and r.get("domain") == domain
        ]
        if not rows:
            return None
        row = max(rows, key=lambda r: r["observed_at"])
        age = (at - datetime.fromisoformat(row["observed_at"])).total_seconds()
        return (
            row
            if 0 <= age <= threshold and row["state"].get("available") is True
            else None
        )

    bell = observation(bells[0], "doorbell")
    if not bell:
        return None
    press_text = bell["state"].get("last_press_at")
    press = datetime.fromisoformat(press_text) if press_text else None
    if not active_doorbell_press(press, at):
        return None
    assert press is not None
    arrivals = [
        r
        for r in data["schedule_events"]
        if r["kind"] == "arrival"
        and datetime.fromisoformat(r["starts_at"])
        <= press
        < datetime.fromisoformat(r["ends_at"])
    ]
    lines = [
        "An arrival is expected now. Hirz does not identify the visitor."
        if arrivals
        else "Nobody is expected right now."
    ]
    names = [
        display_name(str(m["display_name"]))
        for m in data["members"]
        if any(r.get("member_id") == m["id"] for r in arrivals)
    ]
    if arrivals and len(names) == 1 and names[0]:
        lines = [f"{names[0]} is expected now. Hirz does not identify the visitor."]
    motion = bell["state"].get("last_motion_at")
    classification = bell["state"].get("motion_classification")
    if (
        motion
        and classification
        and 0 <= (at - datetime.fromisoformat(motion)).total_seconds() <= threshold
    ):
        lines.insert(
            0,
            f"{classification.capitalize()} motion at {local_time(datetime.fromisoformat(motion), context(snapshot))}.",
        )
    lock = observation(locks[0], "devices") if len(locks) == 1 else None
    locked = lock["state"].get("locked") if lock else None
    valid_until = min(
        press + timedelta(seconds=60),
        datetime.fromisoformat(bell["observed_at"]) + timedelta(seconds=threshold),
    )
    if lock:
        valid_until = min(
            valid_until,
            datetime.fromisoformat(lock["observed_at"]) + timedelta(seconds=threshold),
        )
    return DoorbellCard(
        as_of=at,
        valid_until=valid_until,
        source="live"
        if lock and bell["source"] == lock["source"] == "real"
        else "simulated",
        context=tuple(lines),
        snapshot="twin" if bell["source"] == "twin" else None,
        lock_state="locked"
        if locked is True
        else "unlocked"
        if locked is False
        else "unknown",
        can_request=bool(lock) and isinstance(locked, bool) and len(locks) == 1,
        room=str(locks[0]["name"]) if len(locks) == 1 else None,
    )


async def scorecard(
    p: Pipeline,
    start: datetime,
    end: datetime,
    action_id: str | None,
    annualized: Annualized | None,
) -> tuple[Scorecard, Plan | None]:
    device = db.actions.c.proposal["class"].astext.in_(
        (*SUPPORTED, "security.door_unlock")
    )
    event = db.audit_log.c.event_type
    approved = sa.exists(
        sa.select(db.approvals.c.approval_id).where(
            db.approvals.c.household_id == db.actions.c.household_id,
            db.approvals.c.action_id == db.actions.c.action_id,
            db.approvals.c.status.in_(("approved", "redeemed")),
        )
    )
    categories = {
        "autonomous": sa.and_(
            event == "EXECUTED",
            ~approved,
            db.actions.c.lifecycle["approval_id"].astext.is_(None),
        ),
        "asked": event.startswith("ASK_", autoescape=True),
        "blocked": event.startswith("DENY_", autoescape=True),
        "verified": event == "VERIFIED",
    }
    query = (
        sa.select(
            *(
                sa.func.count(sa.distinct(db.actions.c.action_id))
                .filter(condition)
                .label(name)
                for name, condition in categories.items()
            )
        )
        .select_from(db.audit_log)
        .join(
            db.actions,
            sa.and_(
                db.actions.c.household_id == db.audit_log.c.household_id,
                db.actions.c.action_id == db.audit_log.c.payload["action_id"].astext,
            ),
        )
        .where(p.scope(db.audit_log), device)
    )
    query = (
        query.where(db.actions.c.action_id == action_id)
        if action_id
        else query.where(
            db.audit_log.c.created_at >= start, db.audit_log.c.created_at <= end
        )
    )
    counts = (await p.connection.execute(query)).mappings().one()
    plans = sa.select(db.plans.c.document).where(
        p.scope(db.plans),
        db.plans.c.document["status"].astext.not_in(
            ("superseded", "abandoned", "refreshing")
        ),
    )
    if action_id:
        linked_plan = (
            sa.select(db.actions.c.proposal["plan_id"].astext)
            .where(p.scope(db.actions), db.actions.c.action_id == action_id, device)
            .scalar_subquery()
        )
        plans = plans.where(db.plans.c.plan_id == linked_plan)
    else:
        plans = plans.where(
            db.plans.c.document["horizon"]["start"].astext.cast(
                sa.DateTime(timezone=True)
            )
            < end,
            db.plans.c.document["horizon"]["end"].astext.cast(
                sa.DateTime(timezone=True)
            )
            > start,
        )
    raw = await p.connection.scalar(
        plans.order_by(db.plans.c.accepted_at.desc(), db.plans.c.plan_id).limit(1)
    )
    at = p.clock()
    return Scorecard(
        as_of=at,
        valid_until=at + timedelta(seconds=30),
        counts=Counts.model_validate(dict(counts)),
        annualized=annualized,
        window_start=start,
        window_end=end,
    ), Plan.model_validate(raw) if raw else None


async def decorate(
    p: Pipeline,
    answer: Result,
    snapshot: ContextSnapshot,
    annualized: Annualized | None,
) -> Result:
    data = answer.data
    at = p.clock()
    base: dict[str, Any] = dict(as_of=at, valid_until=at + timedelta(seconds=30))
    if data.context and data.context.scope == "environment":
        return answer.model_copy(
            update={
                "data": data.model_copy(update={"presentation": doorbell(snapshot)})
            }
        )
    if data.presentation is not None:
        return answer
    if data.plan:
        plan = data.plan
        rows = (
            (
                await p.connection.execute(
                    sa.select(db.actions.c.proposal).where(
                        p.scope(db.actions),
                        db.actions.c.action_id.in_(plan.actions),
                        db.actions.c.proposal["plan_id"].astext == plan.plan_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        by_id = {a.action_id: a for a in map(Action.model_validate, rows)}
        actions = tuple(by_id[k] for k in plan.actions if k in by_id)
        priority = ("energy.battery_dispatch", "energy.hvac_adjust", "energy.ev_charge")
        timeline = tuple(
            PlanRow(action_id=a.action_id, label=action_label(a), at=a.scheduled_for)
            for a in actions
        )
        inline_rows = []
        for kind in priority:
            candidates = [a for a in actions if a.action_class == kind]
            if not candidates:
                continue
            selected = next(
                (a for a in candidates if a.params.get("charging") is True),
                candidates[0],
            )
            label = action_label(selected)
            if selected.scheduled_for:
                label += f" · {local_time(selected.scheduled_for, context(snapshot))}"
            inline_rows.append(
                PlanRow(
                    action_id=selected.action_id, label=label, at=selected.scheduled_for
                )
            )
        inline = tuple(inline_rows)
        car = [
            a
            for a in actions
            if a.action_class == "energy.ev_charge" and "charge_limit" in a.params
        ]
        card = PlanCard(
            **base,
            rows=inline,
            timeline=timeline,
            annualized=annualized,
            rate_label="published ComEd rate"
            if snapshot.data["households"][0].get("rate_plan")
            in {"comed_time_of_day", "comed_hourly"}
            else None,
            car_limit=float(str(car[0].params["charge_limit"])) * 100 if car else None,
            can_revise_car=len(
                [a for a in snapshot.data["assets"] if a["kind"] == "ev"]
            )
            == 1,
            can_approve=plan.status in {"proposed", "awaiting_approval"}
            and len(actions) == len(plan.actions)
            and plan.horizon.end > at,
        )
        return answer.model_copy(
            update={
                "data": data.model_copy(
                    update={"presentation": card, "actions": actions}
                )
            }
        )
    if data.case:
        case = data.case
        contacts = [
            c
            for c in snapshot.data["trusted_contacts"]
            if c["id"] == case.subject.contact_id
        ]
        eligible = [
            c
            for c in snapshot.data["contact_channels"]
            if c["contact_id"] == case.subject.contact_id
            and c["kind"] == "hirz_app"
            and c["source"] == "twin"
            and c.get("verified_at")
            and datetime.fromisoformat(str(c["verified_at"])) <= at
        ]
        state = case.verification
        if state:
            base["valid_until"] = state.expires_at
        verification = VerificationCard(
            **base,
            signals=tuple(
                {
                    "financial_or_access_request": "Money or access was requested",
                    "unfamiliar_channel_reported": "An unfamiliar channel was reported",
                    "secrecy": "You were asked to keep this secret",
                    "third_party_recipient": "A third-party recipient was named",
                    "urgency_language": "Pressure to act quickly",
                    "claimed_authority": "A claim of authority",
                }[s.signal]
                for s in case.signals[:3]
            ),
            status=state.status if state else "assessed",
            contact_name=str(contacts[0]["display_name"])
            if len(contacts) == 1
            else None,
            can_check=not state
            and len(contacts) == 1
            and bool(eligible)
            and case.subject.party == "person"
            and data.status == "ok"
            and "app_confirmation"
            in p.bundle.policy().verification.trusted_contact_methods_order,
        )
        return answer.model_copy(
            update={"data": data.model_copy(update={"presentation": verification})}
        )
    decision = data.decision
    if decision and (decision.decision == "ask" or data.status == "phone_required"):
        raw = await p.connection.scalar(
            sa.select(db.actions.c.proposal).where(
                p.scope(db.actions), db.actions.c.action_id == decision.action_id
            )
        )
        if raw:
            action = Action.model_validate(raw)
            security = action.action_class.startswith("security.")
            approval = decision.approval
            if approval:
                base["valid_until"] = min(base["valid_until"], approval.expires_at)
            approval_plan = None
            if action.plan_id:
                document = await p.connection.scalar(
                    sa.select(db.plans.c.document).where(
                        p.scope(db.plans), db.plans.c.plan_id == action.plan_id
                    )
                )
                approval_plan = Plan.model_validate(document) if document else None
            card_approval = ApprovalCard(
                **base,
                label=action_label(action),
                rule=f"Household rule, version {decision.constitution.version}: {decision.constitution.mode}",
                risk_band=decision.risk.band if decision.risk else "Unavailable",
                phone_required=security,
                can_respond=not security
                and approval is not None
                and approval.expires_at > at,
                plan_id=action.plan_id,
                version=approval_plan.version if approval_plan else None,
            )
            return answer.model_copy(
                update={
                    "data": data.model_copy(
                        update={"presentation": card_approval, "action": action}
                    )
                }
            )
    return answer
