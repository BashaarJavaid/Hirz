"""Genuine SDK elicitation, account-bound sessions and transaction-free waiting."""

import asyncio
import json
from uuid import uuid4

import httpx
import jwt
import pytest
import sqlalchemy as sa
from mcp import types

from hirz import db
from scripts.smoke_household_tools import mcp_process
from scripts.smoke_tool_budget import Environment
from tests.integration.test_database import (  # noqa: F401
    connect,
    migrate,
    scratch_database,
)

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("interruption", ["cancel", "disconnect", "timeout"])
def test_interrupted_http_prompt_rejects_late_reply(
    scratch_database,  # noqa: F811
    tmp_path,
    interruption,
):
    async def run():
        async with connect(scratch_database) as connection:
            await migrate(connection)
            env = Environment(connection, tmp_path, "demo-evening")
            await env.prepare()
            try:
                async with env.servers(), mcp_process(env.listeners[1], env.config):
                    async with env.client(0) as home:
                        assert home.storage.tokens
                        bearer = home.storage.tokens.access_token
                        headers = {
                            "Authorization": "Bearer " + bearer,
                            "Accept": "application/json, text/event-stream",
                            "MCP-Protocol-Version": home.protocol_version,
                        }
                        before = await connection.scalar(
                            sa.select(sa.func.count()).select_from(db.actions)
                        )
                        await connection.rollback()
                        async with httpx.AsyncClient(
                            headers=headers,
                            timeout=330 if interruption == "timeout" else 15,
                            trust_env=False,
                        ) as http:
                            opened = await http.post(
                                home.url,
                                json={
                                    "jsonrpc": "2.0",
                                    "id": "init",
                                    "method": "initialize",
                                    "params": {
                                        "protocolVersion": home.protocol_version,
                                        "clientInfo": {
                                            "name": "interruption-probe",
                                            "version": "1",
                                        },
                                        "capabilities": {"elicitation": {"form": {}}},
                                    },
                                },
                            )
                            assert opened.status_code == 200
                            http.headers["Mcp-Session-Id"] = opened.headers[
                                "mcp-session-id"
                            ]
                            await http.post(
                                home.url,
                                json={
                                    "jsonrpc": "2.0",
                                    "method": "notifications/initialized",
                                },
                            )
                            started = asyncio.get_running_loop().time()
                            async with http.stream(
                                "POST",
                                home.url,
                                json={
                                    "jsonrpc": "2.0",
                                    "id": "interrupted",
                                    "method": "tools/call",
                                    "params": {
                                        "name": "execute_household_action",
                                        "arguments": {
                                            "action": "request_door_unlock",
                                            "room": "front door",
                                            "request_id": uuid4().hex,
                                        },
                                    },
                                },
                            ) as stream:
                                lines = stream.aiter_lines()
                                async for line in lines:
                                    if line.startswith("data: "):
                                        prompt = json.loads(line[6:])
                                        if prompt.get("method") == "elicitation/create":
                                            break
                                else:
                                    pytest.fail("No real elicitation request received")
                                reply = {
                                    "jsonrpc": "2.0",
                                    "id": prompt["id"],
                                    "result": {
                                        "action": "accept",
                                        "content": {"minutes": 1},
                                    },
                                }
                                claims = jwt.decode(
                                    bearer, options={"verify_signature": False}
                                )
                                claims["exp"] = claims["iat"] - 60
                                expired = jwt.encode(
                                    claims,
                                    env.config["pem"],
                                    algorithm="RS256",
                                    headers=jwt.get_unverified_header(bearer),
                                )
                                rejected = await http.post(
                                    home.url,
                                    headers={"Authorization": "Bearer " + expired},
                                    json=reply,
                                )
                                assert rejected.status_code == 401
                                if interruption == "cancel":
                                    cancelled = await http.post(
                                        home.url,
                                        json={
                                            "jsonrpc": "2.0",
                                            "method": "notifications/cancelled",
                                            "params": {"requestId": "interrupted"},
                                        },
                                    )
                                    assert cancelled.status_code == 202
                                    # Wait for the SDK cancellation receipt before racing a late answer.
                                    async for line in lines:
                                        if line.startswith("data: "):
                                            result = json.loads(line[6:])
                                            if result.get("id") == "interrupted":
                                                assert "error" in result
                                                break
                                if interruption == "timeout":
                                    # Read SSE directly: an SDK callback that waits forever
                                    # also blocks its own receive loop from seeing expiry.
                                    async for line in lines:
                                        if line.startswith("data: "):
                                            result = json.loads(line[6:])
                                            if result.get("id") == "interrupted":
                                                assert (
                                                    result["result"][
                                                        "structuredContent"
                                                    ]["data"]["code"]
                                                    == "PROMPT_EXPIRED"
                                                )
                                                break
                                    else:
                                        pytest.fail("No expiry result received")
                                    assert (
                                        299
                                        <= asyncio.get_running_loop().time() - started
                                        < 330
                                    )
                            if interruption == "disconnect":
                                # A lost SSE connection alone is resumable; explicit session
                                # termination is the client-close boundary tested here.
                                assert (await http.delete(home.url)).status_code == 200
                            late = await http.post(home.url, json=reply)
                            assert late.status_code == (
                                404 if interruption == "disconnect" else 202
                            )
                            if interruption != "disconnect":
                                await http.delete(home.url)
                        assert (
                            await connection.scalar(
                                sa.select(sa.func.count()).select_from(db.actions)
                            )
                            == before
                        )
                        await connection.rollback()
            finally:
                for listener in env.listeners:
                    listener.close()

    asyncio.run(run())


