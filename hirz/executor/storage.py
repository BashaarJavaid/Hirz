"""Household-scoped lifecycle writes, inside the Pipeline graph transaction."""

from typing import TYPE_CHECKING, Any
from uuid import UUID

import sqlalchemy as sa

from hirz import db
from hirz.pipeline.hashing import digest
from hirz.pipeline.models import Action, Decision, EventType

if TYPE_CHECKING:
    from hirz.pipeline.service import Pipeline


async def row(p: "Pipeline", action_id: str) -> dict[str, Any]:
    found = (
        (
            await p.connection.execute(
                sa.select(db.actions)
                .where(p.scope(db.actions), db.actions.c.action_id == action_id)
                .with_for_update()
            )
        )
        .mappings()
        .one()
    )
    return dict(found)


async def transition(
    p: "Pipeline", action_id: str, status: str, event: EventType, **details: Any
) -> int:
    seq = await p.audit.append(
        p.connection,
        p.household_id,
        p.clock(),
        event,
        {"action_id": action_id, "status": status, **details},
    )
    await p.connection.execute(
        db.actions.update()
        .where(p.scope(db.actions), db.actions.c.action_id == action_id)
        .values(execution_status=status, lifecycle_seq=seq)
    )
    return seq


async def notice(p: "Pipeline", member_id: str, action_id: str, message: str) -> None:
    seq = await p.audit.append(
        p.connection,
        p.household_id,
        p.clock(),
        EventType.NOTICE_PENDING,
        {
            "action_id": action_id,
            "member_id": member_id,
            "message": message,
            "delivery": "pending",
        },
    )
    await p.connection.execute(
        db.pending_notifications.insert().values(
            household_id=p.household_id,
            member_id=UUID(member_id),
            audit_seq=seq,
            message=message,
        )
    )


async def scheduled(
    p: "Pipeline",
    action: Action,
    decision: Decision,
    approval_id: str | None,
    *,
    retry_of: str | None = None,
) -> Decision:
    from hirz.executor.contracts import ending

    if action.revert:
        assert action.scheduled_for
        end = ending(action)
        existing = (
            await p.connection.execute(
                sa.select(db.actions).where(
                    p.scope(db.actions),
                    db.actions.c.lifecycle.is_not(None),
                    db.actions.c.execution_status.not_in(
                        ["cancelled", "skipped", "held"]
                    ),
                )
            )
        ).mappings()
        for other in existing:
            candidate = Action.model_validate(other["proposal"])
            if (
                candidate.action_id in {action.action_id, retry_of}
                or not candidate.revert
            ):
                continue
            candidate_end = ending(candidate)
            assert (
                candidate.scheduled_for
                and candidate_end.scheduled_for
                and end.scheduled_for
            )
            if (
                candidate.target == action.target
                and candidate.scheduled_for < end.scheduled_for
                and action.scheduled_for < candidate_end.scheduled_for
            ):
                ended = await p.connection.scalar(
                    sa.select(db.actions.c.execution_status).where(
                        p.scope(db.actions),
                        db.actions.c.action_id == candidate_end.action_id,
                    )
                )
                if ended != "verified":
                    raise ValueError("Overlapping bounded operations are refused")
    decision = decision.model_copy(
        update={
            "status": "executing",
            "speakable": {"headline": "Your request is queued."},
        }
    )
    seq = await transition(
        p,
        action.action_id,
        "scheduled",
        EventType.SCHEDULED,
        decision=decision.model_dump(mode="json", by_alias=True),
    )
    await p.connection.execute(
        db.actions.update()
        .where(p.scope(db.actions), db.actions.c.action_id == action.action_id)
        .values(
            due_at=action.scheduled_for or p.clock(),
            lifecycle={
                "decision": decision.model_dump(mode="json", by_alias=True),
                "approval_id": approval_id,
                "member_id": action.requested_by.member_id,
                "retry": 0,
            },
        )
    )
    return decision.model_copy(update={"audit_id": seq})


async def repeated(p: "Pipeline", stored: dict[str, Any]) -> Decision:
    lifecycle = stored["lifecycle"]
    decision = Decision.model_validate(lifecycle["decision"])
    status = stored["execution_status"]
    headline = (
        "Your request is queued."
        if status == "scheduled"
        else {
            "verified": "The requested setting was verified.",
            "failed": "The requested setting could not be verified.",
            "held": "This request needs your attention.",
            "cancelled": "This request was cancelled.",
            "skipped": "This request's execution window has ended.",
        }.get(status, "The request's outcome is not yet verified.")
    )
    if status == "verified" and stored["proposal"]["target"]["adapter"] == "twin":
        headline = "The simulated setting was verified."
    return decision.model_copy(
        update={
            "status": "executing" if status == "scheduled" else status,
            "speakable": {"headline": headline},
            "audit_id": stored["lifecycle_seq"],
        }
    )


