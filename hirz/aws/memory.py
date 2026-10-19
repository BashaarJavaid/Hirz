"""Advisory AgentCore mirror; Postgres and consented graph preferences retain authority."""

from collections.abc import AsyncIterator
from hashlib import sha256
from typing import Any

from hirz.aws import client as aws_client
from hirz.aws.client import call
from hirz.memory.models import Page, Session, Turn
from hirz.memory.provider import Hint


def scope(session: Session) -> dict[str, str]:
    session = Session.model_validate(session.model_dump())
    return {
        "actorId": session.household_id.hex + "_" + session.member_id.hex,
        "sessionId": sha256(
            (session.surface + ":" + session.session_id).encode()
        ).hexdigest(),
    }


class AgentCoreMemory:
    def __init__(self, memory_id: str) -> None:
        if not memory_id:
            raise ValueError("Configure an AgentCore Memory identifier")
        self.memory_id = memory_id
        self.sdk: Any = None

    async def _call(self, method: str, **kwargs: Any) -> Any:
        if self.sdk is None:
            self.sdk = await call(aws_client, "client", service="bedrock-agentcore")
        return await call(self.sdk, method, memoryId=self.memory_id, **kwargs)

    def _turn(self, event: dict[str, Any], session: Session) -> Turn:
        if any(
            event.get(k) != v
            for k, v in {"memoryId": self.memory_id, **scope(session)}.items()
        ):
            raise ValueError("Memory event scope mismatch")
        payload = event["payload"]
        if (
            len(payload) != 2
            or set(payload[0]) != {"conversational"}
            or set(payload[1]) != {"blob"}
        ):
            raise ValueError("Unexpected memory event payload")
        turn = Turn.model_validate(payload[1]["blob"])
        if turn.session != session or payload[0]["conversational"] != {
            "role": turn.role.upper(),
            "content": {"text": turn.text},
        }:
            raise ValueError("Memory turn content mismatch")
        return turn

    async def append(self, turn: Turn, *, extract: bool = False) -> None:
        turn = Turn.model_validate(turn.model_dump())
        # Blob preserves the canonical private Turn without extracting its IDs.
        # https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/short-term-create-event.html
        response = await self._call(
            "create_event",
            **scope(turn.session),
            eventTimestamp=turn.recorded_at,
            clientToken=str(turn.id),
            payload=[
                {
                    "conversational": {
                        "role": turn.role.upper(),
                        "content": {"text": turn.text},
                    }
                },
                {"blob": turn.model_dump(mode="json")},
            ],
            **({} if extract else {"extractionMode": "SKIP"}),
        )
        if self._turn(response["event"], turn.session) != turn:
            raise ValueError("Memory append content mismatch")

    async def _pages(
        self, method: str, key: str, **kwargs: Any
    ) -> AsyncIterator[dict[str, Any]]:
        tokens: set[str] = set()
        # shortcut: bound each advisory scan to 1,000 records; use an indexed
        # mirror cursor if long sessions exceed this, while Postgres stays readable.
        for _ in range(10):
            result = await self._call(method, maxResults=100, **kwargs)
            rows = result[key]
            if not isinstance(rows, list) or len(rows) > 100:
                raise ValueError("Invalid Memory page")
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError("Invalid Memory record")
                yield row
            token = result.get("nextToken")
            if token is None:
                return
            if not isinstance(token, str) or not token or token in tokens:
                raise ValueError("Invalid Memory pagination")
            tokens.add(token)
            kwargs["nextToken"] = token
        raise ValueError("Memory scan limit exceeded")

    async def turns(self, session: Session, page: Page = Page()) -> tuple[Turn, ...]:
        page = Page.model_validate(page.model_dump())
        rows: dict[int, Turn] = {}
        async for event in self._pages(
            "list_events", "events", **scope(session), includePayloads=True
        ):
            turn = self._turn(event, session)
            if turn.sequence in rows and rows[turn.sequence] != turn:
                raise ValueError("Memory turn sequence conflict")
            rows[turn.sequence] = turn
        return tuple(rows[i] for i in sorted(rows) if i > page.after)[: page.limit]

    async def hints(self, session: Session) -> tuple[Hint, ...]:
        actor = scope(session)["actorId"]
        hints = []
        for strategy in ("preferences", "semantic"):
            namespace = f"/hirz/{actor}/{strategy}/"
            async for record in self._pages(
                "list_memory_records", "memoryRecordSummaries", namespace=namespace
            ):
                if record.get("namespaces") != [namespace]:
                    raise ValueError("Memory hint namespace mismatch")
                hints.append(Hint(session=session, text=record["content"]["text"]))
        return tuple(hints)
