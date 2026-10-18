"""Worker-only inert boundary checks, with durable sessions and original deadlines."""

from datetime import datetime
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from hirz import db
from hirz.aws.gateway import SessionConflict
from hirz.aws.policy import fingerprint
from hirz.companion.auth import account
from hirz.companion.governance import constitution
from hirz.constitution.compiler import boundary_input
from hirz.pipeline.models import (
    BoundaryEvidence,
    BoundaryRequest,
    EventType,
    Principal,
    Role,
)

if TYPE_CHECKING:
    from hirz.pipeline.service import Evaluation, Pipeline


async def reissue(p: "Pipeline", principal: Principal, before: datetime) -> None:
    rows = (
        (
            await p.connection.execute(
                sa.select(db.approvals).where(
                    p.scope(db.approvals),
                    db.approvals.c.status.in_(["pending", "approved"]),
                    db.approvals.c.created_at <= before,
                )
            )
        )
        .mappings()
        .all()
    )
    if not rows:
        return
    await constitution(p, principal, "publish", "invalidate_gateway_approvals")
    for prior in rows:
        await p.status(dict(prior), "expired")
        if prior["expires_at"] > p.clock():
            await p.connection.execute(
                db.approvals.insert().values(
                    household_id=p.household_id,
                    approval_id="apr_" + uuid4().hex,
                    action_id=prior["action_id"],
                    status="pending",
                    created_at=p.clock(),
                    expires_at=prior["expires_at"],
                    binding=prior["binding"],
                )
            )


async def check(
    p: "Pipeline",
    ev: "Evaluation",
    at: datetime,
    approval: dict[str, Any] | None,
    voter: Principal | None,
    local: dict[Role, bool],
    context_hash: str,
) -> "Evaluation":
    from hirz.pipeline.service import result

    evidence: list[BoundaryRequest] = []
    results: dict[Role, bool] = {}
    completed = False
    reason = "AWS boundary unavailable; no execution"
    try:
        if p.gateway is None or p.policy_route is None:
            raise ValueError("AWS boundary requires the worker Gateway client")
        engine = (
            (
                await p.connection.execute(
                    sa.select(db.policy_engines)
                    .where(
                        db.policy_engines.c.id == p.policy_route.engine_id,
                    )
                    .with_for_update(read=True)
                )
            )
            .mappings()
            .one_or_none()
        )
        if engine is None or not engine["ready"]:
            raise ValueError("AWS actions paused during publication or recovery")
        assert ev.facts is not None and ev.action.requested_by.member_id is not None
        actor = (
            await account(
                p.connection, p.household_id, UUID(ev.action.requested_by.member_id)
            )
        ).model_copy(update={"surface": "scheduler"})
        await reissue(p, actor, engine["changed_at"])
        if approval and (
            approval["created_at"] <= engine["changed_at"]
            or approval["expires_at"] <= p.clock()
        ):
            raise ValueError("Approval expired or invalidated by policy publication")
        scope = (
            "plan:" + ev.action.plan_id
            if ev.action.plan_id
            else "action:" + ev.action.action_id
        )
        session = (
            (
                await p.connection.execute(
                    sa.select(db.gateway_sessions).where(
                        p.scope(db.gateway_sessions),
                        db.gateway_sessions.c.scope == scope,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if (
            session
            and session["conflicted"]
            and session["generation"] == engine["generation"]
            and session["engine_id"] == engine["id"]
        ):
            raise ValueError("Conflicted session requires verified policy recovery")
        if (
            session is None
            or session["generation"] != engine["generation"]
            or session["engine_id"] != engine["id"]
        ):
            await constitution(p, actor, "publish", scope)
            session_id = uuid4()
            await p.connection.execute(
                insert(db.gateway_sessions)
                .values(
                    household_id=p.household_id,
                    scope=scope,
                    engine_id=engine["id"],
                    generation=engine["generation"],
                    session_id=session_id,
                    conflicted=False,
                )
                .on_conflict_do_update(
                    index_elements=["household_id", "scope"],
                    set_={
                        "generation": engine["generation"],
                        "engine_id": engine["id"],
                        "session_id": session_id,
                        "conflicted": False,
                    },
                )
            )
        else:
            session_id = session["session_id"]
        approver = await p.requester(voter) if voter else None
        for role, allowed in local.items():
            action = ev.action.model_copy(
                update={
                    "requested_by": ev.action.requested_by.model_copy(
                        update={"role": role}
                    )
                }
            )
            inputs = boundary_input(
                p.bundle.compiled,
                action,
                ev.facts.policy,
                ttl_minutes=ev.outcomes[0].approval.ttl_minutes,
                session_id=str(session_id),
                approver_role=approver.role if approver else "",
                approval_channel=("app_push" if voter.surface == "app" else "alexa")
                if voter
                else "",
                quorum_satisfied=approval is not None,
            )
            for name in (["governance.approve_action"] if approval else []) + [
                action.action_class
            ]:
                if approval and p.clock() >= approval["expires_at"]:
                    raise ValueError("Original approval deadline passed")
                verdict = await p.gateway.invoke(name, inputs, session_id)
                evidence.append(
                    BoundaryRequest(
                        request_id=verdict.request_id,
                        trace_id=verdict.trace_id,
                        session_id=session_id,
                        policy_ids=verdict.policy_ids,
                        inventory_hash=fingerprint(engine["inventory"]),
                        generation=engine["generation"],
                        result="allow" if verdict.allowed else "deny",
                        mode=cast(Any, verdict.mode),
                    )
                )
                if name == "governance.approve_action" and not verdict.allowed:
                    raise ValueError("AWS refused the approval")
            results[role] = verdict.allowed and allowed
            if verdict.allowed != allowed:
                raise ValueError("Local and AWS policy decisions disagree")
        if approval and p.clock() >= approval["expires_at"]:
            raise ValueError("Original approval deadline passed")
        completed = True
        reason = "Inert AWS policy evaluation only; device execution is unavailable"
    except SessionConflict:
        await constitution(p, actor, "publish", scope)
        await p.connection.execute(
            db.gateway_sessions.update()
            .where(p.scope(db.gateway_sessions), db.gateway_sessions.c.scope == scope)
            .values(conflicted=True)
        )
        await reissue(p, actor, p.clock())
        reason = "Gateway session conflicted; prior approvals cannot be reused"
    except Exception as exc:
        reason = str(exc)
    ev.decision = ev.decision.model_copy(
        update={
            "boundary": BoundaryEvidence(
                engine="agentcore-policy",
                result="allow"
                if completed
                and results
                and all(results.values())
                and len(results) == len(local)
                else "deny",
                reason=reason,
                context_hash=context_hash,
                roles=results,
                requests=tuple(evidence),
            )
        }
    )
    # Item 37 has no signed command or execution transport. Never turn its receipt into a device grant.
    return result(ev, EventType.DENY_BOUNDARY)