def test_elicitation_rejects_invalid_and_injected_replies(scratch_database, tmp_path):  # noqa: F811
    async def run():
        async with connect(scratch_database) as connection:
            await migrate(connection)
            env = Environment(connection, tmp_path, "demo-evening")
            await env.prepare()
            values = {}

            async def elicitation(context, params):
                assert params.requestedSchema["required"] == ["minutes"]
                return types.ElicitResult(action="accept", content=values)

            try:
                async with env.servers(), mcp_process(env.listeners[1], env.config):
                    async with env.client(0, elicitation_callback=elicitation) as home:
                        before = await connection.scalar(
                            sa.select(sa.func.count()).select_from(db.actions)
                        )
                        await connection.rollback()
                        for values in (
                            {"minutes": -1},
                            {"minutes": True},
                            {},
                            {"minutes": 1, "requester_confirmed": True},
                            {"minutes": 1, "room": "another door"},
                        ):
                            result = await home.session.call_tool(
                                "execute_household_action",
                                {
                                    "action": "request_door_unlock",
                                    "room": "front door",
                                    "request_id": uuid4().hex,
                                },
                            )
                            assert result.isError, result
                        assert (
                            await connection.scalar(
                                sa.select(sa.func.count()).select_from(db.actions)
                            )
                            == before
                        )
                        await connection.rollback()
            finally:
                for listener in env.listeners:
                    listener.close()

    asyncio.run(run())


