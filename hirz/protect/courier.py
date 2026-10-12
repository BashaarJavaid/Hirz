"""Durable, independently authorized courier warnings. Never identifies a visitor."""

from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

import sqlalchemy as sa

from hirz import db
from hirz.companion.auth import account
from hirz.contacts.checkins import delivery_allowed, selected
from hirz.contacts.service import contact_time, grant
from hirz.graph.context import ContextSnapshot
from hirz.pipeline.context import active_doorbell_press
from hirz.pipeline.hashing import action_hash
from hirz.pipeline.models import (
    Action,
    CourierDelivery,
    CourierState,
    EventType,
    Principal,
    Requester,
    Target,
    VerificationCase,
)
from hirz.pipeline.service import Pipeline

MEMBER = (
    "An unexpected doorbell press followed your reported request. "
    "Don’t hand anything over. Hirz cannot identify the visitor."
)
CONTACT = (
    "{member} reported a suspicious request. An unexpected doorbell press followed "
    "at their home. Please check on them. Hirz cannot identify the visitor."
)
SIMULATED = "Simulated doorbell event."


def trigger(
    case: VerificationCase,
    created_at: datetime,
    snapshot: ContextSnapshot,
    at: datetime,
) -> dict[str, Any] | None:
    if case.courier or case.risk_band.value != "critical":
        return None
    bells = {a["id"] for a in snapshot.data["assets"] if a["kind"] == "doorbell"}
    for raw in snapshot.data["observations"]:
        row: dict[str, Any] = dict(raw)
        state = row["state"]
        if row["domain"] != "doorbell" or row["asset_id"] not in bells:
            continue
        observed = datetime.fromisoformat(row["observed_at"])
        press = (
            datetime.fromisoformat(state["last_press_at"])
            if state.get("last_press_at")
            else None
        )
        if (
            not state.get("available")
            or not active_doorbell_press(observed, at)
            or not active_doorbell_press(press, at)
            or press is None
            or press > observed
            or not created_at <= press <= created_at + timedelta(hours=1)
        ):
            continue
        if any(
            r["kind"] == "arrival"
            and datetime.fromisoformat(str(r["starts_at"]))
            <= press
            < datetime.fromisoformat(str(r["ends_at"]))
            for r in snapshot.data["schedule_events"]
        ):
            continue
        return row
    return None


async def save(
    p: Pipeline, principal: Principal, case_id: str, state: CourierState
) -> None:
    decision = await grant(p, principal, "process", case_id)
    # Replace only courier state; extraction and check-in results remain independent.
    await p.connection.execute(
        db.verification_cases.update()
        .where(p.scope(db.verification_cases), db.verification_cases.c.id == case_id)
        .values(
            document=sa.func.jsonb_set(
                db.verification_cases.c.document,
                sa.cast(["courier"], sa.ARRAY(sa.Text)),
                sa.cast(state.model_dump(mode="json"), sa.dialects.postgresql.JSONB),
            ),
            decision_seq=decision.audit_id,
        )
    )


async def channel(
    p: Pipeline, case: VerificationCase, snapshot: ContextSnapshot
) -> tuple[str | None, str | None]:
    contact = case.subject.contact_id
    if case.subject.party != "person" or not contact:
        return None, None
    real = await selected(p, contact, "app")
    if real:
        return str(real["id"]), "real"
    history = await p.connection.scalar(
        sa.select(db.contact_links.c.id)
        .where(
            p.scope(db.contact_links), db.contact_links.c.contact_id == UUID(contact)
        )
        .limit(1)
    )
    if (
        history
        or "app_confirmation"
        not in p.bundle.policy().verification.trusted_contact_methods_order
    ):
        return None, None
    fixture = next(
        (
            c
            for c in snapshot.data["contact_channels"]
            if c["contact_id"] == contact
            and c["kind"] == "hirz_app"
            and c["source"] == "twin"
            and c.get("verified_at")
            and datetime.fromisoformat(str(c["verified_at"])) <= p.clock()
        ),
        None,
    )
    return (str(fixture["id"]), "twin") if fixture else (None, None)


def action_for(
    p: Pipeline,
    case_id: str,
    state: CourierState,
    recipient: Literal["member", "contact"],
) -> Action:
    outcome = getattr(state, recipient)
    action = Action.model_validate(
        dict(
            action_id=outcome.action_id or uuid4().hex,
            action_class="communication.notify_member"
            if recipient == "member"
            else "communication.contact_trusted_contact",
            target=Target(
                adapter="member" if recipient == "member" else "contacts",
                entity=state.member_id
                if recipient == "member"
                else str(state.contact_id),
            ),
            params={
                "operation": "courier",
                "household_id": str(p.household_id),
                "case_id": case_id,
                "member_id": state.member_id,
                "press_at": state.press_at.isoformat(),
                "asset_id": state.asset_id,
                "channel": state.channel_id if recipient == "contact" else None,
            },
            requested_by=Requester(member_id=None, role="unknown", surface="scheduler"),
            reason="Warn about an unexpected doorbell press after a reported request",
            content_hash="",
        )
    )
    return action.model_copy(update={"content_hash": action_hash(action)})


