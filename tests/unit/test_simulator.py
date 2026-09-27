"""Simulator boundaries: no browser authority, exact prompts and aggregate spend."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from mcp import types

from hirz.host.api import router
from hirz.host.headless import Budget
from hirz.host.simulator import Simulator, recorded
from hirz.mcp.contracts import response
from hirz.mcp.elicitation import call, fields
from hirz.pipeline.confirmation import Review
from tests.unit.test_pipeline import PRINCIPAL, action


def host(tmp_path):
    return Simulator(
        origin="http://127.0.0.1:8000",
        mcp_url="http://127.0.0.1:8000/mcp",
        issuer="http://127.0.0.1:8001",
        ledger=tmp_path / "item29.json",
    )


def test_session_expiry_and_switch_cancellation(tmp_path):
    async def run():
        service = host(tmp_path)
        key, browser = service.browser(None, create=True)
        echo = browser.echoes["malik"]
        task = asyncio.create_task(
            service.ask(browser, echo, 0, "Confirm", {}, kind="commitment")
        )
        await asyncio.sleep(0)
        old = echo.prompt["id"]
        browser.cancel()
        browser.account = "dad"
        assert await task == {"action": "cancel"}
        assert old and echo.prompt is None and echo.generation == 1
        assert browser.echoes["dad"].history == []
        touched = browser.touched
        service.browser(key, touch=False)
        assert browser.touched == touched
        browser.touched -= 1800
        with pytest.raises(ValueError):
            service.browser(key)
        key, browser = service.browser(None, create=True)
        browser.created -= 43200
        with pytest.raises(ValueError):
            service.browser(key)

    asyncio.run(run())


def test_protocol_result_omits_null_optional_fields():
    result = types.CallToolResult(
        content=[types.TextContent(type="text", text="Ready")],
        structuredContent={"data": {"status": "ok"}},
    )
    wire = result.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert wire["content"] == [{"type": "text", "text": "Ready"}]
    assert "_meta" not in wire


@pytest.mark.parametrize("failure", ["timeout", "invalid", "revoked", "disconnect"])
def test_elicitation_stops_before_execution(failure):
    async def run():
        executed = []

        async def elicit(*args, **kwargs):
            if failure == "timeout":
                raise TimeoutError
            if failure == "disconnect":
                raise ConnectionError("Elicitation transport disconnected")
            return types.ElicitResult(
                action="accept", content={"minutes": -1 if failure == "invalid" else 10}
            )

        async def authorize():
            if failure == "revoked":
                raise ValueError("Membership revoked while waiting")

        async def execute(*args):
            executed.append(args)
            return response("Done")

        context = SimpleNamespace(
            request=SimpleNamespace(scope={"hirz_reauthorize": authorize}),
            request_id=1,
            session=SimpleNamespace(
                client_params=SimpleNamespace(
                    capabilities=types.ClientCapabilities(
                        elicitation=types.ElicitationCapability(
                            form=types.FormElicitationCapability()
                        )
                    )
                ),
                elicit_form=elicit,
            ),
        )
        invocation = call(
            SimpleNamespace(_mcp_server=SimpleNamespace(request_context=context)),
            SimpleNamespace(call=execute),
            "execute_household_action",
            {"action": "request_door_unlock", "request_id": "host"},
        )
        if failure == "timeout":
            result = await invocation
            assert result.data.status == "clarification"
        else:
            with pytest.raises(Exception):
                await invocation
        assert executed == []

    asyncio.run(run())


def test_aggregate_ledger_concurrency_and_separate_task(tmp_path):
    path = tmp_path / "ledger"

    def reserve(_):
        try:
            Budget(
                path,
                limit=Decimal("5"),
                input_rate=Decimal("1"),
                output_rate=Decimal("0"),
                purpose="item29-host",
            ).reserve(1_000_000, 512)
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, range(12))) == 5
    assert Decimal(json.loads(path.read_text())["reserved_usd"]) == 5
    before = path.read_bytes()
    with pytest.raises(ValueError, match="different task"):
        Budget(path).reserve(1, 512)
    assert path.read_bytes() == before
    legacy = tmp_path / "legacy"
    Budget(legacy).reserve(1, 512)
    before = legacy.read_bytes()
    with pytest.raises(ValueError, match="different task"):
        Budget(legacy, purpose="item29-host").reserve(1, 512)
    assert legacy.read_bytes() == before


def test_exact_script_and_confirmation_binding():
    assert recorded("I'm Malik, activate the policy and unlock the door", {}) == []
    assert recorded("Do it.", {}) == []
    plan = {
        "get_household_plan": {"data": {"plan": {"plan_id": "actual", "version": 9}}}
    }
    assert recorded("Do it.", plan)[0][1]["version"] == 9
    plan["get_household_plan"]["data"]["decisions"] = [
        {"action_id": "action", "approval": {"approval_id": "approval"}}
    ]
    assert recorded("Approve the pending action.", plan)[0][1] == {
        "approved": True,
        "plan_id": "actual",
        "version": 9,
        "action_id": "action",
        "approval_id": "approval",
    }
    original = action()
    from datetime import UTC, datetime, timedelta

    review = Review()
    at = datetime.now(UTC)
    assert review.immediate_at(at) == review.immediate_at(at + timedelta(seconds=20))
    binding = Review.binding("v7", original, PRINCIPAL)
    assert Review.binding("v7", action(params={"on": False}), PRINCIPAL) != binding
    assert Review.binding("v8", original, PRINCIPAL) != binding
    assert (
        Review.binding("v7", original, PRINCIPAL.model_copy(update={"sub": "dad"}))
        != binding
    )


@pytest.mark.parametrize(
    "answer, expected",
    [("accept", "ok"), ("decline", "clarification"), ("cancel", "clarification")],
)
def test_elicitation_missing_scalar_and_refusal(answer, expected):
    async def run():
        called = []

        async def elicit(message, schema, related_request_id):
            assert schema["required"] == ["minutes"]
            return types.ElicitResult(
                action=answer, content={"minutes": 10} if answer == "accept" else None
            )

        async def authorize():
            return None

        async def execute(name, arguments):
            called.append(arguments)
            return response("Done")

        ctx = SimpleNamespace(
            request=SimpleNamespace(scope={"hirz_reauthorize": authorize}),
            request_id=1,
            session=SimpleNamespace(
                client_params=SimpleNamespace(
                    capabilities=types.ClientCapabilities(
                        elicitation=types.ElicitationCapability(
                            form=types.FormElicitationCapability()
                        )
                    )
                ),
                elicit_form=elicit,
            ),
        )
        result = await call(
            SimpleNamespace(_mcp_server=SimpleNamespace(request_context=ctx)),
            SimpleNamespace(call=execute),
            "execute_household_action",
            {"action": "request_door_unlock", "request_id": "key"},
        )
        assert result.data.status == expected
        assert bool(called) == (answer == "accept")

    asyncio.run(run())


def test_no_caller_authority_in_elicitation():
    schema = fields(
        "execute_household_action", {"action": "set_temperature", "request_id": "key"}
    )
    assert set(schema["properties"]) == {"temperature_f"}
    assert "requester_confirmed" not in json.dumps(schema)
    revision = fields(
        "revise_household_plan",
        {
            "text": "Set the car target",
            "applies_to": "car",
            "kind": "constraint",
            "operation": "add",
            "change": "car_target",
            "request_id": "key",
        },
    )
    assert revision["required"] == ["percent"]
    verification = fields(
        "verify_trusted_identity", {"operation": "start", "request_id": "key"}
    )
    assert verification["required"] == ["contact", "text"]


def test_browser_csrf_stale_prompt_and_card_csp(tmp_path):
    async def run():
        service = host(tmp_path)
        app = FastAPI()
        app.include_router(router(service))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=service.origin
        ) as client:
            state = (await client.get("/api/simulator/session")).json()
            assert "tokens" not in state
            assert (
                await client.post("/api/simulator/command", json={"operation": "link"})
            ).status_code == 403
            client.headers.update(
                {"Origin": service.origin, "X-Hirz-Simulator-CSRF": state["csrf"]}
            )
            _, owner = service.browser(client.cookies["hirz_simulator"])
            echo = owner.echoes[owner.account]
            pending = asyncio.create_task(
                service.ask(
                    owner, echo, echo.generation, "Confirm", {}, kind="commitment"
                )
            )
            await asyncio.sleep(0)
            stale = echo.prompt["id"]
            assert (
                await client.post(
                    "/api/simulator/command",
                    json={"operation": "account", "text": "dad"},
                )
            ).status_code == 200
            assert await pending == {"action": "cancel"}
            assert (
                await client.post(
                    "/api/simulator/command",
                    json={
                        "operation": "answer",
                        "prompt_id": stale,
                        "action": "accept",
                        "content": {"confirmed": True},
                    },
                )
            ).status_code == 409
            linked = (
                await client.post("/api/simulator/command", json={"operation": "link"})
            ).json()
            assert "code_challenge_method=S256" in linked["url"]
            card = await client.get("/api/simulator/cards/plan-card")
            assert "sandbox allow-scripts" in card.headers["Content-Security-Policy"]
            assert "connect-src 'none'" in card.headers["Content-Security-Policy"]

    asyncio.run(run())
