"""Narrow tool bookkeeping hooks, called only inside a Pipeline grant transaction."""

from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa

from hirz import db
from hirz.executor.plans import governance
from hirz.pipeline.models import (
    Action,
    Decision,
    EventType,
    Principal,
    VerificationCase,
)
from hirz.pipeline.service import Pipeline

CLASSES = {
    "governance." + name
    for name in (
        "record_tool_request",
        "propose_rule",
        "request_plan",
        "record_verification",
    )
}


async def prepare(p: Pipeline, action: Action, principal: Principal) -> None:
    if p._household_command is None or action.params != p._household_command:
        raise ValueError("Household bookkeeping requires an internal command")
    if action.target.adapter != "household" or action.target.entity != str(
        p.household_id
    ):
        raise ValueError("Wrong household target")
    if (await p.requester(principal)).member_id is None:
        raise ValueError("Linked member required")
    if action.params.get("operation") == "finish" and principal.surface != "scheduler":
        raise ValueError("Only the worker finishes durable jobs")


async def command(
    p: Pipeline, name: str, params: dict[str, Any], principal: Principal
) -> Decision:
    if p._household_command is not None:
        raise ValueError("Nested household command")
    p._household_command = params
    try:
        decision = await p.mutate_locked(
            governance(p, name, params, principal), principal
        )
        if decision.decision != "execute":
            raise ValueError("Household bookkeeping was refused")
        return decision
    finally:
        p._household_command = None


async def commit(
    p: Pipeline, action: Action, decision: Decision, principal: Principal
) -> None:
    await prepare(p, action, principal)
    params: dict[str, Any] = dict(action.params)
    member = await p.requester(principal)
    assert member.member_id and decision.audit_id
    name = action.action_class
    values: dict[str, Any] = {
        "household_id": p.household_id,
        "decision_seq": decision.audit_id,
    }
    if name == "governance.record_tool_request":
        await p.connection.execute(db.tool_requests.insert().values(**values, **params))
    elif name == "governance.propose_rule":
        await p.connection.execute(
            db.rule_proposals.insert().values(
                **values,
                id=action.action_id,
                member_id=UUID(member.member_id),
                text=params["text"],
                surface=principal.surface,
                created_at=p.clock(),
            )
        )
        await p.audit.append(
            p.connection,
            p.household_id,
            p.clock(),
            EventType.CONSTITUTION_PROPOSED,
            {
                "proposal_id": action.action_id,
                "member_id": member.member_id,
                "surface": principal.surface,
                "text": params["text"],
                "decision_seq": decision.audit_id,
            },
        )
    elif name == "governance.request_plan":
        operation = params.pop("operation")
        if operation == "start":
            params["horizon_end"] = datetime.fromisoformat(str(params["horizon_end"]))
            await p.connection.execute(
                db.plan_requests.insert().values(
                    **values,
                    **params,
                    principal=principal.model_dump(mode="json"),
                    created_at=p.clock(),
                    status="pending",
                )
            )
        elif operation in {"finish", "revise"}:
            await p.connection.execute(
                db.plan_requests.update()
                .where(
                    p.scope(db.plan_requests),
                    db.plan_requests.c.id == params.pop("id"),
                    db.plan_requests.c.status == "pending",
                )
                .values(**params, decision_seq=decision.audit_id)
            )
        else:
            raise ValueError("Unknown plan request operation")
    else:
        case = VerificationCase.model_validate(params["case"])
        existing = (
            (
                await p.connection.execute(
                    sa.select(db.verification_cases).where(
                        p.scope(db.verification_cases),
                        db.verification_cases.c.id == case.case_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        operation = params["operation"]
        if operation == "assess":
            if existing or case.verification is not None:
                raise ValueError("An assessment cannot initiate contact")
            await p.connection.execute(
                db.verification_cases.insert().values(
                    **values,
                    id=case.case_id,
                    member_id=UUID(member.member_id),
                    document=case.model_dump(mode="json"),
                    created_at=p.clock(),
                )
            )
        else:
            if existing is None or str(existing["member_id"]) != member.member_id:
                raise ValueError("Private case is unavailable")
            old = VerificationCase.model_validate(existing["document"])
            if old.model_dump(exclude={"verification"}) != case.model_dump(
                exclude={"verification"}
            ):
                raise ValueError("Case claims are immutable")
            if operation == "start":
                contact_seq = params.get("contact_decision")
                grant = await p.connection.scalar(
                    sa.select(db.audit_log.c.payload).where(
                        p.scope(db.audit_log),
                        db.audit_log.c.seq == contact_seq,
                        db.audit_log.c.event_type == "EXECUTE",
                    )
                )
                if (
                    old.verification
                    or not case.verification
                    or case.verification.status != "pending"
                    or not grant
                    or grant["constitution"]["rule"]
                    != "communication.contact_trusted_contact"
                ):
                    raise ValueError(
                        "Contact initiation requires a fresh contact grant"
                    )
            elif operation == "finish":
                if (
                    principal.surface != "scheduler"
                    or not old.verification
                    or old.verification.status != "pending"
                    or not case.verification
                    or case.verification.status == "pending"
                ):
                    raise ValueError("Only the worker finishes a pending check")
                if old.verification.model_dump(
                    exclude={"status"}
                ) != case.verification.model_dump(exclude={"status"}):
                    raise ValueError("Verification binding changed")
            else:
                raise ValueError("Unknown case operation")
            await p.connection.execute(
                db.verification_cases.update()
                .where(
                    p.scope(db.verification_cases),
                    db.verification_cases.c.id == case.case_id,
                )
                .values(
                    document=case.model_dump(mode="json"),
                    decision_seq=decision.audit_id,
                )
            )
        await p.audit.append(
            p.connection,
            p.household_id,
            p.clock(),
            EventType.VERIFY,
            {
                "case_id": case.case_id,
                "operation": operation,
                "decision_seq": decision.audit_id,
                "source": "twin" if case.verification else "reported",
            },
        )
