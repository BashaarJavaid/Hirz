"""Only actual dialogue enters memory; cards and cancelled speech do not."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp import types

from hirz.host import simulator
from hirz.host.memory import Suggestion
from hirz.host.simulator import Echo
from tests.unit.test_simulator import host


@pytest.mark.parametrize(
    "quote,value,valid",
    [
        ("I prefer 72°F.", 72, True),
        ("I prefer 72.5 degrees Fahrenheit.", 72.5, True),
        ("I prefer 72°F.", 75, False),
        ("I prefer 72 degrees.", 72, False),
        ("I prefer 22°C.", 71.6, False),
        ("I prefer 172°F.", 72, False),
    ],
)
def test_suggestion_preserves_explicit_source_value(quote, value, valid):
    suggestion = Suggestion(value=value, confidence=0.9, quote=quote)
    if valid:
        assert suggestion.candidate(quote).value == value
    else:
        with pytest.raises(ValueError, match="Fahrenheit evidence"):
            suggestion.candidate(quote)
    with pytest.raises(ValueError):
        suggestion.candidate("Unrelated message")


@pytest.mark.parametrize("case", ["normal", "card", "cancel", "outage"])
def test_actual_turns_and_advisory_failure(tmp_path, monkeypatch, caplog, case):
    async def run():
        service = host(tmp_path)
        _, browser = service.browser(None, create=True)
        echo = browser.echoes["malik"]
        echo.oauth = SimpleNamespace(token=AsyncMock(return_value="private-bearer"))
        service.memory = AsyncMock(
            side_effect=RuntimeError("private-bearer and private dialogue")
            if case == "outage"
            else None
        )
        calls = []

        class Client:
            async def list_tools(self):
                return types.ListToolsResult(
                    tools=[types.Tool(name="what_can_you_do", inputSchema={})]
                )

            async def call_tool(self, name, args):
                calls.append(name)
                if case == "cancel":
                    browser.cancel()
                return types.CallToolResult(
                    content=[types.TextContent(type="text", text="Ready.")],
                    structuredContent={"speakable": {"headline": "Ready."}},
                )

        @asynccontextmanager
        async def connected(*args, **kwargs):
            yield Client()

        monkeypatch.setattr(simulator, "connect_mcp", connected)
        await service.turn(
            browser,
            "What can you do?",
            account="malik",
            model="scripted",
            selected=("what_can_you_do", {}) if case == "card" else None,
        )
        assert calls == ["what_can_you_do"]
        recorded = [call.args[1] for call in service.memory.await_args_list]
        assert [(turn.role, turn.text) for turn in recorded] == (
            []
            if case == "card"
            else [("user", "What can you do?")]
            if case == "cancel"
            else [("user", "What can you do?"), ("assistant", "Ready.")]
        )
        assert all(turn.session_id == echo.memory_session for turn in recorded)
        assert echo.memory_session != browser.echoes["dad"].memory_session
        assert Echo().memory_session != echo.memory_session
        assert "private-bearer" not in caplog.text
        assert "private dialogue" not in caplog.text
        assert not any(event["kind"] == "error" for event in echo.events)

    asyncio.run(run())


def test_prompt_is_actual_dialogue_and_cancel_is_not_invented_speech(tmp_path):
    async def run():
        service = host(tmp_path)
        _, browser = service.browser(None, create=True)
        echo = browser.echoes["malik"]
        echo.oauth = SimpleNamespace(token=AsyncMock(return_value="private-bearer"))
        service.memory = AsyncMock()
        pending = asyncio.create_task(
            service.ask(browser, echo, 0, "Which room?", {}, kind="elicitation")
        )
        await asyncio.sleep(0)
        browser.cancel()
        assert await pending == {"action": "cancel"}
        assert service.memory.await_count == 1
        assert service.memory.await_args.args[1].text == "Which room?"
        assert service.memory.await_args.args[1].role == "assistant"
        await service.say(echo, 0, "Suppressed after cancellation")
        assert service.memory.await_count == 1

    asyncio.run(run())


@pytest.mark.parametrize("failure", [False, True, "cancel"])
def test_selected_suggestion_stays_pending_without_mcp_execution(
    tmp_path, monkeypatch, caplog, failure
):
    from unittest.mock import Mock
    from uuid import uuid4

    from hirz.graph.models import now
    from hirz.host import selection
    from hirz.memory.models import Session, Turn
    from tests.unit.test_pipeline import HOME, ident

    async def run():
        service = host(tmp_path)
        _, browser = service.browser(None, create=True)
        echo = browser.echoes["malik"]
        echo.oauth = SimpleNamespace(
            token=AsyncMock(return_value="fresh-private-token")
        )
        source = Turn(
            id=uuid4(),
            session=Session(
                household_id=HOME,
                member_id=ident("members", "malik"),
                surface="alexa",
                session_id=echo.memory_session,
            ),
            session_id=echo.memory_session,
            role="user",
            text="I prefer 72°F.",
            sequence=1,
            recorded_at=now(),
            decision_seq=1,
        )
        service.memory = AsyncMock(return_value=source)
        service.suggest = AsyncMock(
            side_effect=RuntimeError("private dialogue and token")
            if failure is True
            else None
        )
        client = SimpleNamespace(
            list_tools=AsyncMock(return_value=types.ListToolsResult(tools=[])),
            call_tool=AsyncMock(),
        )

        @asynccontextmanager
        async def connected(*args, **kwargs):
            yield client

        monkeypatch.setattr(simulator, "connect_mcp", connected)
        raw = {"value": 72, "confidence": 0.9, "quote": source.text}
        choices = iter([([("suggest_temperature_preference", raw)], ""), ([], "")])

        def choose(*args, **kwargs):
            if failure == "cancel":
                browser.cancel()
            return next(choices)

        select = Mock(side_effect=choose)
        monkeypatch.setattr(selection, "select", select)
        receipt = Mock()
        monkeypatch.setattr(selection, "complete_selection", receipt)
        await service.turn(browser, source.text, account="malik", model="nova")
        if failure == "cancel":
            service.suggest.assert_not_awaited()
            assert not any(e["kind"] == "speech" for e in echo.events)
            client.call_tool.assert_not_awaited()
            return
        service.suggest.assert_awaited_once_with(
            "fresh-private-token", source, Suggestion(**raw)
        )
        assert [c.kwargs["memory"] for c in select.call_args_list] == [True, False]
        assert receipt.call_args.kwargs["error"] == failure
        client.call_tool.assert_not_awaited()
        speech = [e["text"] for e in echo.events if e["kind"] == "speech"]
        assert len(speech) == 1
        assert ("couldn't save" if failure else "only if you accept") in speech[0]
        assert "private dialogue" not in caplog.text
        assert "fresh-private-token" not in caplog.text

    asyncio.run(run())
