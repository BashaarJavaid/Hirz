"""Full Runtime tool composition with a simulated issuer and disposable database.

Production Cognito linking is a separate gate; these tests use existing demo
accounts and real signed local tokens, passkey activation, tools and audit rows.
"""

import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest
import sqlalchemy as sa
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from test_companion_auth_database import enroll
from test_database import connect
from test_database import scratch_database as scratch_database
from test_pipeline_database import setup

from hirz import db
from hirz.audit import verify_database
from hirz.aws import app as aws_app
from hirz.aws.routing import Route, Routing
from hirz.companion import auth, policy
from hirz.constitution.schema import dump
from hirz.mcp import runtime as mcp_runtime
from hirz.mcp.contracts import TOOLS
from tests.unit.aws.test_runtime import RESOURCE
from tests.unit.test_companion_auth import Authenticator
from tests.unit.test_oauth import cache_for, claims, encode, provider
from tests.unit.test_pipeline import ident

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("assignment", ["local", "managed", "unknown"])
def test_runtime_real_tools_audit_and_explicit_policy_route(
    scratch_database, monkeypatch, assignment
):
    async def run():
        async with connect(scratch_database) as c:
            p = await setup(c, native=True)
            login = await enroll(
                p,
                await auth.initial_invitation(p, ident("members", "malik")),
                Authenticator(),
            )
            async with c.begin():
                member = await auth.session(c, login["session"], p.clock())
            owner = member["principal"].model_copy(update={"passkey_verified": True})
            async with p.repo.write(p.clock):
                draft = await policy.draft(p, owner, dump(p.bundle.policy()))
                await policy.activate(
                    p, owner, draft["id"], draft["candidate_hash"], member["digest"]
                )
            issuer = provider()
            verifier = await cache_for(issuer)

            @asynccontextmanager
            async def keys():
                yield

            verifier.run = keys
            monkeypatch.setattr(aws_app, "CognitoCache", lambda *a, **kw: verifier)
            monkeypatch.setattr(aws_app.config, "secret", lambda _: "synthetic")
            monkeypatch.setattr(aws_app.config, "database", lambda _: c.engine)
            monkeypatch.setattr(aws_app, "signing_key", lambda _: p.audit.key)
            for name, value in {
                "HIRZ_RUNTIME_RESOURCE": RESOURCE,
                "HIRZ_COGNITO_ISSUER": "simulated-by-local-issuer",
                "HIRZ_HUMAN_CLIENT": "simulated-client",
                "HIRZ_POLICY_ENGINE": "engine",
                "HIRZ_GATEWAY_ARN": "gateway-arn",
                "HIRZ_GATEWAY_URL": "https://gateway.example.test/mcp",
            }.items():
                monkeypatch.setenv(name, value)
            route = Route("engine", "gateway-arn", "https://gateway.example.test/mcp")
            routes = Routing(
                frozenset({p.household_id}) if assignment == "managed" else frozenset(),
                frozenset({p.household_id}) if assignment == "local" else frozenset(),
                route,
            )
            monkeypatch.setattr(aws_app, "policy_routes", lambda _: routes)
            household_type = aws_app.HouseholdRuntime
            monkeypatch.setattr(
                aws_app,
                "HouseholdRuntime",
                lambda *a, **kw: household_type(*a, **kw, clock=p.clock),
            )
            pipelines = []
            tools_type = mcp_runtime.HouseholdTools

            def tools(pipeline, *args, **kwargs):
                pipelines.append(pipeline)
                return tools_type(pipeline, *args, **kwargs)

            monkeypatch.setattr(mcp_runtime, "HouseholdTools", tools)
            app = aws_app.create_runtime()
            if assignment == "unknown":
                with pytest.raises(ValueError, match="Unknown household boundary"):
                    async with app.router.lifespan_context(app):
                        pytest.fail("Unassigned household started")
                return
            signed = encode(
                issuer, claims(issuer, scope="hirz:read hirz:act hirz:plan")
            )
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app),
                    headers={"Authorization": "Bearer " + signed},
                ) as http:
                    async with streamable_http_client(
                        "http://runtime.internal:8000/mcp", http_client=http
                    ) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            assert {
                                t.name for t in (await session.list_tools()).tools
                            } == set(TOOLS)
                            result = await session.call_tool(
                                "get_household_context", {}
                            )
                            assert not result.isError, result
                            assert result.structuredContent["data"]["context"][
                                "household_id"
                            ] == str(p.household_id)
                            result = await session.call_tool(
                                "propose_household_rule",
                                {
                                    "text": "Never unlock for an unexpected visitor",
                                    "request_id": "runtime-proposal",
                                },
                            )
                            assert not result.isError, result
                            assert (
                                result.structuredContent["data"]["status"] == "recorded"
                            )
                            assert len(pipelines) == 2
                            assert all(
                                q.require_active and q.gateway is None
                                for q in pipelines
                            )
                            assert all(
                                q.policy_route
                                == (route if assignment == "managed" else None)
                                for q in pipelines
                            )
                async with c.begin():
                    assert (
                        await c.scalar(
                            sa.select(sa.func.count()).select_from(db.rule_proposals)
                        )
                        == 1
                    )
                report, _ = await verify_database(
                    c, p.household_id, p.audit.key.public_key()
                )
                assert report["status"] == "valid" and report["checked_count"] > 0

    asyncio.run(run())