async def authorize_ending(p: "Pipeline", action: Action, decision: Decision) -> None:
    from hirz.executor.contracts import ending
    from hirz.pipeline.models import Principal
    from hirz.pipeline.service import identity

    if action.revert is None:
        return
    end = ending(action)
    opening = await row(p, action.action_id)
    principal = Principal.model_validate(opening["principal"])
    seq = await p.audit.append(
        p.connection,
        p.household_id,
        p.clock(),
        EventType.ENDING_AUTHORIZED,
        {
            "opening": action.action_id,
            "opening_hash": action.content_hash,
            "grant_seq": decision.audit_id,
            "ending": end.model_dump(mode="json", by_alias=True),
        },
    )
    end_decision = decision.model_copy(
        update={"action_id": end.action_id, "audit_id": seq}
    )
    await p.connection.execute(
        db.actions.insert().values(
            household_id=p.household_id,
            action_id=end.action_id,
            proposal=end.model_dump(mode="json", by_alias=True),
            principal=identity(principal),
            grant_seq=seq,
            due_at=end.scheduled_for,
            execution_status="scheduled",
            lifecycle_seq=seq,
            lifecycle={
                "ending_of": action.action_id,
                "decision": end_decision.model_dump(mode="json", by_alias=True),
                "member_id": opening["lifecycle"]["member_id"],
                "retry": 0,
            },
        )
    )


async def validate_ending(p: "Pipeline", action: Action, grant: dict[str, Any]) -> None:
    from hirz.audit import Verification
    from hirz.executor.contracts import ending

    parent = await row(p, grant["payload"]["opening"])
    opening = Action.model_validate(parent["proposal"])
    if (
        grant["event_type"] != EventType.ENDING_AUTHORIZED
        or parent["execution_attempt_seq"] is None
        or parent["grant_seq"] != grant["payload"]["grant_seq"]
        or opening.content_hash != grant["payload"]["opening_hash"]
        or digest(ending(opening).model_dump(mode="json", by_alias=True))
        != digest(action.model_dump(mode="json", by_alias=True))
        or digest(grant["payload"]["ending"])
        != digest(action.model_dump(mode="json", by_alias=True))
    ):
        raise ValueError("Bounded ending does not match its original operation")
    original = dict(
        (
            await p.connection.execute(
                sa.select(db.audit_log).where(
                    p.scope(db.audit_log), db.audit_log.c.seq == parent["grant_seq"]
                )
            )
        )
        .mappings()
        .one()
    )
    Verification(p.household_id, p.audit.key.public_key()).feed(original)
    if original["event_type"] != EventType.EXECUTE:
        raise ValueError("Missing original bounded operation grant")


async def retry(p: "Pipeline", original: Action) -> Decision | None:
    """A fresh proposal, fresh assessment and one audited retry; no copied grant/vote."""
    from decimal import Decimal
    from uuid import uuid4

    from hirz.executor.contracts import ending
    from hirz.pipeline.hashing import action_hash
    from hirz.pipeline.models import Principal

    async with p.repo.write(p.clock):
        parent = await row(p, original.action_id)
        if parent["execution_status"] != "failed" or parent["lifecycle"].get(
            "retry", 0
        ):
            return None
        already = await p.connection.scalar(
            sa.select(db.actions.c.action_id).where(
                p.scope(db.actions),
                db.actions.c.lifecycle["retry_of"].astext == original.action_id,
            )
        )
        if already:
            return None
        # Overlapping bounded operations cannot be retried until their ending is verified.
        # A late opening is shortened to the original absolute ending, never extended.
        at = p.clock()
        changes: dict[str, Any] = {"action_id": uuid4().hex, "scheduled_for": at}
        if original.revert:
            end = ending(original)
            assert end.scheduled_for
            remaining = int((end.scheduled_for - at).total_seconds())
            if remaining <= 0:
                return None
            changes["revert"] = original.revert.model_copy(
                update={"after_s": remaining}
            )
        action = original.model_copy(update=changes)
        action = action.model_copy(update={"content_hash": action_hash(action)})
        principal = Principal.model_validate(parent["principal"])
        cost = Decimal(parent["cost"]) if parent["cost"] is not None else None
        await p.proposal(action, principal, cost)
        if action.plan_id:
            await p.connection.execute(
                db.plan_actions.insert().values(
                    household_id=p.household_id,
                    plan_id=action.plan_id,
                    action_id=action.action_id,
                )
            )
        ev = await p.assess_operation(action, principal, cost, (), at)
        if ev.decision.decision != "execute":
            ev = await p.ask(ev, action, principal, cost, at)
            return await p.record(ev, at)
        # The retry is part of the same bounded operation and retains the same stop.
        result = await scheduled(
            p, ev.action, ev.decision, None, retry_of=original.action_id
        )
        current = await row(p, action.action_id)
        await p.connection.execute(
            db.actions.update()
            .where(p.scope(db.actions), db.actions.c.action_id == action.action_id)
            .values(
                lifecycle=current["lifecycle"]
                | {"retry": 1, "retry_of": original.action_id}
            )
        )
        await p.audit.append(
            p.connection,
            p.household_id,
            p.clock(),
            EventType.SCHEDULED,
            {"action_id": action.action_id, "retry_of": original.action_id},
        )
        return result
