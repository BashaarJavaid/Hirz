"""Memory mutations participate in the existing Pipeline grant transaction."""

from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID, uuid5

import sqlalchemy as sa
from pydantic import Field

from hirz import db
from hirz.executor.plans import governance
from hirz.graph.models import Model, Preference
from hirz.memory.models import (
    Candidate,
    MutationResult,
    Page,
    Proposal,
    References,
    Session,
    Turn,
    TurnInput,
)
from hirz.memory.provider import Hint, InProcessMemory, MemoryProvider
from hirz.pipeline.hashing import digest
from hirz.pipeline.models import Action, Decision, EventType, Principal
from hirz.planner.coordinator import Clarification

if TYPE_CHECKING:
    from hirz.pipeline.service import Pipeline


class Command(Model):
    operation: Literal["append_turn", "propose", "accept", "reject"]
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_turn: UUID | None = None
    candidate: Candidate | None = None
    proposal_id: UUID | None = None


def turn_record(row: dict[str, Any]) -> Turn:
    return Turn.model_validate(
        {
            **{
                k: v
                for k, v in row.items()
                if k not in {"household_id", "member_id", "surface"}
            },
            "session": {
                k: row[k]
                for k in ("household_id", "member_id", "surface", "session_id")
            },
        }
    )


def session_scope(session: Session) -> sa.ColumnElement[bool]:
    return sa.and_(
        *(db.session_turns.c[k] == v for k, v in session.model_dump().items())
    )


