"""Actor/session isolation compatible with AgentCore; local recorded hints only."""

from typing import Protocol

from pydantic import Field

from hirz.graph.models import Model
from hirz.memory.models import Page, Session, Turn


class Hint(Model):
    session: Session
    text: str = Field(min_length=1, max_length=8000)


class MemoryProvider(Protocol):
    async def append(self, turn: Turn) -> None: ...
    async def turns(
        self, session: Session, page: Page = Page()
    ) -> tuple[Turn, ...]: ...
    async def hints(self, session: Session) -> tuple[Hint, ...]: ...


class InProcessMemory:
    def __init__(self, hints: tuple[Hint, ...] = ()):
        self._turns: dict[Session, dict[int, Turn]] = {}
        self._hints = tuple(Hint.model_validate(h.model_dump()) for h in hints)

    async def append(self, turn: Turn) -> None:
        turn = Turn.model_validate(turn.model_dump())
        rows = self._turns.setdefault(turn.session, {})
        old = rows.get(turn.sequence)
        if old is not None and old != turn:
            raise ValueError("Turn sequence content mismatch")
        rows[turn.sequence] = turn

    async def turns(self, session: Session, page: Page = Page()) -> tuple[Turn, ...]:
        page = Page.model_validate(page.model_dump())
        rows = self._turns.get(session, {})
        return tuple(rows[i] for i in sorted(rows) if i > page.after)[: page.limit]

    async def hints(self, session: Session) -> tuple[Hint, ...]:
        return tuple(h for h in self._hints if h.session == session)