async def bound_channel(
    p: Pipeline, state: CourierState, outcome: CourierDelivery
) -> bool:
    if (
        "app_confirmation"
        not in p.bundle.policy().verification.trusted_contact_methods_order
    ):
        return False
    if outcome.source == "real":
        current = await selected(p, str(state.contact_id), "app")
        if not current or current["id"] != state.channel_id:
            return False
        return bool(
            await p.connection.scalar(
                sa.select(db.members.c.id).where(
                    db.members.c.household_id == current["recipient_household"],
                    db.members.c.id == current["recipient_member"],
                    db.members.c.role.in_(["owner", "adult"]),
                )
            )
        )
    row = await p.repo.get("contact_channels", {"id": UUID(str(state.channel_id))})
    real = await p.connection.scalar(
        sa.select(db.contact_links.c.id)
        .where(
            p.scope(db.contact_links),
            db.contact_links.c.contact_id == UUID(str(state.contact_id)),
        )
        .limit(1)
    )
    return bool(
        not real
        and row
        and str(row["contact_id"]) == state.contact_id
        and row["attributes"].get("source") == "twin"
        and row["attributes"].get("verified_at")
    )


async def deliver(
    p: Pipeline,
    principal: Principal,
    case_id: str,
    state: CourierState,
    recipient: Literal["member", "contact"],
) -> CourierState:
    outcome = getattr(state, recipient)
    if outcome.status in {"published", "stopped"}:
        return state
    at = contact_time(p) if outcome.source == "real" else p.clock()
    reason = "expired" if at >= outcome.expires_at else None
    if recipient == "contact" and not await bound_channel(p, state, outcome):
        reason = "channel_revoked"
    action = action_for(p, case_id, state, recipient)
    if not reason and outcome.action_id is None:
        decision = await p.mutate_locked(action, principal)
        outcome = outcome.model_copy(
            update={
                "action_id": action.action_id,
                "status": "approval" if decision.decision == "ask" else "pending",
            }
        )
        if decision.decision not in {"execute", "ask"}:
            reason = "permission_denied"
    if not reason:
        stored = (
            (
                await p.connection.execute(
                    sa.select(db.actions).where(
                        p.scope(db.actions), db.actions.c.action_id == action.action_id
                    )
                )
            )
            .mappings()
            .one()
        )
        approval = (
            (
                await p.connection.execute(
                    sa.select(db.approvals)
                    .where(
                        p.scope(db.approvals),
                        db.approvals.c.action_id == action.action_id,
                    )
                    .order_by(db.approvals.c.created_at.desc())
                    .limit(1)
                )
            )
            .mappings()
            .one_or_none()
        )
        if approval and (
            approval["status"] in {"rejected", "expired"}
            or approval["expires_at"] <= p.clock()
        ):
            reason = "approval_refused"
        elif stored["grant_seq"] is None:
            # An unanswered ASK is not a grant. Current policy still must permit asking.
            evaluation = await p.assess_operation(
                action, principal, None, (), p.clock()
            )
            if evaluation.decision.decision not in {"execute", "ask"}:
                reason = "permission_changed"
            else:
                return state.model_copy(update={recipient: outcome})
        elif stored["proposal"][
            "params"
        ] != action.params or not await delivery_allowed(
            p, Action.model_validate(stored["proposal"]), principal
        ):
            reason = "permission_changed"
    if reason:
        return state.model_copy(
            update={
                recipient: outcome.model_copy(
                    update={"status": "stopped", "reason": reason}
                )
            }
        )
    if recipient == "contact":
        from hirz.contacts.worker import send_allowed

        if not await send_allowed(p, state.contact_id, at=at):
            return state.model_copy(update={recipient: outcome})
    await p.audit.append(
        p.connection,
        p.household_id,
        p.clock(),
        EventType.EXECUTED,
        {
            "operation": "courier",
            "action_id": action.action_id,
            "case_id": case_id,
            "recipient": recipient,
            "source": outcome.source,
            "press_source": state.source,
            "press_at": state.press_at.isoformat(),
            "result": "inbox_published"
            if outcome.source == "real"
            else "simulated_publication",
        },
    )
    return state.model_copy(
        update={
            recipient: outcome.model_copy(
                update={"status": "published", "published_at": at}
            )
        }
    )


