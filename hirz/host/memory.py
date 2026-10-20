"""Actual Simulator dialogue, attributed by its freshly verified linked account."""

from uuid import uuid4

from hirz.companion.api import Companion
from hirz.mcp.auth import KeyCache
from hirz.memory.models import TurnInput
from hirz.memory.service import MemoryService


async def record(
    service: Companion, verifier: KeyCache, token: str, turn: TurnInput
) -> None:
    access = await verifier.verify_token(token)
    if access is None or "hirz:plan" not in access.scopes:
        raise ValueError("Conversation memory requires a current planning login")
    async with service.engine.begin() as connection:
        identity = await verifier.identity(connection, access)
    if identity is None or identity.member.member_id is None:
        raise ValueError("Conversation memory requires a linked member")
    async with service.pipeline(identity.household_id) as pipeline:
        result = await MemoryService(pipeline).record_turn(
            identity.principal,
            action_id="simulator-memory:" + uuid4().hex,
            turn=turn,
        )
        if result.record is None:
            raise ValueError("Conversation memory was refused")
