"""Private companion and mailbox-capability routes; no bearer token in a URL."""

from typing import Any, Literal

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from hirz import db
from hirz.companion.api import Companion
from hirz.companion.auth import account, digest
from hirz.contacts import checkins
from hirz.contacts.service import contact_time, grant, guess, link
from hirz.graph.models import now
from hirz.mcp.trust import case_response
from hirz.pipeline.models import VerificationCase


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Guess(Input):
    case_id: str = Field(max_length=128)
    value: str = Field(max_length=512)


class Retry(Input):
    case_id: str = Field(max_length=128)
    method: Literal["app", "email"]
    confirmed: Literal[True]
    request_id: str = Field(min_length=1, max_length=128)


class Capability(Input):
    token: str = Field(min_length=43, max_length=43, pattern=r"^[A-Za-z0-9_-]+$")
    request_hash: str | None = Field(default=None, max_length=64)
    answer: Literal["genuine", "not_genuine", "will_call"] | None = None


def router(service: Companion) -> APIRouter:
    api = APIRouter()

    @api.get("/contacts")
    async def contacts(request: Request, response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        async with service.authorized(request) as (p, current):
            member = await p.requester(current["principal"])
            rows = (
                (
                    await p.connection.execute(
                        sa.select(db.contact_links).where(
                            sa.or_(
                                sa.and_(
                                    p.scope(db.contact_links),
                                    sa.literal(member.role == "owner"),
                                ),
                                sa.and_(
                                    db.contact_links.c.recipient_household
                                    == p.household_id,
                                    db.contact_links.c.recipient_member
                                    == current["member_id"],
                                ),
                            )
                        )
                    )
                )
                .mappings()
                .all()
            )
            return {
                "links": [
                    {
                        k: row[k]
                        for k in ("id", "contact_id", "kind", "status", "expires_at")
                    }
                    | {"received": row["household_id"] != p.household_id}
                    for row in rows
                ]
            }

    @api.get("/checkins")
    async def inbox(request: Request, response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        async with service.authorized(request) as (p, current):
            own = (
                (
                    await p.connection.execute(
                        sa.select(db.verification_cases.c.document)
                        .where(
                            p.scope(db.verification_cases),
                            db.verification_cases.c.member_id == current["member_id"],
                        )
                        .order_by(db.verification_cases.c.created_at.desc())
                        .limit(50)
                    )
                )
                .scalars()
                .all()
            )
            received = (
                (
                    await p.connection.execute(
                        sa.select(
                            db.checkin_jobs,
                            db.verification_cases.c.document,
                            db.members.c.display_name,
                        )
                        .join(
                            db.contact_links,
                            db.checkin_jobs.c.link_id == db.contact_links.c.id,
                        )
                        .join(
                            db.verification_cases,
                            sa.and_(
                                db.verification_cases.c.household_id
                                == db.checkin_jobs.c.household_id,
                                db.verification_cases.c.id == db.checkin_jobs.c.case_id,
                            ),
                        )
                        .join(
                            db.members,
                            sa.and_(
                                db.members.c.household_id
                                == db.checkin_jobs.c.household_id,
                                db.members.c.id == db.checkin_jobs.c.member_id,
                            ),
                        )
                        .where(
                            db.contact_links.c.recipient_household == p.household_id,
                            db.contact_links.c.recipient_member == current["member_id"],
                            db.contact_links.c.status == "active",
                            db.contact_links.c.kind == "app",
                            db.checkin_jobs.c.status == "sent",
                            ~sa.exists(
                                sa.select(db.checkin_receipts.c.job_id).where(
                                    db.checkin_receipts.c.job_id == db.checkin_jobs.c.id
                                )
                            ),
                            db.checkin_jobs.c.expires_at > contact_time(p),
                        )
                        .order_by(db.checkin_jobs.c.created_at.desc())
                        .limit(50)
                    )
                )
                .mappings()
                .all()
            )
            return {
                "cases": [
                    case_response(VerificationCase.model_validate(c)).model_dump(
                        mode="json"
                    )
                    for c in own
                ],
                "received": [
                    {
                        "id": r["id"],
                        "requester": r["display_name"],
                        "text": r["document"]["claim"]["text"],
                        "request_hash": r["request_hash"],
                        "expires_at": r["expires_at"],
                        "source": "real",
                    }
                    for r in received
                ],
            }

    @api.post("/checkins/safe-word")
    async def safe_word(value: Guess, request: Request) -> dict[str, Any]:
        async with service.authorized(request) as (p, current):
            return await guess(p, current["principal"], value.case_id, value.value)

    @api.post("/checkins/retry")
    async def retry(value: Retry, request: Request) -> dict[str, Any]:
        from hirz.mcp.household import HouseholdTools

        async with service.engine.begin() as c:
            from hirz.companion.auth import session

            service.guard(request, authenticated=True)
            current = await session(
                c, request.cookies.get(service.config.session_cookie, ""), now()
            )
        async with service.pipeline(current["household_id"]) as p:
            result = await HouseholdTools(
                p, current["principal"].model_copy(update={"requester_confirmed": True})
            ).call(
                "verify_trusted_identity",
                {
                    "operation": "retry",
                    "case_id": value.case_id,
                    "method": value.method,
                    "request_id": value.request_id,
                },
            )
            return result.model_dump(mode="json")

    @api.post("/contact-links/view")
    async def view(
        value: Capability, request: Request, response: Response
    ) -> dict[str, Any]:
        return await mailbox(value, request, response, False)

    @api.post("/contact-links/confirm")
    async def confirm(
        value: Capability, request: Request, response: Response
    ) -> dict[str, Any]:
        return await mailbox(value, request, response, True)

    async def mailbox(
        value: Capability, request: Request, response: Response, commit: bool
    ) -> dict[str, Any]:
        response.headers.update(
            {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
        )
        service.guard(request)
        async with service.engine.begin() as c:
            enrollment = (
                (
                    await c.execute(
                        sa.select(db.contact_links).where(
                            db.contact_links.c.token_digest == digest(value.token),
                            db.contact_links.c.kind == "email",
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            job = (
                (
                    await c.execute(
                        sa.select(db.checkin_jobs).where(
                            db.checkin_jobs.c.token_digest == digest(value.token)
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
        if enrollment is None and job is None:
            raise HTTPException(400, "This private link is unavailable")
        target = enrollment if enrollment is not None else job
        assert target is not None
        owner_household = target["household_id"]
        async with service.pipeline(owner_household) as p:
            async with p.repo.write(p.clock):
                channel = await link(
                    p, target["id"] if enrollment else target["link_id"]
                )
                if enrollment:
                    if channel["status"] != "pending" or channel[
                        "expires_at"
                    ] <= contact_time(p):
                        raise ValueError(
                            "This private link expired or was already used"
                        )
                    if commit:
                        principal = (
                            await account(
                                p.connection, p.household_id, channel["owner_id"]
                            )
                        ).model_copy(update={"surface": "scheduler"})
                        decision = await grant(p, principal, "process", channel["id"])
                        await p.connection.execute(
                            db.contact_links.update()
                            .where(db.contact_links.c.id == channel["id"])
                            .values(
                                status="confirmed",
                                proof={
                                    "kind": "mailbox",
                                    "accepted_at": contact_time(p).isoformat(),
                                    "decision_seq": decision.audit_id,
                                },
                                decision_seq=decision.audit_id,
                            )
                        )
                    return {
                        "kind": "enrollment",
                        "confirmed": commit,
                        "message": "Confirm this mailbox. The owner must separately confirm the intended contact.",
                    }
                assert job is not None
                if (
                    channel["kind"] != "email"
                    or channel["status"] != "active"
                    or job["status"] == "approval"
                    or job["expires_at"] <= contact_time(p)
                ):
                    raise ValueError("This private request is unavailable")
                document = await p.connection.scalar(
                    sa.select(db.verification_cases.c.document).where(
                        p.scope(db.verification_cases),
                        db.verification_cases.c.id == job["case_id"],
                    )
                )
                case = VerificationCase.model_validate(document)
                if not case.verification or case.verification.source != "real":
                    raise ValueError("This is not a real check-in")
                if commit:
                    if value.answer is None:
                        raise ValueError("Choose a response")
                    from hirz.pipeline.models import Principal

                    principal = Principal.model_validate(job["principal"]).model_copy(
                        update={"surface": "scheduler"}
                    )
                    return await checkins.receipt(
                        p,
                        principal,
                        dict(job),
                        channel,
                        value.request_hash or "",
                        value.answer,
                        "mailbox",
                        None,
                    )
                used = await p.connection.scalar(
                    sa.select(db.checkin_receipts.c.job_id).where(
                        db.checkin_receipts.c.job_id == job["id"]
                    )
                )
                if used or job["status"] == "closed":
                    raise ValueError("This private link was already used")
                name = await p.connection.scalar(
                    sa.select(db.members.c.display_name).where(
                        p.scope(db.members), db.members.c.id == job["member_id"]
                    )
                )
                return {
                    "kind": "checkin",
                    "requester": name,
                    "text": case.claim.text,
                    "request_hash": job["request_hash"],
                    "source": "real",
                }

    return api