async def advance(p: Pipeline) -> None:
    async with p.repo.write(p.clock):
        rows = (
            (
                await p.connection.execute(
                    sa.select(db.verification_cases)
                    .where(
                        p.scope(db.verification_cases),
                        sa.or_(
                            db.verification_cases.c.created_at
                            >= p.clock() - timedelta(minutes=61),
                            db.verification_cases.c.document["courier"]["member"][
                                "status"
                            ].astext.in_(["pending", "approval"]),
                            db.verification_cases.c.document["courier"]["contact"][
                                "status"
                            ].astext.in_(["pending", "approval"]),
                        ),
                    )
                    .order_by(
                        db.verification_cases.c.created_at, db.verification_cases.c.id
                    )
                )
            )
            .mappings()
            .all()
        )
        if not rows:
            return
        snapshot = await p.snapshot(p.clock())
        for row in rows:
            case = VerificationCase.model_validate(row["document"])
            try:
                principal = (
                    await account(p.connection, p.household_id, row["member_id"])
                ).model_copy(update={"surface": "scheduler"})
            except ValueError:
                if case.courier:
                    abandoned = case.courier
                    for removed_recipient in ("member", "contact"):
                        outcome = getattr(abandoned, removed_recipient)
                        if outcome.status in {"pending", "approval"}:
                            abandoned = abandoned.model_copy(
                                update={
                                    removed_recipient: outcome.model_copy(
                                        update={
                                            "status": "stopped",
                                            "reason": "member_removed",
                                        }
                                    )
                                }
                            )
                    if abandoned == case.courier:
                        continue
                    for survivor in snapshot.data["members"]:
                        try:
                            recorder = (
                                await account(
                                    p.connection,
                                    p.household_id,
                                    UUID(str(survivor["id"])),
                                )
                            ).model_copy(update={"surface": "scheduler"})
                        except ValueError:
                            continue
                        await save(p, recorder, case.case_id, abandoned)
                        break
                continue
            state = case.courier
            if state is None:
                event = trigger(case, row["created_at"], snapshot, p.clock())
                if event is None:
                    continue
                member = next(
                    m
                    for m in snapshot.data["members"]
                    if m["id"] == str(row["member_id"])
                )
                channel_id, contact_source = await channel(p, case, snapshot)
                # Real app recipients always use wall time, even for a simulated press.
                real_member = bool(
                    await p.connection.scalar(
                        sa.select(db.member_passkeys.c.credential_id)
                        .where(
                            p.scope(db.member_passkeys),
                            db.member_passkeys.c.member_id == row["member_id"],
                            db.member_passkeys.c.revoked_at.is_(None),
                        )
                        .limit(1)
                    )
                )
                state = CourierState(
                    press_at=event["state"]["last_press_at"],
                    observation_id=event["id"],
                    asset_id=event["asset_id"],
                    source=event["source"],
                    detected_at=p.clock(),
                    member_id=str(row["member_id"]),
                    member_name=str(member["display_name"]),
                    contact_id=case.subject.contact_id if channel_id else None,
                    channel_id=channel_id,
                    member=CourierDelivery(
                        source="real" if real_member else "twin",
                        expires_at=(contact_time(p) if real_member else p.clock())
                        + timedelta(minutes=5),
                    ),
                    contact=CourierDelivery(
                        source="real" if contact_source == "real" else "twin",
                        expires_at=(
                            contact_time(p) if contact_source == "real" else p.clock()
                        )
                        + timedelta(minutes=5),
                        status="pending" if channel_id else "stopped",
                        reason=None if channel_id else "no_eligible_contact",
                    ),
                )
            for recipient in ("member", "contact"):
                state = await deliver(p, principal, case.case_id, state, recipient)
            if state != case.courier:
                await save(p, principal, case.case_id, state)


def member_warning(case: VerificationCase) -> str | None:
    if not case.courier or case.courier.member.status != "published":
        return None
    return (SIMULATED + " " if case.courier.source != "real" else "") + MEMBER


async def warnings(p: Pipeline, member: UUID) -> list[dict[str, Any]]:
    """Cross-household projection contains no claim, amount, snapshot or case document."""
    rows = (
        (
            await p.connection.execute(
                sa.select(
                    db.verification_cases.c.household_id,
                    db.verification_cases.c.document,
                )
                .where(
                    sa.or_(
                        sa.and_(
                            p.scope(db.verification_cases),
                            db.verification_cases.c.member_id == member,
                        ),
                        sa.exists(
                            sa.select(db.contact_links.c.id).where(
                                db.contact_links.c.household_id
                                == db.verification_cases.c.household_id,
                                db.contact_links.c.id
                                == db.verification_cases.c.document["courier"][
                                    "channel_id"
                                ].astext,
                                db.contact_links.c.recipient_household
                                == p.household_id,
                                db.contact_links.c.recipient_member == member,
                                db.contact_links.c.kind == "app",
                                db.contact_links.c.status == "active",
                            )
                        ),
                    ),
                    db.verification_cases.c.document["courier"].is_not(None),
                )
                .order_by(db.verification_cases.c.created_at.desc())
            )
        )
        .mappings()
        .all()
    )
    result = []
    for row in rows:
        state = VerificationCase.model_validate(row["document"]).courier
        if state is None:
            continue
        own = row["household_id"] == p.household_id and state.member_id == str(member)
        outcome = state.member if own else state.contact
        if outcome.status != "published" or not own and outcome.source != "real":
            continue
        result.append(
            {
                "id": "courier:" + str(outcome.action_id),
                "text": MEMBER if own else CONTACT.format(member=state.member_name),
                "event_at": state.press_at.isoformat(),
                "source": state.source,
                "label": SIMULATED if state.source != "real" else None,
                "expires_at": outcome.expires_at.isoformat(),
                "delivery_source": outcome.source,
            }
        )
    return result
