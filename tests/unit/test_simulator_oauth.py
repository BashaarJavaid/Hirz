"""Cognito's two origins stay pinned while the published host owns PKCE and refresh."""

import asyncio
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from addon_host import OAuthConfig, OAuthSession
from mcp.client.auth.exceptions import OAuthFlowError

from hirz.host.oauth import CognitoSession
from tests.unit.aws.test_auth import CLIENT, ISSUER, RESOURCE

LOGIN = "https://configured.auth.us-east-1.amazoncognito.com"
CONFIG = OAuthConfig(
    RESOURCE,
    ISSUER,
    CLIENT,
    "https://companion.example.test/api/simulator/callback",
    ("hirz/read", "hirz/plan"),
)


@pytest.mark.parametrize(
    "case",
    ["missing_pkce", "s256", "plain", "issuer", "authorization", "token", "resource"],
)
def test_cognito_discovery_pkce_exchange_and_refresh(monkeypatch, case):
    seen = []
    metadata = {
        "issuer": ISSUER,
        "authorization_endpoint": LOGIN + "/oauth2/authorize",
        "token_endpoint": LOGIN + "/oauth2/token",
        "response_types_supported": ["code", "token"],
    }
    if case in {"s256", "plain"}:
        metadata["code_challenge_methods_supported"] = [
            "S256" if case == "s256" else "plain"
        ]
    if case == "issuer":
        metadata["issuer"] = ISSUER + "wrong"
    if case in {"authorization", "token"}:
        metadata[case + "_endpoint"] = (
            "https://unconfigured.example.test/oauth2/" + case
        )

    def respond(request):
        seen.append(str(request.url))
        if str(request.url) == RESOURCE:
            return httpx.Response(
                401,
                headers={
                    "www-authenticate": f'Bearer resource_metadata="{RESOURCE}/.well-known/oauth-protected-resource"'
                },
            )
        if str(request.url) == RESOURCE + "/.well-known/oauth-protected-resource":
            return httpx.Response(
                200,
                json={
                    "resource": RESOURCE + ("wrong" if case == "resource" else ""),
                    "authorization_servers": [ISSUER],
                },
            )
        if str(request.url) == ISSUER + "/.well-known/openid-configuration":
            return httpx.Response(200, json=metadata)
        if str(request.url) == LOGIN + "/oauth2/token":
            body = parse_qs(request.content.decode())
            assert body["client_id"] == [CLIENT]
            assert body["resource"] == [RESOURCE]
            if body["grant_type"] == ["authorization_code"]:
                assert len(body["code_verifier"][0]) >= 43
                assert body["redirect_uri"] == [CONFIG.redirect_uri]
            else:
                assert body["grant_type"] == ["refresh_token"]
                assert body["refresh_token"] == ["synthetic-refresh"]
            return httpx.Response(
                200,
                json={
                    "access_token": "synthetic-access",
                    "refresh_token": "synthetic-refresh",
                    "token_type": "Bearer",
                    "expires_in": 300,
                    "scope": "hirz/read hirz/plan",
                },
            )
        return httpx.Response(404)

    client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: client(transport=httpx.MockTransport(respond), **kw),
    )

    async def run():
        session = CognitoSession(CONFIG, login_origin=LOGIN)
        if case not in {"missing_pkce", "s256"}:
            with pytest.raises((ValueError, OAuthFlowError)):
                await session.begin()
            assert not any(url.startswith("https://unconfigured") for url in seen)
            assert not any(url == LOGIN + "/oauth2/token" for url in seen)
            return
        url = await session.begin()
        query = parse_qs(urlsplit(url).query)
        assert url.startswith(LOGIN + "/oauth2/authorize?")
        assert query["code_challenge_method"] == ["S256"]
        assert len(query["code_challenge"][0]) == 43
        assert query["scope"] == ["hirz/read hirz/plan"]
        assert query["resource"] == [RESOURCE]
        assert query["client_id"] == [CLIENT]
        await session.complete(query["state"][0], "synthetic-code")
        with pytest.raises(ValueError, match="invalid or expired"):
            await session.complete(query["state"][0], "synthetic-code")
        assert await session.token() == "synthetic-access"
        session._received = 0
        assert await session.token() == "synthetic-access"
        assert seen.count(LOGIN + "/oauth2/token") == 2

    asyncio.run(run())


def test_exact_origin_allowance_does_not_relax_other_endpoints():
    with pytest.raises(ValueError, match="outside its configured origin"):
        OAuthSession(CONFIG)._endpoint(LOGIN + "/oauth2/authorize", ISSUER)
    session = CognitoSession(CONFIG, login_origin=LOGIN)
    for endpoint, base in (
        (LOGIN + "/keys", ISSUER),
        (LOGIN + "/oauth2/token?changed=true", ISSUER),
        (LOGIN + "/oauth2/token", RESOURCE),
        ("http://configured.auth.us-east-1.amazoncognito.com/oauth2/token", ISSUER),
    ):
        with pytest.raises(ValueError):
            session._endpoint(endpoint, base)
    for origin in (
        "http://login.example.test",
        "https://login.example.test/path",
        "https://user@login.example.test",
        "https://login.example.test?x=1",
    ):
        with pytest.raises(ValueError):
            CognitoSession(CONFIG, login_origin=origin)