def test_host_switch_reconciles_accepted_action_without_stale_speech(
    scratch_database,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    import time

    from hirz.host.simulator import Simulator

    async def run():
        async with connect(scratch_database) as connection:
            await migrate(connection)
            env = Environment(connection, tmp_path, "demo-evening")
            await env.prepare()
            host = Simulator(
                origin=env.config["resource"].removesuffix("/mcp"),
                mcp_url=env.config["resource"],
                issuer=env.config["issuer"],
            )
            _, browser = host.browser(None, create=True)
            echo = browser.echoes["malik"]
            emit = host.emit

            def switch_on_receipt(account, generation, **event):
                emit(account, generation, **event)
                if event["kind"] == "prompt":
                    assert account.prompt["kind"] == "commitment"
                    account.answer.set_result(
                        {"action": "accept", "content": {"confirmed": True}}
                    )
                if event["kind"] == "tool":
                    browser.cancel()
                    browser.account = "dad"

            monkeypatch.setattr(host, "emit", switch_on_receipt)
            try:
                async with env.servers(), mcp_process(env.listeners[1], env.config):
                    async with env.client(0) as home:
                        assert home.storage.tokens
                        echo.tokens = home.storage.tokens.model_dump() | {
                            "received": time.monotonic()
                        }
                        before = await connection.scalar(
                            sa.select(sa.func.count())
                            .select_from(db.actions)
                            .where(
                                db.actions.c.proposal["class"].astext
                                == "environment.lights"
                            )
                        )
                        await connection.rollback()
                        await host.turn(
                            browser,
                            "Turn on the living room lamp.",
                            account="malik",
                            model="scripted",
                        )
                        assert (
                            echo.last_result["structuredContent"]["data"]["status"]
                            == "queued"
                        )
                        assert (
                            browser.account == "dad"
                            and not browser.echoes["dad"].events
                        )
                        assert not any(e["kind"] == "speech" for e in echo.events)
                        receipt = next(
                            e for e in echo.events if e["kind"] == "reconciled"
                        )
                        assert receipt["generation"] == echo.generation
                        assert receipt["result"] == echo.last_result
                        assert (
                            await connection.scalar(
                                sa.select(sa.func.count())
                                .select_from(db.actions)
                                .where(
                                    db.actions.c.proposal["class"].astext
                                    == "environment.lights"
                                )
                            )
                            == before + 1
                        )
                        await connection.rollback()
            finally:
                for listener in env.listeners:
                    listener.close()

    asyncio.run(run())


def test_authenticated_elicitation_and_session_isolation(scratch_database, tmp_path):  # noqa: F811
    async def run():
        async with connect(scratch_database) as connection:
            await migrate(connection)
            env = Environment(connection, tmp_path, "demo-evening")
            await env.prepare()
            answer = "decline"
            seen = []

            async def elicitation(context, params):
                seen.append(params.requestedSchema)
                if len(seen) == 1:
                    # Another valid account cannot answer this pending SDK request.
                    foreign = await parents.http.post(
                        parents.url,
                        headers={
                            "Mcp-Session-Id": home.session_id,
                            "MCP-Protocol-Version": home.protocol_version,
                            "Accept": "application/json, text/event-stream",
                        },
                        json={
                            "jsonrpc": "2.0",
                            "id": context.request_id,
                            "result": {"action": "accept", "content": {"minutes": 1}},
                        },
                    )
                    assert foreign.status_code == 404
                # A separate connection can lock the household while the server
                # awaits its human response; no authorization transaction survives.
                async with connect(scratch_database) as other:
                    async with other.begin():
                        await other.execute(
                            sa.select(db.households).with_for_update(nowait=True)
                        )
                return types.ElicitResult(
                    action=answer,
                    content={"minutes": 1} if answer == "accept" else None,
                )

            try:
                async with env.servers(), mcp_process(env.listeners[1], env.config):
                    async with (
                        env.client(0, elicitation_callback=elicitation) as home,
                        env.client(3) as parents,
                    ):
                        for answer in ("decline", "cancel", "accept"):
                            result = await home.session.call_tool(
                                "execute_household_action",
                                {
                                    "action": "request_door_unlock",
                                    "room": "front door",
                                    "request_id": uuid4().hex,
                                },
                            )
                            assert not result.isError, result.structuredContent
                            assert (
                                result.structuredContent["data"]["status"] != "executed"
                            )
                        assert len(seen) == 3 and all(
                            s["required"] == ["minutes"] for s in seen
                        )
                        assert parents.storage.tokens
                        response = await parents.http.post(
                            parents.url,
                            headers={
                                "Mcp-Session-Id": home.session_id,
                                "MCP-Protocol-Version": home.protocol_version,
                                "Accept": "application/json, text/event-stream",
                            },
                            json={
                                "jsonrpc": "2.0",
                                "id": "cross-account",
                                "method": "tools/list",
                                "params": {},
                            },
                        )
                        assert response.status_code == 404
                        fallback = await parents.session.call_tool(
                            "execute_household_action",
                            {
                                "action": "request_door_unlock",
                                "request_id": uuid4().hex,
                            },
                        )
                        assert (
                            fallback.structuredContent["data"]["status"]
                            == "clarification"
                        )
            finally:
                for listener in env.listeners:
                    listener.close()

    asyncio.run(run())


@pytest.mark.parametrize("change", ["policy", "profile"])
def test_requester_review_rechecks_policy_and_resolved_profile(
    scratch_database,  # noqa: F811
    change,
):
    from datetime import timedelta
    from types import SimpleNamespace

    from test_executor_database import environment

    from hirz.mcp.elicitation import call
    from hirz.mcp.household import HouseholdTools
    from hirz.mcp.profiles import Profile
    from hirz.pipeline.models import Principal
    from hirz.pipeline.service import PolicyBundle

    async def run():
        async with connect(scratch_database) as connection:
            p, world, registry, _ = await environment(connection)
            try:
                policy = p.bundle.policy()
                policy = policy.model_copy(
                    update={
                        "verification": policy.verification.model_copy(
                            update={
                                "require_requester_confirmation": (
                                    "environment.comfort_profile",
                                    "environment.lights",
                                ),
                            }
                        )
                    }
                )
                p.bundle = await PolicyBundle.validate(
                    p.household_id, policy, p.boundary
                )
                tools = HouseholdTools(
                    p,
                    Principal(provider="demo", sub="malik", surface="alexa"),
                    profiles={
                        "night": Profile.model_validate(
                            {
                                "settings": [
                                    {"action": "turn_on_light", "room": "Living room"}
                                ]
                            }
                        ),
                    },
                )
                prompts = []

                async def authorize():
                    return None

                async def elicit(message, schema, related_request_id):
                    assert not p.connection.in_transaction()
                    prompts.append(message)
                    world.clock.jump(world.clock() + timedelta(seconds=1))
                    if len(prompts) == 1 and change == "profile":
                        tools.profiles["night"] = Profile.model_validate(
                            {
                                "settings": [
                                    {"action": "turn_off_light", "room": "Living room"}
                                ]
                            }
                        )
                    if len(prompts) == 1 and change == "policy":
                        # Swap the currently evaluated policy bundle while waiting;
                        # this is not a policy-activation claim or a persisted write.
                        changed = policy.model_copy(
                            update={
                                "verification": policy.verification.model_copy(
                                    update={
                                        "require_requester_confirmation": (
                                            *policy.verification.require_requester_confirmation,
                                            "energy.ev_charge",
                                        ),
                                    }
                                )
                            }
                        )
                        p.bundle = await PolicyBundle.validate(
                            p.household_id, changed, p.boundary
                        )
                    assert len(prompts) <= 3, (
                        "An immediate request must retain its hash across real-time waiting"
                    )
                    return types.ElicitResult(
                        action="accept", content={"confirmed": True}
                    )

                context = SimpleNamespace(
                    request=SimpleNamespace(scope={"hirz_reauthorize": authorize}),
                    request_id=1,
                    session=SimpleNamespace(
                        elicit_form=elicit,
                        client_params=SimpleNamespace(
                            capabilities=types.ClientCapabilities(
                                elicitation=types.ElicitationCapability(
                                    form=types.FormElicitationCapability()
                                ),
                            )
                        ),
                    ),
                )
                result = await call(
                    SimpleNamespace(
                        _mcp_server=SimpleNamespace(request_context=context)
                    ),
                    tools,
                    "execute_household_action",
                    {
                        "action": "apply_profile",
                        "profile": "night",
                        "request_id": uuid4().hex,
                    },
                )
                assert result.data.status == "queued", result
                assert (
                    len(prompts) == 3
                )  # Original binding, changed binding, independent child.
                assert len(result.data.decisions) == 1
                assert result.data.decisions[0].decision == "execute"
            finally:
                await registry.close()

    asyncio.run(run())
