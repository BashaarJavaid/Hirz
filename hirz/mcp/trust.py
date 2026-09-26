"""Approved bounded advisory signals and private simulated contact checks."""

import re
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Literal
from uuid import UUID, uuid4

import sqlalchemy as sa

from hirz import db
from hirz.graph.context import ContextSnapshot
from hirz.mcp.contracts import Result, RiskInput, VerifyInput, response
from hirz.mcp.persistence import command
from hirz.pipeline.hashing import action_hash
from hirz.pipeline.models import (
    Action,
    Principal,
    Requester,
    Target,
    VerificationCase,
    VerificationClaim,
    VerificationSignal,
    VerificationState,
    VerificationSubject,
)
from hirz.pipeline.service import Pipeline
from hirz.planner.coordinator import Clarification
from hirz.risk import RiskBand
from hirz.twin.people import ContactScript
from hirz.twin.world import TwinWorld

# Approved 2026-09-23. Advisory only; never supplies execution's trusted scam flag.
PHRASES: dict[str, tuple[int, tuple[str, ...]]] = {
    "financial_or_access_request": (
        2,
        (
            "send money",
            "pay money",
            "transfer money",
            "wire money",
            "dollars",
            "gift cards",
            "bank details",
            "password",
            "verification code",
            "unlock the door",
            "open the door",
        ),
    ),
    "unfamiliar_channel_reported": (
        2,
        ("strange number", "new number", "unknown number", "different number"),
    ),
    "secrecy": (2, ("keep this secret", "don't tell anyone")),
    "third_party_recipient": (
        2,
        ("courier", "someone collecting money", "another person's account"),
    ),
    "urgency_language": (1, ("urgent", "immediately", "right now")),
    "claimed_authority": (1, ("police", "government", "bank", "irs")),
}


def signals(text: str) -> tuple[VerificationSignal, ...]:
    found = []
    for name, (weight, phrases) in PHRASES.items():
        matched = False
        for clause in re.split(r"[.!?;,\n]", text.casefold().replace("’", "'")):
            for phrase in phrases:
                for match in re.finditer(r"\b" + re.escape(phrase) + r"\b", clause):
                    prefix = re.findall(r"[a-z']+", clause[: match.start()])[-3:]
                    if phrase == "don't tell anyone" or not {
                        "no",
                        "not",
                        "never",
                    }.intersection(prefix):
                        matched = True
        if matched:
            found.append(
                VerificationSignal.model_validate(dict(signal=name, weight=weight))
            )
    return tuple(found)


def phone(text: str) -> str:
    if not re.fullmatch(r"\+?[0-9 ().-]+", text):
        raise ValueError("Provide a phone number without extensions or letters.")
    digits = re.sub(r"[ ().-]", "", text)
    if digits.startswith("+"):
        if not 8 <= len(digits) - 1 <= 15:
            raise ValueError("International numbers need eight through fifteen digits.")
        return digits
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    raise ValueError("International numbers require an explicit plus country code.")


def band(found: tuple[VerificationSignal, ...]) -> RiskBand:
    score = sum(s.weight for s in found)
    return (
        RiskBand.LOW
        if score == 0
        else RiskBand.MEDIUM
        if score <= 2
        else RiskBand.HIGH
        if score <= 4
        else RiskBand.CRITICAL
    )


