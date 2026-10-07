"""Real check-in jobs and recipient-scoped receipts; network work belongs to the worker."""

import asyncio
import secrets
import smtplib
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa

from hirz import db
from hirz.companion.auth import account, digest
from hirz.contacts.secrets import Config, send_email
from hirz.contacts.service import addressed, contact_time, grant, link
from hirz.mcp.contracts import Result, response
from hirz.pipeline.hashing import action_hash
from hirz.pipeline.models import (
    Action,
    Principal,
    Requester,
    Target,
    VerificationCase,
    VerificationState,
)
from hirz.pipeline.service import Pipeline


async def selected(
    p: Pipeline, contact_id: str, method: str | None = None
) -> dict[str, Any] | None:
    methods = p.bundle.policy().verification.trusted_contact_methods_order
    for name in methods:
        kind = {"app_confirmation": "app", "verified_email": "email"}.get(name)
        if kind is None or method is not None and kind != method:
            continue
        row = (
            (
                await p.connection.execute(
                    sa.select(db.contact_links)
                    .where(
                        p.scope(db.contact_links),
                        db.contact_links.c.contact_id == UUID(contact_id),
                        db.contact_links.c.kind == kind,
                        db.contact_links.c.status == "active",
                    )
                    .with_for_update()
                )
            )
            .mappings()
            .one_or_none()
        )
        if row:
            return dict(row)
    return None


def request_hash(case: VerificationCase) -> str:
    return digest(case.claim.model_dump_json())


async def start(
    p: Pipeline, principal: Principal, case: VerificationCase, channel: dict[str, Any]
) -> Result:
    from hirz.mcp.trust import case_response

    member = await p.requester(principal)
    assert case.subject.contact_id
    if not principal.requester_confirmed:
        # Elicitation binds to stable case IDs generated from the request key by trust.verify.
        from hirz.pipeline.confirmation import RequesterReview, review_context

        review = review_context.get()
        confirmation = Action.model_validate(
            dict(
                action_id=case.case_id,
                action_class="communication.contact_trusted_contact",
                target=Target(adapter="contacts", entity=case.subject.contact_id),
                params={
                    "case_id": case.case_id,
                    "channel": channel["id"],
                    "request_hash": request_hash(case),
                },
                requested_by=Requester(
                    member_id=None, role="unknown", surface=principal.surface
                ),
                reason="Confirm this exact contact check",
                content_hash="",
            )
        )
        confirmation = confirmation.model_copy(
            update={"content_hash": action_hash(confirmation)}
        )
        binding = (
            review.binding(p.bundle.fingerprint, confirmation, principal)
            if review
            else ""
        )
        if not review or binding not in review.accepted:
            if review:
                raise RequesterReview(
                    binding,
                    confirmation,
                    f"Confirm a real {channel['kind']} check for this exact reported request: “{case.claim.text}”",
                )
            return response(
                "Please explicitly confirm this contact check.",
                status="clarification",
                code="CONFIRM_REQUIRED",
                case=case,
            )
        principal = principal.model_copy(update={"requester_confirmed": True})
    count = await p.connection.scalar(
        sa.select(sa.func.count())
        .select_from(db.checkin_jobs)
        .where(
            p.scope(db.checkin_jobs),
            db.checkin_jobs.c.created_at >= contact_time(p) - timedelta(days=1),
        )
    )
    recent = await p.connection.scalar(
        sa.select(sa.func.count())
        .select_from(db.checkin_jobs)
        .join(
            db.contact_links,
            db.contact_links.c.id == db.checkin_jobs.c.link_id,
        )
        .where(
            p.scope(db.checkin_jobs),
            db.contact_links.c.contact_id == channel["contact_id"],
            db.checkin_jobs.c.created_at >= contact_time(p) - timedelta(minutes=15),
        )
    )
    if (count or 0) >= 20 or (recent or 0) >= 3:
        return response(
            "The contact-check sending limit has been reached. Call the contact saved in your own phone.",
            status="unavailable",
            case=case,
        )
    action = Action.model_validate(
        dict(
            action_id=uuid4().hex,
            action_class="communication.contact_trusted_contact",
            target=Target(adapter="contacts", entity=case.subject.contact_id),
            params={
                "household_id": str(p.household_id),
                "member_id": member.member_id,
                "case_id": case.case_id,
                "channel": channel["id"],
                "request_hash": request_hash(case),
            },
            requested_by=Requester(
                member_id=None, role="unknown", surface=principal.surface
            ),
            reason="Check the reported request through a verified contact channel",
            content_hash="",
        )
    )
    action = action.model_copy(update={"content_hash": action_hash(action)})
    decision = await p.mutate_locked(action, principal)
    if decision.decision not in {"execute", "ask"}:
        return response(
            "The household rules have not permitted this check.",
            status="denied",
            case=case,
            decision=decision,
        )
    record = await grant(
        p,
        principal.model_copy(update={"surface": "scheduler"}),
        "process",
        case.case_id,
    )
    await p.connection.execute(
        db.checkin_jobs.insert().values(
            id=uuid4().hex,
            household_id=p.household_id,
            member_id=UUID(str(member.member_id)),
            link_id=channel["id"],
            case_id=case.case_id,
            action_id=action.action_id,
            request_hash=request_hash(case),
            principal=principal.model_dump(mode="json"),
            status="approval",
            attempts=0,
            created_at=contact_time(p),
            next_attempt=contact_time(p),
            decision_seq=record.audit_id,
        )
    )
    if decision.decision == "execute":
        await queued(p, principal, action, decision.audit_id)
        document = await p.connection.scalar(
            sa.select(db.verification_cases.c.document).where(
                p.scope(db.verification_cases),
                db.verification_cases.c.id == case.case_id,
            )
        )
        return case_response(VerificationCase.model_validate(document))
    return response(
        "Approve this contact check in your approval inbox. The reply deadline starts after approval.",
        status="queued",
        case=case,
        decision=decision,
    )


