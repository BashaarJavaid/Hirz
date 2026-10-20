"""Only actual dialogue enters memory; cards and cancelled speech do not."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from mcp import types

from hirz.host import simulator
from hirz.host.simulator import Echo
from tests.unit.test_simulator import host


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