async def assess(
    p: Pipeline, principal: Principal, args: RiskInput, snapshot: ContextSnapshot
) -> Result:
    contacts = [
        r
        for r in snapshot.data["trusted_contacts"]
        if str(r["display_name"]).casefold() == args.claimed_party.casefold()
        or str(r["id"]) == args.claimed_party
    ]
    contact = contacts[0] if len(contacts) == 1 and args.party == "person" else None
    comparison: (
        Literal["matches", "does_not_match", "insufficient_information"] | None
    ) = None
    if args.presented_number:
        normalized = phone(args.presented_number)
        comparison = "insufficient_information"
        if contact:
            channels = (
                (
                    await p.connection.execute(
                        sa.select(db.contact_channels.c.attributes).where(
                            p.scope(db.contact_channels),
                            db.contact_channels.c.contact_id
                            == UUID(str(contact["id"])),
                        )
                    )
                )
                .scalars()
                .all()
            )
            hashes = [
                c["value_hash"]
                for c in channels
                if c.get("kind") == "phone"
                and c.get("verified_at")
                and datetime.fromisoformat(c["verified_at"]) <= p.clock()
            ]
            if hashes:
                comparison = (
                    "matches"
                    if sha256(normalized.encode()).hexdigest() in hashes
                    else "does_not_match"
                )
    found = signals(args.text)
    risk = band(found)
    speech = response(
        "This request has warning signs. Check with your trusted contact before acting."
        if found
        else "I found no listed warning signs. A trusted-contact check is still available.",
        details=(),
        options=("Check with a trusted contact",),
    )
    if args.party == "organization":
        speech = response(
            "There is insufficient information to verify this organization in the preview.",
            options=("Check with a trusted contact",),
        )
        comparison = "insufficient_information" if args.presented_number else None
    if comparison is not None:
        line = {
            "matches": "The supplied number matches a verified saved number; this does not establish identity.",
            "does_not_match": "The supplied number does not match a verified saved number.",
            "insufficient_information": "There is insufficient verified information to compare the supplied number.",
        }[comparison]
        speech = speech.model_copy(
            update={
                "speakable": speech.speakable.model_copy(update={"details": (line,)})
            }
        )
    case = VerificationCase(
        case_id=uuid4().hex,
        claim=VerificationClaim(text=args.text, presented_number=args.presented_number),
        subject=VerificationSubject(
            contact_id=str(contact["id"]) if contact else None,
            trusted=contact is not None,
            claimed_party=args.claimed_party,
            party=args.party,
        ),
        signals=found,
        risk_band=risk,
        recommended=("verify_via_verified_channel", "do_not_transfer")
        if found
        else ("verify_via_verified_channel",),
        number_comparison=comparison,
        speakable=speech.speakable.model_dump(mode="json"),
    )
    await command(
        p,
        "record_verification",
        {"operation": "assess", "case": case.model_dump(mode="json")},
        principal,
    )
    return Result.model_validate({"speakable": case.speakable, "data": {"case": case}})


def case_response(case: VerificationCase) -> Result:
    state = case.verification
    if state is None:
        return Result.model_validate(
            {"speakable": case.speakable, "data": {"case": case}}
        )
    headline = {
        "pending": "A simulated check is pending. Ask me again in a minute.",
        "genuine": "The simulated reply confirms this specific request. Talk to the contact using their saved number.",
        "not_genuine": "The simulated reply says they did not make this request. Do not send anything.",
        "will_call": "The simulated reply says the contact will call. No real call has been arranged.",
        "no_answer": "There was no simulated reply. Do not send anything; contact the person through a channel you trust.",
    }[state.status]
    if (
        state.status == "no_answer"
        and case.speakable.get("headline")
        == "The contact was removed. No reply will be accepted for this check."
    ):
        headline = str(case.speakable["headline"])
    return response(headline, source="twin", case=case)