async def scoped_row(
    p: "Pipeline", table: sa.Table, ident: UUID, member: UUID
) -> dict[str, Any]:
    row = (
        (
            await p.connection.execute(
                sa.select(table).where(
                    p.scope(table),
                    table.c.id == ident,
                    table.c.member_id == member,
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise Clarification("Memory is unavailable for this linked member.")
    return dict(row)


async def preference(p: "Pipeline", member: UUID) -> dict[str, Any] | None:
    rows = (
        (
            await p.connection.execute(
                sa.select(db.preferences).where(
                    p.scope(db.preferences),
                    db.preferences.c.member_id == member,
                    db.preferences.c.attributes["scope"].astext == "member",
                    db.preferences.c.attributes["key"].astext == "temperature_target_f",
                )
            )
        )
        .mappings()
        .all()
    )
    if len(rows) > 1:
        raise Clarification("Multiple matching preferences require clarification.")
    return dict(rows[0]) if rows else None


async def reference(p: "Pipeline", kind: str, ident: str) -> str:
    if kind == "verification_case":
        raise Clarification("Verification-case context is not available yet.")
    if kind not in {"plan", "action"}:
        raise Clarification("Unknown reference kind.")
    table = db.plans if kind == "plan" else db.actions
    column = table.c.plan_id if kind == "plan" else table.c.action_id
    row = (
        (
            await p.connection.execute(
                sa.select(table).where(p.scope(table), column == ident)
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise Clarification(
            "The referenced object is unavailable; please identify it again."
        )
    if kind == "plan":
        if row["document"]["status"] not in {
            "proposed",
            "approved",
            "active",
            "awaiting_approval",
        }:
            raise Clarification("The referenced plan is no longer current.")
        if p.clock() >= datetime.fromisoformat(
            row["document"]["horizon"]["end"].replace("Z", "+00:00")
        ):
            raise Clarification("The referenced plan has ended.")
    elif row["execution_status"] in {
        "cancelled",
        "skipped",
        "failed",
        "held",
        "verified",
    }:
        raise Clarification("The referenced action is no longer current.")
    return ident


async def prepare(p: "Pipeline", action: Action, principal: Principal) -> Command:
    command = Command.model_validate(action.params)
    member = await p.requester(principal)
    if (
        member.member_id is None
        or principal.surface == "scheduler"
        or action.scheduled_for is not None
    ):
        raise Clarification("Memory requires an immediate linked-member request.")
    subject = UUID(member.member_id)
    if command.operation == "append_turn":
        if command.source_turn or command.candidate or command.proposal_id:
            raise ValueError("Unexpected turn arguments")
        private = p._memory_turn
        if (
            private is None
            or digest(private.model_dump(mode="json")) != command.content_hash
        ):
            raise ValueError("Private turn content does not match the action")
        TurnInput.model_validate(private.model_dump())
        for kind, ident in private.references.model_dump().items():
            if ident is not None and kind != "verification_case":
                await reference(p, kind, ident)
    elif command.operation == "propose":
        if not command.source_turn or not command.candidate or command.proposal_id:
            raise ValueError("A typed candidate and source turn are required")
        if p.bundle.policy().learning.accept_memory_proposals == "never":
            raise ValueError("Learning is disabled")
        await scoped_row(p, db.session_turns, command.source_turn, subject)
        await preference(p, subject)
        if command.content_hash != digest(
            {
                "source_turn": str(command.source_turn),
                "candidate": command.candidate.model_dump(mode="json"),
            }
        ):
            raise ValueError("Candidate content mismatch")
    else:
        if not command.proposal_id or command.source_turn or command.candidate:
            raise ValueError("Only a proposal identity is accepted for review")
        if principal.surface != "app":
            raise ValueError("Only the subject member's app may review memory")
        proposal = Proposal.model_validate(
            await scoped_row(p, db.memory_proposals, command.proposal_id, subject)
        )
        if proposal.status != "pending":
            raise ValueError("Proposal already reviewed")
        if command.content_hash != digest(
            {"proposal_id": str(command.proposal_id), "operation": command.operation}
        ):
            raise ValueError("Review content mismatch")
        if command.operation == "accept":
            if p.bundle.policy().learning.accept_memory_proposals == "never":
                raise ValueError("Learning is disabled")
            current = await preference(p, subject)
            if (
                current["id"] if current else None,
                current["valid_from"] if current else None,
            ) != (proposal.preference_id, proposal.preference_version):
                raise ValueError("Preference changed; a new proposal is required")
    return command


async def commit(
    p: "Pipeline", action: Action, decision: Decision, principal: Principal
) -> None:
    command = await prepare(p, action, principal)
    assert decision.audit_id is not None and action.requested_by.member_id is not None
    member = UUID(action.requested_by.member_id)
    ident = uuid5(p.household_id, "memory:" + action.action_id)
    at = p.clock()
    if command.operation == "append_turn":
        private = p._memory_turn
        assert private is not None
        session = Session(
            household_id=p.household_id,
            member_id=member,
            surface=principal.surface,
            session_id=private.session_id,
        )
        last = await p.connection.scalar(
            sa.select(sa.func.max(db.session_turns.c.sequence)).where(
                session_scope(session)
            )
        )
        await p.connection.execute(
            db.session_turns.insert().values(
                **session.model_dump(),
                id=ident,
                sequence=(last or 0) + 1,
                role=private.role,
                text=private.text,
                references=private.references.model_dump(),
                recorded_at=at,
                decision_seq=decision.audit_id,
            )
        )
        return
    event = {
        "propose": EventType.MEMORY_PROPOSED,
        "accept": EventType.MEMORY_ACCEPTED,
        "reject": EventType.MEMORY_REJECTED,
    }[command.operation]
    seq = await p.audit.append(
        p.connection,
        p.household_id,
        at,
        event,
        {
            "action_id": action.action_id,
            "decision_seq": decision.audit_id,
            "proposal_id": str(
                ident if command.operation == "propose" else command.proposal_id
            ),
            "member_id": str(member),
            "content_hash": command.content_hash,
        },
    )
    if command.operation == "propose":
        current = await preference(p, member)
        assert command.candidate is not None
        await p.connection.execute(
            db.memory_proposals.insert().values(
                household_id=p.household_id,
                id=ident,
                member_id=member,
                source_turn=command.source_turn,
                candidate=command.candidate.model_dump(mode="json"),
                preference_id=current["id"] if current else None,
                preference_version=current["valid_from"] if current else None,
                status="pending",
                created_at=at,
                decision_seq=decision.audit_id,
                audit_seq=seq,
            )
        )
        return
    assert command.proposal_id is not None
    proposal = Proposal.model_validate(
        await scoped_row(p, db.memory_proposals, command.proposal_id, member)
    )
    if command.operation == "accept":
        await p.repo.put(
            "preferences",
            Preference(
                household_id=p.household_id,
                id=proposal.preference_id or proposal.id,
                member_id=member,
                scope="member",
                source="learned_accepted",
                **proposal.candidate.model_dump(),
            ),
            expected_version=proposal.preference_version,
        )
        from hirz.executor.refresh import invalidate_all

        await invalidate_all(
            p,
            "Accepted memory preference " + str(proposal.id),
            decision=decision.audit_id,
        )
    await p.connection.execute(
        db.memory_proposals.update()
        .where(
            p.scope(db.memory_proposals),
            db.memory_proposals.c.id == proposal.id,
        )
        .values(
            status="accepted" if command.operation == "accept" else "rejected",
            review_seq=seq,
        )
    )


class MemoryService:
    def __init__(self, pipeline: "Pipeline", provider: MemoryProvider | None = None):
        self.pipeline = pipeline
        self.provider = provider if provider is not None else InProcessMemory()

    async def session(self, principal: Principal, session_id: str) -> Session:
        member = await self.pipeline.requester(principal)
        if member.member_id is None or principal.surface == "scheduler":
            raise Clarification("A linked member session is required.")
        return Session(
            household_id=self.pipeline.household_id,
            member_id=UUID(member.member_id),
            surface=principal.surface,
            session_id=session_id,
        )

    async def record_turn(
        self, principal: Principal, *, action_id: str, turn: TurnInput
    ) -> MutationResult:
        turn = TurnInput.model_validate(turn.model_dump())
        p = self.pipeline
        if p._memory_turn is not None:
            raise ValueError("Overlapping memory commands")
        p._memory_turn = turn
        try:
            result = await self.mutate(
                principal,
                action_id,
                Command(
                    operation="append_turn",
                    content_hash=digest(turn.model_dump(mode="json")),
                ),
            )
        finally:
            p._memory_turn = None
        if isinstance(result.record, Turn):
            try:
                await self.provider.append(result.record)
            except Exception:
                pass  # Advisory mirror; committed Postgres remains authoritative.
        return result

    async def propose(
        self,
        principal: Principal,
        *,
        action_id: str,
        source_turn: UUID,
        candidate: Candidate,
    ) -> MutationResult:
        candidate = Candidate.model_validate(candidate.model_dump())
        return await self.mutate(
            principal,
            action_id,
            Command(
                operation="propose",
                source_turn=source_turn,
                candidate=candidate,
                content_hash=digest(
                    {
                        "source_turn": str(source_turn),
                        "candidate": candidate.model_dump(mode="json"),
                    }
                ),
            ),
        )

    async def review(
        self, principal: Principal, *, action_id: str, proposal_id: UUID, accept: bool
    ) -> MutationResult:
        if type(accept) is not bool:
            raise ValueError("Review requires an explicit boolean")
        operation: Literal["accept", "reject"] = "accept" if accept else "reject"
        return await self.mutate(
            principal,
            action_id,
            Command(
                operation=operation,
                proposal_id=proposal_id,
                content_hash=digest(
                    {"proposal_id": str(proposal_id), "operation": operation}
                ),
            ),
        )

    async def mutate(
        self, principal: Principal, action_id: str, command: Command
    ) -> MutationResult:
        p = self.pipeline
        decision = await p.redeem(
            governance(
                p, "memory", command.model_dump(mode="json"), principal, action_id
            ),
            principal,
        )
        record: Turn | Proposal | None = None
        if decision.decision == "execute":
            async with p.connection.begin():
                member = (await p.requester(principal)).member_id
                assert member is not None
                ident = command.proposal_id or uuid5(
                    p.household_id, "memory:" + action_id
                )
                row = await scoped_row(
                    p,
                    db.session_turns
                    if command.operation == "append_turn"
                    else db.memory_proposals,
                    ident,
                    UUID(member),
                )
                record = (
                    turn_record(row)
                    if command.operation == "append_turn"
                    else Proposal.model_validate(row)
                )
        return MutationResult(decision=decision, record=record)

    async def turns(
        self, principal: Principal, session_id: str, page: Page = Page()
    ) -> tuple[Turn, ...]:
        page = Page.model_validate(page.model_dump())
        p = self.pipeline
        async with p.connection.begin():
            session = await self.session(principal, session_id)
            rows = (
                await p.connection.execute(
                    sa.select(db.session_turns)
                    .where(
                        session_scope(session), db.session_turns.c.sequence > page.after
                    )
                    .order_by(db.session_turns.c.sequence)
                    .limit(page.limit)
                )
            ).mappings()
            return tuple(turn_record(dict(r)) for r in rows)

    async def hints(self, principal: Principal, session_id: str) -> tuple[Hint, ...]:
        async with self.pipeline.connection.begin():
            session = await self.session(principal, session_id)
        try:
            return tuple(
                Hint.model_validate(h.model_dump())
                for h in await self.provider.hints(session)
                if h.session == session
            )
        except Exception:
            return ()

    async def proposals(
        self, principal: Principal, *, pending_only: bool = True, page: Page = Page()
    ) -> tuple[Proposal, ...]:
        page = Page.model_validate(page.model_dump())
        p = self.pipeline
        async with p.connection.begin():
            session = await self.session(principal, "proposal-list")
            query = sa.select(db.memory_proposals).where(
                p.scope(db.memory_proposals),
                db.memory_proposals.c.member_id == session.member_id,
                db.memory_proposals.c.audit_seq > page.after,
            )
            if pending_only:
                query = query.where(db.memory_proposals.c.status == "pending")
            return tuple(
                Proposal.model_validate(dict(r))
                for r in (
                    await p.connection.execute(
                        query.order_by(db.memory_proposals.c.audit_seq).limit(
                            page.limit
                        )
                    )
                ).mappings()
            )

    async def resolve(
        self,
        principal: Principal,
        session_id: str,
        kind: Literal["plan", "action", "verification_case"],
    ) -> str:
        if kind not in References.model_fields:
            raise Clarification("Unknown reference kind.")
        p = self.pipeline
        try:
            async with p.connection.begin():
                session = await self.session(principal, session_id)
                value = db.session_turns.c.references[kind].astext
                ident = await p.connection.scalar(
                    sa.select(value)
                    .where(session_scope(session), value.is_not(None))
                    .order_by(db.session_turns.c.sequence.desc())
                    .limit(1)
                )
                if ident is None:
                    raise Clarification("Please identify the object for this session.")
                return await reference(p, kind, ident)
        except sa.exc.DBAPIError:
            raise Clarification(
                "Session context is unavailable; please identify the object again."
            ) from None
