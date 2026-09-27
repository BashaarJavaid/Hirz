"""Genuine SDK elicitation, account-bound sessions and transaction-free waiting."""

import asyncio
from uuid import uuid4

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


def test_requester_review_rechecks_policy_and_resolved_profile(scratch_database):  # noqa: F811
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
                    if len(prompts) == 1:
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
                )  # Old policy, current policy, independent child.
                assert len(result.data.decisions) == 1
                assert result.data.decisions[0].decision == "execute"
            finally:
                await registry.close()

    asyncio.run(run())