async def verify(
    p: Pipeline, principal: Principal, args: VerifyInput, snapshot: ContextSnapshot
) -> Result:
    member = await p.requester(principal)
    query = sa.select(db.verification_cases).where(
        p.scope(db.verification_cases),
        db.verification_cases.c.member_id == UUID(str(member.member_id)),
    )
    if args.case_id:
        query = query.where(db.verification_cases.c.id == args.case_id)
    contact = None
    if args.contact:
        matches = [
            r
            for r in snapshot.data["trusted_contacts"]
            if str(r["id"]) == args.contact
            or str(r["display_name"]).casefold() == args.contact.casefold()
        ]
        if len(matches) != 1:
            raise Clarification("Please name one trusted household contact exactly.")
        contact = matches[0]
        query = query.where(
            db.verification_cases.c.document["subject"]["contact_id"].astext
            == str(contact["id"])
        )
    rows = (
        (
            await p.connection.execute(
                query.order_by(
                    db.verification_cases.c.created_at.desc(),
                    db.verification_cases.c.decision_seq.desc(),
                )
            )
        )
        .mappings()
        .all()
    )
    cases = [VerificationCase.model_validate(r["document"]) for r in rows]
    pending = [
        c for c in cases if c.verification and c.verification.status == "pending"
    ]
    if args.case_id and not cases:
        raise ValueError("That case is unavailable to this linked member.")
    if args.operation == "status":
        if len(pending) > 1:
            raise Clarification(
                "There are multiple pending checks. Choose the case you want to review."
            )
        selected = pending or [c for c in cases if c.verification]
        if args.case_id:
            selected = cases
        return (
            case_response(selected[0])
            if selected
            else response(
                "There is no contact check to report for this linked member.",
                status="unavailable",
            )
        )
    if args.case_id:
        case = cases[0]
        if case.verification:
            return case_response(case)
        if args.text is not None and args.text != case.claim.text:
            raise ValueError("Start a new assessment for a different request.")
    else:
        assert contact and args.text
        result = await assess(
            p,
            principal,
            RiskInput(
                text=args.text,
                claimed_party=str(contact["display_name"]),
                party="person",
                request_id=args.request_id or "",
            ),
            snapshot,
        )
        assert result.data.case
        case = result.data.case
    if not case.subject.contact_id or case.subject.party != "person":
        return response(
            "A verified simulated app channel is required for this preview's contact check.",
            status="unavailable",
            case=case,
        )
    channels = [
        r
        for r in snapshot.data["contact_channels"]
        if str(r["contact_id"]) == case.subject.contact_id
        and r["kind"] == "hirz_app"
        and r.get("verified_at")
        and datetime.fromisoformat(str(r["verified_at"])) <= p.clock()
        and r["source"] == "twin"
    ]
    if (
        not channels
        or "app_confirmation"
        not in p.bundle.policy().verification.trusted_contact_methods_order
    ):
        return response(
            "A verified simulated app channel is unavailable for this contact.",
            status="unavailable",
            case=case,
        )
    action = Action.model_validate(
        dict(
            action_id=uuid4().hex,
            **{"class": "communication.contact_trusted_contact"},
            target=Target(adapter="contacts", entity=case.subject.contact_id),
            params={},
            requested_by=Requester(
                member_id=None, role="unknown", surface=principal.surface
            ),
            reason="Explicit simulated app confirmation",
            content_hash="",
        )
    )
    action = action.model_copy(update={"content_hash": action_hash(action)})
    decision = await p.mutate_locked(action, principal)
    if decision.decision != "execute":
        return response(
            "The household rules have not permitted this contact check.",
            status="denied",
            decision=decision,
            case=case,
        )
    case = case.model_copy(
        update={
            "verification": VerificationState(
                status="pending",
                sent_to=case.subject.contact_id,
                started_at=p.clock(),
                expires_at=p.clock() + timedelta(minutes=2),
            )
        }
    )
    await command(
        p,
        "record_verification",
        {
            "operation": "start",
            "case": case.model_dump(mode="json"),
            "contact_decision": decision.audit_id,
        },
        principal,
    )
    return case_response(case)


async def advance(p: Pipeline, world: TwinWorld | None) -> None:
    async with p.repo.write(p.clock):
        rows = (
            (
                await p.connection.execute(
                    sa.select(db.verification_cases).where(
                        p.scope(db.verification_cases),
                        db.verification_cases.c.document["verification"][
                            "status"
                        ].astext
                        == "pending",
                    )
                )
            )
            .mappings()
            .all()
        )
        for row in rows:
            case = VerificationCase.model_validate(row["document"])
            state = case.verification
            assert state
            status = "no_answer" if p.clock() >= state.expires_at else "pending"
            if world and world.household.id == p.household_id:
                scripts = [
                    s
                    for s in world.config.contact_scripts
                    if str(s.contact_id) == state.sent_to
                ]
                if len(scripts) == 1:
                    original = scripts[0]
                    delay = (
                        original.reply_at - original.requested_at
                        if original.reply_at
                        else None
                    )
                    reply_at = state.started_at + delay if delay is not None else None
                    script = ContactScript(
                        contact_id=UUID(state.sent_to),
                        requested_at=state.started_at,
                        deadline=state.expires_at,
                        reply_at=reply_at
                        if reply_at and reply_at < state.expires_at
                        else None,
                        reply=original.reply
                        if reply_at and reply_at < state.expires_at
                        else "no_answer",
                    )
                    status = script.status(p.clock())
            if status != "pending":
                updated = VerificationState.model_validate(
                    state.model_dump() | {"status": status}
                )
                case = case.model_copy(update={"verification": updated})
                accounts = (
                    (
                        await p.connection.execute(
                            sa.select(db.member_accounts).where(
                                p.scope(db.member_accounts),
                                db.member_accounts.c.member_id == row["member_id"],
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
                if not accounts:
                    continue
                account = accounts[0]
                scheduler = Principal(
                    provider=account["provider"],
                    sub=account["sub"],
                    surface="scheduler",
                )
                await command(
                    p,
                    "record_verification",
                    {"operation": "finish", "case": case.model_dump(mode="json")},
                    scheduler,
                )
