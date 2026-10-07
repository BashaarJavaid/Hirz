"""Scoped contact enrollment. Every mutation follows an audited Pipeline grant."""

import asyncio
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.dialects.postgresql import insert

from hirz import db
from hirz.companion.auth import digest
from hirz.companion.governance import household
from hirz.contacts.secrets import Config, check_word, email, hash_word
from hirz.executor.plans import governance
from hirz.graph.models import ContactChannel, TrustedContact, now
from hirz.pipeline.models import Decision, Principal
from hirz.pipeline.service import Pipeline


def contact_time(p: Pipeline) -> datetime:
    """Real communication deadlines use wall time, even inside a paced twin demo."""
    return now()


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal[
        "create",
        "invite",
        "confirm",
        "revoke",
        "remove",
        "word",
        "accept",
        "withdraw",
        "phone",
        "reply",
    ]
    contact_id: UUID | None = None
    reference: str | None = Field(default=None, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    relationship: str | None = Field(default=None, min_length=1, max_length=100)
    method: Literal["app", "email"] | None = None
    value: str | None = Field(default=None, max_length=512)
    request_hash: str | None = Field(default=None, max_length=64)
    answer: Literal["genuine", "not_genuine", "will_call"] | None = None


async def grant(
    p: Pipeline, principal: Principal, operation: str, reference: str
) -> Decision:
    params = {"operation": operation, "reference": reference}
    action = governance(p, "contacts", params, principal)
    return await household(
        p,
        principal.model_copy(update={"verified_action_hash": action.content_hash}),
        "contacts",
        params,
    )


async def link(p: Pipeline, reference: str) -> dict[str, Any]:
    row = (
        (
            await p.connection.execute(
                sa.select(db.contact_links)
                .where(db.contact_links.c.id == reference)
                .with_for_update()
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ValueError("Contact link unavailable")
    return dict(row)


def addressed(row: dict[str, Any], household_id: UUID, member_id: str) -> bool:
    return (
        row["recipient_household"] == household_id
        and str(row["recipient_member"]) == member_id
    )


async def command(
    p: Pipeline, principal: Principal, value: Command, config: Config
) -> dict[str, Any]:
    member = await p.requester(principal)
    if (
        not principal.passkey_verified
        or not principal.credential_id
        or not await p.credential_current(principal)
    ):
        raise ValueError("A fresh bound passkey is required")
    if value.operation == "reply":
        from hirz.contacts.checkins import reply

        return await reply(
            p, principal, value.reference or "", value.request_hash or "", value.answer
        )
    if value.operation == "create":
        if not value.name or not value.relationship:
            raise ValueError("Name and relationship are required")
        contact_reference = uuid4()
        await grant(p, principal, "create", str(contact_reference))
        await p.repo.put(
            "trusted_contacts",
            TrustedContact(
                id=contact_reference,
                household_id=p.household_id,
                display_name=value.name,
                relationship=value.relationship,
            ),
        )
        return {"id": str(contact_reference)}
    if value.operation in {"accept", "withdraw", "phone"}:
        if member.role not in {"owner", "adult"}:
            raise ValueError("An enrolled owner or adult is required")
        if value.operation == "accept":
            invitation = (
                (
                    await p.connection.execute(
                        sa.select(db.contact_links)
                        .where(
                            db.contact_links.c.token_digest
                            == digest(value.value or ""),
                            db.contact_links.c.kind == "app",
                        )
                        .with_for_update()
                    )
                )
                .mappings()
                .one_or_none()
            )
            if (
                invitation is None
                or invitation["status"] != "pending"
                or invitation["expires_at"] <= contact_time(p)
                or invitation["household_id"] == p.household_id
            ):
                raise ValueError("Invitation unavailable or expired")
            decision = await grant(p, principal, "accept", invitation["id"])
            await p.connection.execute(
                db.contact_links.update()
                .where(db.contact_links.c.id == invitation["id"])
                .values(
                    status="confirmed",
                    recipient_household=p.household_id,
                    recipient_member=UUID(str(member.member_id)),
                    proof={
                        "household_id": str(p.household_id),
                        "member_id": member.member_id,
                        "decision_seq": decision.audit_id,
                        "kind": "passkey",
                        "accepted_at": contact_time(p).isoformat(),
                    },
                )
            )
            return {
                "message": "Accepted. The initiating owner must confirm the pairing."
            }
        row = await link(p, value.reference or "")
        if (
            row["kind"] != "app"
            or not addressed(row, p.household_id, str(member.member_id))
            or row["status"] not in {"active", "confirmed"}
        ):
            raise ValueError("Contact link unavailable")
        decision = await grant(p, principal, value.operation, row["id"])
        proof = dict(row["proof"] or {})
        proof["recipient_decision_seq"] = decision.audit_id
        if value.operation == "phone":
            from hirz.mcp.trust import phone

            proof.update(
                phone_hash=digest(phone(value.value or "")),
                phone_provenance="contact-confirmed",
            )
            await p.connection.execute(
                db.contact_links.update()
                .where(db.contact_links.c.id == row["id"])
                .values(proof=proof)
            )
        else:
            await p.connection.execute(
                db.contact_links.update()
                .where(db.contact_links.c.id == row["id"])
                .values(status="revoked", proof=proof)
            )
        return {"ok": True}
    if member.role != "owner" or value.contact_id is None:
        raise ValueError("The household owner must select a contact")
    contact = await p.repo.get("trusted_contacts", {"id": value.contact_id})
    if contact is None:
        raise ValueError("Contact unavailable")
    if value.operation == "remove":
        from hirz.companion.contacts import remove

        await remove(p, principal, value.contact_id)
        return {"ok": True}
    if value.operation == "word":
        hashed = await asyncio.to_thread(hash_word, value.value or "")
        decision = await grant(p, principal, "word", str(value.contact_id))
        await p.connection.execute(
            insert(db.contact_secrets)
            .values(
                household_id=p.household_id,
                contact_id=value.contact_id,
                word_hash=hashed,
                guesses=[],
                decision_seq=decision.audit_id,
            )
            .on_conflict_do_update(
                index_elements=["household_id", "contact_id"],
                set_={
                    "word_hash": hashed,
                    "guesses": [],
                    "decision_seq": decision.audit_id,
                },
            )
        )
        return {"ok": True}
    if value.operation == "invite":
        if value.method not in {"app", "email"}:
            raise ValueError("Choose app or email")
        destination = email(value.value or "") if value.method == "email" else ""
        reference, token = uuid4().hex, secrets.token_urlsafe(32)
        decision = await grant(p, principal, "invite", reference)
        await p.connection.execute(
            db.contact_links.insert().values(
                id=reference,
                household_id=p.household_id,
                contact_id=value.contact_id,
                owner_id=UUID(str(member.member_id)),
                kind=value.method,
                status="pending",
                token_digest=digest(token),
                ciphertext=config.seal({"destination": destination, "token": token})
                if destination
                else None,
                created_at=contact_time(p),
                expires_at=contact_time(p)
                + timedelta(minutes=15 if destination else 1440),
                decision_seq=decision.audit_id,
                proof={"requester": principal.model_dump(mode="json")},
            )
        )
        return {
            "id": reference,
            **(
                {"invitation": token}
                if not destination
                else {
                    "message": "Mailbox confirmation queued; owner confirmation is still required."
                }
            ),
        }
    row = await link(p, value.reference or "")
    if row["household_id"] != p.household_id or row["contact_id"] != value.contact_id:
        raise ValueError("Contact link unavailable")
    if value.operation == "confirm":
        if row["status"] != "confirmed" or row["expires_at"] <= contact_time(p):
            raise ValueError("A current contact confirmation is required")
        if row["kind"] == "app":
            eligible = await p.connection.scalar(
                sa.select(db.members.c.id).where(
                    db.members.c.household_id == row["recipient_household"],
                    db.members.c.id == row["recipient_member"],
                    db.members.c.role.in_(["owner", "adult"]),
                )
            )
            from hirz.companion.auth import account

            if not eligible or not await p.connection.scalar(
                sa.select(db.member_passkeys.c.credential_id)
                .where(
                    db.member_passkeys.c.household_id == row["recipient_household"],
                    db.member_passkeys.c.member_id == row["recipient_member"],
                    db.member_passkeys.c.revoked_at.is_(None),
                )
                .limit(1)
            ):
                raise ValueError("Recipient no longer eligible")
            await account(
                p.connection, row["recipient_household"], row["recipient_member"]
            )
        decision = await grant(p, principal, "confirm", row["id"])
        # Versions are immutable link IDs. Replacing one revokes its outstanding grants.
        await p.connection.execute(
            db.contact_links.update()
            .where(
                p.scope(db.contact_links),
                db.contact_links.c.contact_id == value.contact_id,
                db.contact_links.c.kind == row["kind"],
                db.contact_links.c.status == "active",
            )
            .values(status="revoked", decision_seq=decision.audit_id)
        )
        await p.connection.execute(
            db.contact_links.update()
            .where(db.contact_links.c.id == row["id"])
            .values(status="active", decision_seq=decision.audit_id)
        )
        await p.repo.put(
            "contact_channels",
            ContactChannel(
                household_id=p.household_id,
                id=UUID(row["id"]),
                contact_id=value.contact_id,
                kind="hirz_app" if row["kind"] == "app" else "email",
                value_hash=digest(row["id"]),
                verified_at=p.repo._at,
                source="real",
            ),
        )
        return {"ok": True}
    if value.operation == "revoke":
        decision = await grant(p, principal, "revoke", row["id"])
        await p.connection.execute(
            db.contact_links.update()
            .where(db.contact_links.c.id == row["id"])
            .values(status="revoked", decision_seq=decision.audit_id)
        )
        return {"ok": True}
    raise ValueError("Unsupported contact operation")


async def guess(
    p: Pipeline, principal: Principal, case_id: str, value: str
) -> dict[str, Any]:
    member = await p.requester(principal)
    case = await p.connection.scalar(
        sa.select(db.verification_cases.c.document).where(
            p.scope(db.verification_cases),
            db.verification_cases.c.id == case_id,
            db.verification_cases.c.member_id == UUID(str(member.member_id)),
        )
    )
    if not case or not case["subject"]["contact_id"]:
        raise ValueError("Private case unavailable")
    contact_id = UUID(case["subject"]["contact_id"])
    if await p.repo.get("trusted_contacts", {"id": contact_id}) is None:
        raise ValueError("Contact unavailable")
    stored = (
        (
            await p.connection.execute(
                sa.select(db.contact_secrets)
                .where(
                    p.scope(db.contact_secrets),
                    db.contact_secrets.c.contact_id == contact_id,
                )
                .with_for_update()
            )
        )
        .mappings()
        .one_or_none()
    )
    if not stored or not stored["word_hash"]:
        raise ValueError("Ask the owner to reset this safe word")
    cutoff = (contact_time(p) - timedelta(minutes=15)).isoformat()
    guesses = [at for at in stored["guesses"] if at > cutoff]
    if len(guesses) >= 5:
        return {
            "limited": True,
            "message": "Five attempts used. Try again after fifteen minutes.",
        }
    decision = await grant(p, principal, "guess", case_id)
    guesses.append(contact_time(p).isoformat())
    await p.connection.execute(
        db.contact_secrets.update()
        .where(
            p.scope(db.contact_secrets),
            db.contact_secrets.c.contact_id == contact_id,
        )
        .values(guesses=guesses, decision_seq=decision.audit_id)
    )
    try:
        matched = await asyncio.to_thread(check_word, value, stored["word_hash"])
    except ValueError:
        matched = False
    return {
        "matches": matched,
        "message": "Supporting evidence only. This does not verify the request or authorize an action.",
    }


def bound(config: Config, value: Command, binding: str) -> None:
    if not hmac.compare_digest(config.binding(value.model_dump_json()), binding):
        raise ValueError("The reviewed contact operation changed")
