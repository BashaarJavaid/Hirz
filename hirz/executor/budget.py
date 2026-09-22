"""Append-only reservation adjustments; grant dates and uncertain costs are retained."""

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from hirz import db
from hirz.executor.contracts import ending
from hirz.executor.runtime import RuntimeInputs
from hirz.pipeline.models import Action, EventType

if TYPE_CHECKING:
    from hirz.pipeline.service import Pipeline


def intervals(runtime: RuntimeInputs) -> list[dict[str, str]]:
    return [
        dict(start=e.start.isoformat(), end=e.end.isoformat(), amount=str(e.reserved))
        for e in runtime.estimates
    ]


async def allocate(p: "Pipeline", stored: dict[str, Any], budget_action: Any) -> None:
    if not stored["runtime"]:
        raise ValueError("Runtime estimates are required for plan consent")
    runtime = RuntimeInputs.model_validate(stored["runtime"])
    grant = (
        await p.connection.execute(
            sa.select(db.audit_log.c.payload)
            .join(
                db.actions,
                sa.and_(
                    db.actions.c.household_id == db.audit_log.c.household_id,
                    db.actions.c.grant_seq == db.audit_log.c.seq,
                ),
            )
            .where(p.scope(db.actions), db.actions.c.action_id == budget_action)
        )
    ).scalar_one()
    reservation = stored.get("reservation") or {}
    allocations = reservation.get("allocations", []) + [
        e | {"grant": budget_action, "date": grant["budget"]["local_date"]}
        for e in reservation.get("estimates", intervals(runtime))
    ]
    await p.connection.execute(
        db.plans.update()
        .where(p.scope(db.plans), db.plans.c.plan_id == stored["plan_id"])
        .values(reservation=reservation | {"allocations": allocations})
    )


async def transfer(
    p: "Pipeline",
    old: dict[str, Any],
    runtime: RuntimeInputs,
    actions: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    now = p.clock()
    # ponytail: retain whole-house intervals through commitments; per-asset allocation
    # is only needed if conservative reservation retention becomes restrictive.
    until = now
    uncertain = False
    for row in actions:
        a = Action.model_validate(row["proposal"])
        if (row["lifecycle"] or {}).get("ending_of") or row[
            "execution_attempt_seq"
        ] is None:
            continue
        if row["execution_status"] != "verified":
            uncertain = True
        if a.revert:
            end_action = ending(a)
            completed = next(
                (r for r in actions if r["action_id"] == end_action.action_id), None
            )
            if not completed or completed["execution_status"] != "verified":
                until = max(until, end_action.scheduled_for or now)
        if (
            a.action_class == "energy.appliance_start"
            and runtime.workload.appliance
            and runtime.workload.appliance.running
        ):
            from datetime import timedelta

            appliance = runtime.workload.appliance
            until = max(
                until,
                now
                + timedelta(
                    seconds=appliance.cycle_minutes * 60 - appliance.elapsed_seconds
                ),
            )
    retained = []
    released: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for allocation in (old.get("reservation") or {}).get("allocations", []):
        start, end = (
            datetime.fromisoformat(allocation["start"]),
            datetime.fromisoformat(allocation["end"]),
        )
        amount = Decimal(allocation["amount"])
        cut = end if uncertain else max(start, min(end, until))
        kept = (
            amount
            * Decimal(str((cut - start).total_seconds()))
            / Decimal(str((end - start).total_seconds()))
        )
        if kept:
            retained.append(allocation | {"end": cut.isoformat(), "amount": str(kept)})
        released[(allocation["grant"], allocation["date"])] += amount - kept
    for (grant, date), amount in released.items():
        if amount:
            await p.audit.append(
                p.connection,
                p.household_id,
                now,
                EventType.RESERVATION_ADJUSTED,
                {
                    "plan_id": old["plan_id"],
                    "grant": grant,
                    "class": "energy.optimize_cost",
                    "local_date": date,
                    "delta": str(-amount),
                },
            )
    estimates = intervals(runtime)
    for e in estimates:
        start, end = (
            datetime.fromisoformat(e["start"]),
            datetime.fromisoformat(e["end"]),
        )
        credit = Decimal(0)
        for a in retained:
            left, right = (
                datetime.fromisoformat(a["start"]),
                datetime.fromisoformat(a["end"]),
            )
            overlap = max(0, (min(end, right) - max(start, left)).total_seconds())
            credit += (
                Decimal(a["amount"])
                * Decimal(str(overlap))
                / Decimal(str((right - left).total_seconds()))
            )
        e["amount"] = str(max(Decimal(0), Decimal(e["amount"]) - credit))
    return {"allocations": retained, "estimates": estimates}
