"""Runtime composition without AWS calls; issuer and database tests are separate."""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from hirz.aws import app as aws_app
from hirz.mcp.contracts import TOOLS
from tests.unit.aws.test_auth import CLIENT, ISSUER

RESOURCE = "https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/test/invocations?qualifier=DEFAULT"


def test_runtime_full_catalog_challenge_bounds_and_lifespan(monkeypatch):
    for name, value in {
        "HIRZ_RUNTIME_RESOURCE": RESOURCE,
        "HIRZ_COGNITO_ISSUER": ISSUER,
        "HIRZ_HUMAN_CLIENT": CLIENT,
        "HIRZ_POLICY_ENGINE": "engine",
        "HIRZ_GATEWAY_ARN": "gateway-arn",
        "HIRZ_GATEWAY_URL": "https://gateway.example.test/mcp",
    }.items():
        monkeypatch.setenv(name, value)
    engine = Mock(dispose=AsyncMock())
    secrets = Mock(return_value="synthetic")
    monkeypatch.setattr(aws_app.config, "secret", secrets)
    monkeypatch.setattr(aws_app.config, "database", lambda _: engine)
    monkeypatch.setattr(
        aws_app, "signing_key", lambda _: ec.generate_private_key(ec.SECP256R1())
    )
    opened = []

    @asynccontextmanager
    async def household_run(self):
        assert not self.allow_unvalidated_fixture
        assert len(self.policy_routes.managed) == 2
        assert len(self.policy_routes.local) == 1
        opened.append("household")
        yield
        opened.append("household closed")

    @asynccontextmanager
    async def cache_run(self):
        assert self.issuer == ISSUER and self.client_id == CLIENT
        assert self.resource == RESOURCE
        opened.append("issuer")
        yield
        opened.append("issuer closed")

    monkeypatch.setattr(aws_app.HouseholdRuntime, "run", household_run)
    monkeypatch.setattr(aws_app.CognitoCache, "run", cache_run)

    async def run():
        app = aws_app.create_runtime()
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app),
                base_url="http://runtime.internal:8000",
            ) as client:
                assert (await client.get("/ping")).json() == {"status": "Healthy"}
                listed = await client.post(
                    "/mcp",
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                    headers={"Accept": "application/json, text/event-stream"},
                )
                assert listed.status_code == 200
                assert {
                    tool["name"] for tool in listed.json()["result"]["tools"]
                } == set(TOOLS)
                refused = await client.post(
                    "/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {"name": "get_household_context", "arguments": {}},
                    },
                )
                assert refused.status_code == 401
                assert 'scope="hirz/read"' in refused.headers["www-authenticate"]
                assert (
                    "/invocations/.well-known/oauth-protected-resource?qualifier=DEFAULT"
                    in refused.headers["www-authenticate"]
                )
                assert (await client.post("/mcp", content=b"[" * 33)).status_code == 400
                assert (
                    await client.post("/mcp", content=b"x" * 1_048_577)
                ).status_code == 413
                assert (await client.post("/internal/tick")).status_code == 404
        engine.dispose.assert_awaited_once()
        assert opened == ["household", "issuer", "issuer closed", "household closed"]
        assert [c.args[0] for c in secrets.call_args_list] == [
            "HIRZ_DATABASE_SECRET",
            "HIRZ_AUDIT_SECRET",
        ]

    asyncio.run(run())


@pytest.mark.parametrize(
    "resource",
    [
        "",
        "http://example.test/invocations",
        "https://example.test/mcp",
        RESOURCE + "#fragment",
    ],
)
def test_runtime_refuses_incomplete_resource_configuration(monkeypatch, resource):
    monkeypatch.setenv("HIRZ_RUNTIME_RESOURCE", resource)
    secret = Mock()
    monkeypatch.setattr(aws_app.config, "secret", secret)
    with pytest.raises(ValueError, match="exact Runtime protected resource"):
        aws_app.create_runtime()
    secret.assert_not_called()