async def queued(
    p: Pipeline, principal: Principal, action: Action, decision_seq: int | None
) -> None:
    from hirz.mcp.persistence import command

    job = (
        (
            await p.connection.execute(
                sa.select(db.checkin_jobs).where(
                    p.scope(db.checkin_jobs),
                    db.checkin_jobs.c.action_id == action.action_id,
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if job is None or job["status"] != "approval":
        raise ValueError("Check-in approval is unavailable")
    channel = await link(p, job["link_id"])
    if channel["status"] != "active":
        raise ValueError("Contact channel was revoked")
    document = await p.connection.scalar(
        sa.select(db.verification_cases.c.document).where(
            p.scope(db.verification_cases),
            db.verification_cases.c.id == job["case_id"],
        )
    )
    case = VerificationCase.model_validate(document)
    if action.params != {
        "household_id": str(p.household_id),
        "member_id": str(job["member_id"]),
        "case_id": case.case_id,
        "channel": channel["id"],
        "request_hash": request_hash(case),
    }:
        raise ValueError("Contact request binding changed")
    assert case.subject.contact_id
    expires = contact_time(p) + timedelta(minutes=2 if channel["kind"] == "app" else 15)
    case = case.model_copy(
        update={
            "verification": VerificationState(
                status="pending",
                method="app_confirmation"
                if channel["kind"] == "app"
                else "verified_email",
                sent_to=case.subject.contact_id,
                started_at=contact_time(p),
                expires_at=expires,
                source="real",
            )
        }
    )
    await command(
        p,
        "record_verification",
        {
            "operation": "start",
            "case": case.model_dump(mode="json"),
            "contact_decision": decision_seq,
        },
        principal,
    )
    token = secrets.token_urlsafe(32)
    config = Config.environment()
    if config is None:
        raise ValueError("Contact encryption must be initialized")
    await p.connection.execute(
        db.checkin_jobs.update()
        .where(db.checkin_jobs.c.id == job["id"])
        .values(
            status="pending",
            expires_at=expires,
            token_digest=digest(token),
            ciphertext=config.seal({"token": token}),
            decision_seq=decision_seq,
        )
    )


async def reply(
    p: Pipeline, principal: Principal, reference: str, binding: str, answer: str | None
) -> dict[str, Any]:
    if answer not in {"genuine", "not_genuine", "will_call"}:
        raise ValueError("Choose a reply")
    row = (
        (
            await p.connection.execute(
                sa.select(db.checkin_jobs).where(db.checkin_jobs.c.id == reference)
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ValueError("Request unavailable")
    channel = await link(p, row["link_id"])
    member = await p.requester(principal)
    if (
        channel["kind"] != "app"
        or not addressed(channel, p.household_id, str(member.member_id))
        or member.role not in {"owner", "adult"}
    ):
        raise ValueError("Request unavailable")
    if (
        not principal.passkey_verified
        or not principal.credential_id
        or not await p.credential_current(principal)
    ):
        raise ValueError("A fresh bound passkey is required")
    return await receipt(
        p,
        principal,
        dict(row),
        channel,
        binding,
        answer,
        "passkey",
        UUID(str(member.member_id)),
    )


async def receipt(
    p: Pipeline,
    principal: Principal,
    job: dict[str, Any],
    channel: dict[str, Any],
    binding: str,
    answer: str,
    proof: str,
    member: UUID | None,
) -> dict[str, Any]:
    if channel["status"] != "active" or job["request_hash"] != binding:
        raise ValueError("Request was changed or revoked")
    old = (
        (
            await p.connection.execute(
                sa.select(db.checkin_receipts).where(
                    db.checkin_receipts.c.job_id == job["id"]
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if old:
        if (
            old["answer"] == answer
            and old["request_hash"] == binding
            and old["household_id"] == p.household_id
            and old["member_id"] == member
        ):
            return {"ok": True}
        raise ValueError("A different reply was already recorded")
    # Re-read after the channel lock, which all timeout/revocation paths also take.
    current = (
        (
            await p.connection.execute(
                sa.select(db.checkin_jobs)
                .where(db.checkin_jobs.c.id == job["id"])
                .with_for_update()
            )
        )
        .mappings()
        .one()
    )
    accepted_at = contact_time(p)
    if (
        current["status"] not in {"pending", "sending", "sent"}
        or channel["kind"] == "app"
        and current["status"] != "sent"
        or not current["expires_at"]
        or accepted_at >= current["expires_at"]
    ):
        raise ValueError("This request expired or closed")
    decision = await grant(
        p, principal, "reply" if proof == "passkey" else "process", job["id"]
    )
    from hirz.pipeline.models import EventType

    receipt_seq = await p.audit.append(
        p.connection,
        p.household_id,
        p.clock(),
        EventType.VERIFY,
        {
            "operation": "contact_receipt",
            "job_id": job["id"],
            "request_hash": binding,
            "answer": answer,
            "proof": proof,
            "member_id": str(member) if member else None,
            "accepted_at": accepted_at.isoformat(),
            "decision_seq": decision.audit_id,
        },
    )
    await p.connection.execute(
        db.checkin_receipts.insert().values(
            job_id=job["id"],
            household_id=p.household_id,
            member_id=member,
            answer=answer,
            request_hash=binding,
            proof=proof,
            accepted_at=accepted_at,
            decision_seq=receipt_seq,
        )
    )
    return {"ok": True}


async def advance(p: Pipeline) -> None:
    """Consume receipts and claim transport attempts under household/channel locks."""
    async with p.connection.begin():
        rows = (
            (
                await p.connection.execute(
                    sa.select(db.checkin_jobs.c.id).where(
                        p.scope(db.checkin_jobs),
                        db.checkin_jobs.c.status != "closed",
                    )
                )
            )
            .scalars()
            .all()
        )
    for reference in rows:
        delivery = None
        async with p.repo.write(p.clock):
            job = dict(
                (
                    await p.connection.execute(
                        sa.select(db.checkin_jobs).where(
                            p.scope(db.checkin_jobs),
                            db.checkin_jobs.c.id == reference,
                        )
                    )
                )
                .mappings()
                .one()
            )
            channel = await link(p, job["link_id"])
            principal = (
                await account(p.connection, p.household_id, job["member_id"])
            ).model_copy(update={"surface": "scheduler"})
            document = await p.connection.scalar(
                sa.select(db.verification_cases.c.document).where(
                    p.scope(db.verification_cases),
                    db.verification_cases.c.id == job["case_id"],
                )
            )
            case = VerificationCase.model_validate(document)
            accepted = (
                (
                    await p.connection.execute(
                        sa.select(db.checkin_receipts).where(
                            db.checkin_receipts.c.job_id == reference,
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            if job["status"] == "approval":
                approval = (
                    (
                        await p.connection.execute(
                            sa.select(db.approvals)
                            .where(
                                p.scope(db.approvals),
                                db.approvals.c.action_id == job["action_id"],
                            )
                            .order_by(db.approvals.c.created_at.desc())
                            .limit(1)
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                reason = None
                if channel["status"] != "active":
                    reason = "channel_revoked"
                elif (
                    not approval
                    or approval["status"] in {"rejected", "expired"}
                    or approval["expires_at"] <= p.clock()
                ):
                    reason = "approval_refused"
                elif not await p.credential_current(
                    Principal.model_validate(job["principal"])
                ):
                    reason = "permission_changed"
                if reason:
                    await finish(p, principal, job, case, "no_answer", reason)
                continue
            state = case.verification
            if state is None or state.source != "real":
                raise ValueError("Real delivery requires an explicitly real case")
            status, reason = None, None
            if accepted:
                if (
                    accepted["request_hash"] != job["request_hash"]
                    or accepted["accepted_at"] >= job["expires_at"]
                ):
                    raise ValueError("Invalid receipt binding")
                status = accepted["answer"]
            elif channel["status"] != "active":
                status, reason = "no_answer", "channel_revoked"
            elif contact_time(p) >= job["expires_at"]:
                status, reason = "no_answer", "expired"
            elif (
                job["attempts"] >= 3
                and job["status"] != "sent"
                and job["next_attempt"] <= contact_time(p)
            ):
                status, reason = "no_answer", "delivery_failed"
            if status:
                await finish(p, principal, job, case, status, reason)
                continue
            if job["status"] == "sent" or job["next_attempt"] > contact_time(p):
                continue
            action_row = (
                (
                    await p.connection.execute(
                        sa.select(db.actions).where(
                            p.scope(db.actions),
                            db.actions.c.action_id == job["action_id"],
                        )
                    )
                )
                .mappings()
                .one()
            )
            action = Action.model_validate(action_row["proposal"])
            original = Principal.model_validate(job["principal"])
            allowed = await delivery_allowed(p, action, original)
            if not allowed:
                await finish(p, principal, job, case, "no_answer", "permission_changed")
                continue
            from hirz.contacts.worker import send_allowed

            if not await send_allowed(p, channel["contact_id"]):
                continue
            decision = await grant(p, principal, "process", reference)
            attempts = job["attempts"] + 1
            await p.connection.execute(
                db.checkin_jobs.update()
                .where(db.checkin_jobs.c.id == reference)
                .values(
                    status="sent" if channel["kind"] == "app" else "sending",
                    attempts=attempts,
                    next_attempt=contact_time(p) + timedelta(seconds=30 * attempts),
                    decision_seq=decision.audit_id,
                )
            )
            if channel["kind"] == "email":
                config = Config.environment()
                if config is None:
                    raise ValueError("Contact configuration unavailable")
                delivery = (
                    config,
                    config.open(channel["ciphertext"])["destination"],
                    config.open(job["ciphertext"])["token"],
                )
        if delivery is None:
            continue
        permanent = False
        try:
            await asyncio.to_thread(send_email, *delivery)
            delivered = True
        except (smtplib.SMTPRecipientsRefused, smtplib.SMTPAuthenticationError):
            delivered, permanent = False, True
        except (OSError, smtplib.SMTPException, ValueError):
            delivered = False
        async with p.repo.write(p.clock):
            channel = await link(p, job["link_id"])
            current = dict(
                (
                    await p.connection.execute(
                        sa.select(db.checkin_jobs).where(
                            db.checkin_jobs.c.id == reference
                        )
                    )
                )
                .mappings()
                .one()
            )
            if current["status"] == "closed":
                continue
            decision = await grant(p, principal, "process", reference)
            await p.connection.execute(
                db.checkin_jobs.update()
                .where(db.checkin_jobs.c.id == reference)
                .values(
                    status="sent" if delivered else "pending",
                    attempts=3 if permanent else attempts,
                    next_attempt=contact_time(p)
                    if permanent
                    else contact_time(p) + timedelta(seconds=30 * attempts),
                    decision_seq=decision.audit_id,
                )
            )


async def finish(
    p: Pipeline,
    principal: Principal,
    job: dict[str, Any],
    case: VerificationCase,
    status: str,
    reason: str | None,
) -> None:
    decision = await grant(p, principal, "process", job["id"])
    if case.verification is None:
        # No reply deadline existed while approval was pending. Cancellation records
        # a zero-duration terminal interval; nothing was sent.
        channel = await link(p, job["link_id"])
        at = contact_time(p)
        case = case.model_copy(
            update={
                "verification": VerificationState(
                    status="pending",
                    method="app_confirmation"
                    if channel["kind"] == "app"
                    else "verified_email",
                    sent_to=str(channel["contact_id"]),
                    started_at=at,
                    expires_at=at,
                    source="real",
                )
            }
        )
    assert case.verification is not None
    if case.verification.status != "pending" or case.verification.source != "real":
        raise ValueError("Only a pending real check can finish")
    updated = case.model_copy(
        update={
            "verification": VerificationState.model_validate(
                case.verification.model_dump() | {"status": status, "reason": reason}
            )
        }
    )
    await p.connection.execute(
        db.verification_cases.update()
        .where(
            p.scope(db.verification_cases),
            db.verification_cases.c.id == case.case_id,
        )
        .values(
            document=updated.model_dump(mode="json"), decision_seq=decision.audit_id
        )
    )
    await p.connection.execute(
        db.checkin_jobs.update()
        .where(db.checkin_jobs.c.id == job["id"])
        .values(
            status="closed",
            ciphertext=None,
            decision_seq=decision.audit_id,
        )
    )
    from hirz.pipeline.models import EventType

    receipt_row = (
        (
            await p.connection.execute(
                sa.select(db.checkin_receipts).where(
                    db.checkin_receipts.c.job_id == job["id"]
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if receipt_row:
        payload = await p.connection.scalar(
            sa.select(db.audit_log.c.payload).where(
                db.audit_log.c.household_id == receipt_row["household_id"],
                db.audit_log.c.seq == receipt_row["decision_seq"],
                db.audit_log.c.event_type == "VERIFY",
            )
        )
        expected = {
            "operation": "contact_receipt",
            "job_id": job["id"],
            "request_hash": job["request_hash"],
            "answer": status,
            "proof": receipt_row["proof"],
            "member_id": str(receipt_row["member_id"])
            if receipt_row["member_id"]
            else None,
            "accepted_at": receipt_row["accepted_at"].isoformat(),
        }
        if not payload or any(payload.get(k) != v for k, v in expected.items()):
            raise ValueError("Contact receipt does not match its audited proof")
    await p.audit.append(
        p.connection,
        p.household_id,
        p.clock(),
        EventType.VERIFY,
        {
            "case_id": case.case_id,
            "status": status,
            "reason": reason,
            "source": "real",
            "worker_surface": "scheduler",
            "decision_seq": decision.audit_id,
            "receipt": {
                k: str(receipt_row[k])
                for k in (
                    "household_id",
                    "member_id",
                    "decision_seq",
                    "proof",
                    "accepted_at",
                )
            }
            if receipt_row
            else None,
        },
    )


async def delivery_allowed(p: Pipeline, action: Action, original: Principal) -> bool:
    """Revalidate the exact granted action, including any redeemed approval."""
    # Fresh evaluation is read-only; retain the exact grant/request binding.
    evaluation = await p.assess_operation(action, original, None, (), p.clock())
    approval = None
    voter = None
    allowed = evaluation.decision.decision == "execute" and await p.credential_current(
        original
    )
    if evaluation.decision.decision == "ask" and await p.credential_current(original):
        row = (
            (
                await p.connection.execute(
                    sa.select(db.approvals)
                    .where(
                        p.scope(db.approvals),
                        db.approvals.c.action_id == action.action_id,
                        db.approvals.c.status == "redeemed",
                        db.approvals.c.expires_at > p.clock(),
                    )
                    .order_by(db.approvals.c.approval_id.desc())
                    .limit(1)
                )
            )
            .mappings()
            .one_or_none()
        )
        if row:
            approval = dict(row)
            if p.compatible(
                approval["binding"], p.binding(action, original, None, evaluation)
            ):
                allowed, voter = await p.eligible_votes(approval, evaluation)
    if allowed:
        evaluation = await p.boundary_check(evaluation, p.clock(), approval, voter)
        allowed = evaluation.decision.decision == "execute"
    return allowed
