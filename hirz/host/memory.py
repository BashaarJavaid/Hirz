"""Actual Simulator dialogue, attributed by its freshly verified linked account."""

import re
from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import Field

from hirz import db
from hirz.companion.api import Companion
from hirz.mcp.auth import Identity, KeyCache
from hirz.memory.models import Candidate, Proposal, Turn, TurnInput
from hirz.memory.service import MemoryService, scoped_row, turn_record
from hirz.pipeline.hashing import digest


class Suggestion(Candidate):
    quote: str = Field(min_length=1, max_length=8000)

    def candidate(self, text: str) -> Candidate:
        values = re.findall(
            r"(?<![\w.])(-?\d+(?:\.\d+)?)\s*(?:°\s*)?(?:degrees?\s*)?(?:Fahrenheit|F)\b",
            self.quote,
            re.IGNORECASE,
        )
        if self.quote not in text or Decimal(str(self.value)) not in {
            Decimal(value) for value in values
        }:
            raise ValueError("Temperature must match quoted Fahrenheit evidence")
        return Candidate.model_validate(self.model_dump(exclude={"quote"}))


async def identity(service: Companion, verifier: KeyCache, token: str) -> Identity:
    access = await verifier.verify_token(token)
    if access is None or "hirz:plan" not in access.scopes:
        raise ValueError("Conversation memory requires a current planning login")
    async with service.engine.begin() as connection:
        identity = await verifier.identity(connection, access)
    if identity is None or identity.member.member_id is None:
        raise ValueError("Conversation memory requires a linked member")
    return identity


async def record(
    service: Companion, verifier: KeyCache, token: str, turn: TurnInput
) -> Turn:
    linked = await identity(service, verifier, token)
    async with service.pipeline(linked.household_id) as pipeline:
        result = await MemoryService(pipeline).record_turn(
            linked.principal,
            action_id="simulator-memory:" + uuid4().hex,
            turn=turn,
        )
        if not isinstance(result.record, Turn):
            raise ValueError("Conversation memory was refused")
        return result.record


async def suggest(
    service: Companion,
    verifier: KeyCache,
    token: str,
    source: Turn,
    suggestion: Suggestion,
) -> None:
    suggestion = Suggestion.model_validate(suggestion.model_dump())
    linked = await identity(service, verifier, token)
    async with service.pipeline(linked.household_id) as pipeline:
        async with pipeline.connection.begin():
            stored = turn_record(
                await scoped_row(
                    pipeline,
                    db.session_turns,
                    source.id,
                    UUID(linked.member.member_id),
                )
            )
        if (
            stored != source
            or stored.role != "user"
            or stored.session.surface != linked.principal.surface
        ):
            raise ValueError("Preference source does not match the linked conversation")
        candidate = suggestion.candidate(stored.text)
        result = await MemoryService(pipeline).propose(
            linked.principal,
            action_id=f"simulator-proposal:{source.id}:{digest(candidate.model_dump())}",
            source_turn=stored.id,
            candidate=candidate,
        )
        if not isinstance(result.record, Proposal):
            raise ValueError("Temperature suggestion was refused")
