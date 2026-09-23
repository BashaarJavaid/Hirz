"""OAuth boundary regressions; all credentials are ephemeral and never retained."""

import asyncio
import base64
import hashlib
import re
import time
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy.ext.asyncio import create_async_engine

from hirz.api.app import create_app
from hirz.mcp import dev_oauth
from hirz.mcp.auth import (
    ISSUER,
    RESOURCE,
    AuthUnavailable,
    KeyCache,
    identity_context,
)
from hirz.mcp.dev_oauth import CALLBACK, DevProvider, create_issuer
from hirz.mcp.server import create_server
from hirz.mcp.transport import local_security
from scripts.dev_oauth import initialize

HEADERS = {"accept": "application/json, text/event-stream"}
VERIFIER = "a" * 43
CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest())
    .decode()
    .rstrip("=")
)


def provider():
    return DevProvider(rsa.generate_private_key(public_exponent=65537, key_size=2048))


def params(**changes):
    return (
        dict(
            client_id="hirz-dev-sdk",
            redirect_uri=CALLBACK,
            response_type="code",
            code_challenge=CHALLENGE,
            code_challenge_method="S256",
            resource=RESOURCE,
            state="test-state",
        )
        | changes
    )


def exchange(code, **changes):
    return (
        dict(
            client_id="hirz-dev-sdk",
            redirect_uri=CALLBACK,
            grant_type="authorization_code",
            code=code,
            code_verifier=VERIFIER,
            resource=RESOURCE,
        )
        | changes
    )


async def consent(
    client, *, choice=0, decision="approve", scopes="hirz:read", **changes
):
    p = params(**changes)
    if scopes is not None:
        p["scope"] = scopes
    response = await client.get("/authorize", params=p)
    assert response.status_code == 302
    page = await client.get(response.headers["location"])
    assert "simulated login" in page.text
    assert page.headers["referrer-policy"] == "same-origin"
    assert f"form-action 'self' {CALLBACK}" in page.headers["content-security-policy"]
    hidden = dict(re.findall(r'name="(transaction|csrf)" value="([^"]+)"', page.text))
    response = await client.post(
        "/consent", data=hidden | {"member": str(choice), "decision": decision}
    )
    assert response.status_code == 302
    return parse_qs(urlsplit(response.headers["location"]).query)


async def tokens(client, **kwargs):
    code = (await consent(client, **kwargs))["code"][0]
    response = await client.post("/token", data=exchange(code))
    assert response.status_code == 200
    return response.json()


def claims(p, **changes):
    at = int(time.time())
    return (
        dict(
            iss=ISSUER,
            sub="malik",
            aud=RESOURCE,
            iat=at,
            exp=at + 300,
            client_id="hirz-dev-sdk",
            scope="hirz:read",
            household_id=p.choices[0].household,
        )
        | changes
    )


def encode(p, values=None, **headers):
    return jwt.encode(
        values or claims(p),
        p.key,
        algorithm="RS256",
        headers={"kid": p.kid, "typ": "at+jwt"} | headers,
    )


async def cache_for(p):
    cache = KeyCache()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_issuer(p)), base_url=ISSUER
    ) as client:
        assert await cache.refresh(client)
    return cache


async def oauth_probe() -> dict[str, Any]:
    from mcp.server.auth.middleware.auth_context import get_access_token

    before = identity_context.get()
    assert before is not None and get_access_token() is not None
    await asyncio.sleep(0)
    assert identity_context.get() is before
    return {
        "speakable": {
            "headline": "Your simulated account is linked.",
            "details": [],
            "options": [],
        },
        "data": {
            "household": str(before.household_id),
            "member": before.member.member_id,
            "role": before.member.role,
            "surface": before.principal.surface,
            "passkey": before.principal.passkey_verified,
            "speaker": before.member.speaker,
        },
    }


def call(name="oauth_probe"):
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": {}},
    }


@asynccontextmanager
async def gated(p, engine=None, required="hirz:read"):
    cache = await cache_for(p)

    # Inject an already-refreshed cache so no test makes a third-party request.
    @asynccontextmanager
    async def running():
        yield

    cache.run = running
    app = create_app(
        cache=cache,
        engine=engine
        or create_async_engine("postgresql+psycopg://invalid@127.0.0.1:1/invalid"),
        register=lambda server: server.add_tool(oauth_probe, required_scope=required),
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1:8000",
            headers=HEADERS,
        ) as client:
            yield client, cache


def test_consent_exchange_rotation_resource_and_replay():
    async def run():
        p = provider()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_issuer(p)), base_url=ISSUER
        ) as client:
            metadata = (
                await client.get("/.well-known/oauth-authorization-server")
            ).json()
            assert metadata["code_challenge_methods_supported"] == ["S256"]
            assert (
                "registration_endpoint" not in metadata
                and "revocation_endpoint" not in metadata
            )
            assert len(p.choices) == 5
            assert (await consent(client, decision="deny"))["error"] == [
                "access_denied"
            ]
            for change in (
                {"resource": None},
                {"resource": RESOURCE + "/other"},
                {"redirect_uri": CALLBACK + "/other"},
                {"code_challenge_method": "plain"},
                {"code_challenge_method": None},
            ):
                values = {k: v for k, v in params(**change).items() if v is not None}
                response = await client.get("/authorize", params=values)
                assert response.status_code == 400
                assert not p.pending
            response = await client.get("/authorize", params=params(scope="root"))
            assert "invalid_scope" in response.headers["location"]
            code = (await consent(client, scopes=None))["code"][0]
            for changes in (
                {"resource": None},
                {"resource": "https://wrong.example/mcp"},
                {"code_verifier": "b" * 43},
                {"redirect_uri": CALLBACK + "/wrong"},
            ):
                response = await client.post(
                    "/token",
                    data={
                        k: v
                        for k, v in exchange(code, **changes).items()
                        if v is not None
                    },
                )
                assert response.status_code == 400
                assert not p.families
            good = (await client.post("/token", data=exchange(code))).json()
            assert good["scope"] == "hirz:read"
            assert (await client.post("/token", data=exchange(code))).status_code == 400
            original = jwt.decode(
                good["access_token"],
                p.key.public_key(),
                algorithms=["RS256"],
                audience=RESOURCE,
            )
            refresh = dict(
                client_id="hirz-dev-sdk",
                grant_type="refresh_token",
                refresh_token=good["refresh_token"],
            )
            assert (
                await client.post("/token", data=refresh | {"scope": "hirz:act"})
            ).json()["error"] == "invalid_scope"
            assert (
                await client.post("/token", data=refresh | {"resource": "wrong"})
            ).json()["error"] == "invalid_target"
            refreshed = (await client.post("/token", data=refresh)).json()
            assert refreshed["refresh_token"] != good["refresh_token"]
            next_claims = jwt.decode(
                refreshed["access_token"],
                p.key.public_key(),
                algorithms=["RS256"],
                audience=RESOURCE,
            )
            assert all(
                original[k] == next_claims[k]
                for k in ("sub", "aud", "household_id", "scope")
            )
            assert (await client.post("/token", data=refresh)).json()[
                "error"
            ] == "invalid_grant"
            assert (
                await client.post(
                    "/token",
                    data=refresh | {"refresh_token": refreshed["refresh_token"]},
                )
            ).json()["error"] == "invalid_grant"
            code = (await consent(client))["code"][0]
            p.codes[code].expires_at = time.time() - 1
            assert (await client.post("/token", data=exchange(code))).status_code == 400

    asyncio.run(run())


def test_csrf_limits_expiry_and_atomic_rotation(monkeypatch):
    async def run():
        p = provider()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_issuer(p)), base_url=ISSUER
        ) as client:
            response = await client.get("/authorize", params=params())
            page = await client.get(response.headers["location"])
            hidden = dict(
                re.findall(r'name="(transaction|csrf)" value="([^"]+)"', page.text)
            )
            assert (
                await client.post(
                    "/consent",
                    data=hidden
                    | {"csrf": "wrong", "member": "0", "decision": "approve"},
                )
            ).status_code == 400
            client.cookies.clear()
            assert (
                await client.post(
                    "/consent", data=hidden | {"member": "0", "decision": "approve"}
                )
            ).status_code == 400
            monkeypatch.setattr(dev_oauth, "LIMIT", 1)
            response = await client.get("/authorize", params=params())
            assert "temporarily_unavailable" in response.headers["location"]
            pending = next(iter(p.pending.values()))
            pending.expires_at = time.time() - 1
            code = (await consent(client))["code"][0]
            assert (await consent(client))["error"] == ["temporarily_unavailable"]
            response = await client.post("/token", data=exchange(code))
            assert response.status_code == 200
            old = response.json()["refresh_token"]
            family = next(iter(p.families.values()))
            expires = family.current.expires_at
            a = await p.load_refresh_token(p.client, old)
            b = await p.load_refresh_token(p.client, old)
            await p.exchange_refresh_token(p.client, a, a.scopes)
            with pytest.raises(dev_oauth.TokenError):
                await p.exchange_refresh_token(p.client, b, b.scopes)
            assert family.revoked and family.current.expires_at == expires
            code = (await consent(client))["code"][0]
            assert (await client.post("/token", data=exchange(code))).status_code == 400
            family.current.expires_at = int(time.time()) - 1
            assert (await client.post("/token", data=exchange(code))).status_code == 200
            assert len(p.families) == 1
            # A forged generation cannot revoke another grant.
            current = next(iter(p.families.values()))
            forged = current.current.token.split(".")[0] + ".0." + "0" * 64
            assert await p.load_refresh_token(p.client, forged) is None
            assert not current.revoked

    asyncio.run(run())


def test_jwt_validation_and_fresh_key_errors():
    async def run():
        p = provider()
        cache = await cache_for(p)
        assert await cache.verify_token(encode(p)) is not None
        at = int(time.time())
        bad = [
            {"aud": "wrong"},
            {"aud": [RESOURCE]},
            {"iss": "wrong"},
            {"exp": at - 31, "iat": at - 331},
            {"iat": at + 31, "exp": at + 300},
            {"nbf": at + 31},
            {"nbf": "1"},
            {"iat": str(at)},
            {"exp": float(at + 300)},
            {"sub": 1},
            {"sub": ""},
            {"client_id": False},
            {"household_id": "invalid"},
            {"scope": ["hirz:read"]},
            {"scope": "root"},
            {"exp": at + 301},
            {"exp": at - 1, "iat": at},
            {"nbf": at + 400},
        ]
        for change in bad:
            assert await cache.verify_token(encode(p, claims(p, **change))) is None
        for key in claims(p):
            data = claims(p)
            data.pop(key)
            assert await cache.verify_token(encode(p, data)) is None
        for headers in (
            {"kid": "unknown"},
            {"kid": ""},
            {"typ": "JWT"},
            {"crit": ["x"]},
        ):
            assert await cache.verify_token(encode(p, **headers)) is None
        assert await cache.verify_token(encode(provider())) is None
        assert (
            await cache.verify_token(
                jwt.encode(
                    claims(p),
                    "a" * 32,
                    algorithm="HS256",
                    headers={"kid": p.kid, "typ": "at+jwt"},
                )
            )
            is None
        )
        assert await cache.verify_token("malformed") is None
        assert await cache.verify_token(encode(p, claims(p, exp=float("inf")))) is None
        # Accept exactly the configured skew, and ignore token authority claims.
        assert (
            await cache.verify_token(
                encode(
                    p,
                    claims(
                        p,
                        exp=at - 10,
                        iat=at - 310,
                        role="owner",
                        provider="admin",
                        surface="app",
                        passkey_verified=True,
                    ),
                )
            )
            is not None
        )
        cache.updated -= 301
        with pytest.raises(AuthUnavailable):
            await cache.verify_token(encode(p))

    asyncio.run(run())


def test_key_cache_fetch_bounds_origin_expiry_and_recovery():
    async def run():
        p = provider()
        cache = await cache_for(p)
        original = cache.updated
        for response in (
            httpx.Response(302, headers={"location": "https://other.invalid"}),
            httpx.Response(
                200, json={"issuer": ISSUER, "jwks_uri": "https://other.invalid/keys"}
            ),
            httpx.Response(200, content=b"x" * 1_048_577),
            httpx.Response(200, content=b"[" * 1000 + b"]" * 1000),
            httpx.Response(
                200, json={"issuer": ISSUER + "/wrong", "jwks_uri": ISSUER + "/keys"}
            ),
        ):
            async with httpx.AsyncClient(
                transport=httpx.MockTransport(lambda request: response)
            ) as client:
                assert not await cache.refresh(client)
                assert cache.updated == original
        assert await cache.verify_token(encode(p))
        cache.updated -= 301
        with pytest.raises(AuthUnavailable):
            await cache.verify_token(encode(p))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_issuer(p))
        ) as client:
            assert await cache.refresh(client)
        assert await cache.verify_token(encode(p))

    asyncio.run(run())


def test_http_gate_errors_guest_and_registration():
    async def run():
        p = provider()
        with pytest.raises(ValueError, match="authentication"):
            create_server(local_security(8000)).add_tool(oauth_probe)
        async with gated(p) as (client, cache):
            root = await client.get("/.well-known/oauth-protected-resource")
            assert (
                root.json()
                == (
                    await client.get("/.well-known/oauth-protected-resource/mcp")
                ).json()
            )
            response = await client.post("/mcp", json=call())
            assert (
                response.status_code == 401
                and 'resource_metadata="http://127.0.0.1:8000/.well-known/oauth-protected-resource"'
                in response.headers["www-authenticate"]
            )
            for headers in (
                {"authorization": "Basic bad"},
                {"authorization": "Bearer "},
                [("authorization", "Bearer x"), ("authorization", "Bearer y")],
                {"authorization": "Bearer " + encode(p, claims(p, aud="wrong"))},
            ):
                assert (
                    await client.post("/mcp", json=call(), headers=headers)
                ).status_code == 401
            response = await client.post(
                "/mcp",
                json=call(),
                headers={
                    "authorization": "Bearer " + encode(p, claims(p, scope="hirz:act"))
                },
            )
            assert (
                response.status_code == 403
                and "insufficient_scope" in response.headers["www-authenticate"]
            )
            assert (
                await client.post(
                    "/mcp",
                    json=call(),
                    headers={"authorization": "Bearer " + encode(p)},
                )
            ).status_code == 503
            cache.updated -= 301
            assert (
                await client.post(
                    "/mcp",
                    json=call(),
                    headers={"authorization": "Bearer " + encode(p)},
                )
            ).status_code == 503
            assert (
                await client.post("/mcp", json=call("what_can_you_do"))
            ).status_code == 200
        app = create_app()
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://127.0.0.1:8000",
                headers=HEADERS,
            ) as client:
                assert (
                    await client.post(
                        "/mcp",
                        json=call("what_can_you_do"),
                        headers={"authorization": "Bearer x"},
                    )
                ).status_code == 503
                listed = await client.post(
                    "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
                )
                assert [t["name"] for t in listed.json()["result"]["tools"]] == [
                    "what_can_you_do"
                ]

    asyncio.run(run())


def test_explicit_key_initialization(tmp_path):
    from hirz.local import LocalError, read_env
    from hirz.mcp.dev_oauth import KEY_NAME, signing_key

    path = tmp_path / ".env"
    initialize(path)
    first = path.read_bytes()
    assert path.stat().st_mode & 0o777 == 0o600
    assert signing_key(read_env(path)).key_size == 2048
    initialize(path)
    assert path.read_bytes() == first
    for value in ("", "malformed"):
        path.write_text(f'{KEY_NAME}="{value}"\n')
        with pytest.raises(LocalError):
            initialize(path)
        assert path.read_text() == f'{KEY_NAME}="{value}"\n'
    path.unlink()
    path.symlink_to(tmp_path / "missing")
    with pytest.raises(LocalError):
        initialize(path)


def test_issuer_restart_loses_grants_but_access_token_survives():
    async def run():
        p = provider()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_issuer(p)), base_url=ISSUER
        ) as client:
            issued = await tokens(client)
            code = (await consent(client))["code"][0]
        restarted = DevProvider(p.key)
        assert not restarted.pending and not restarted.codes and not restarted.families
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_issuer(restarted)), base_url=ISSUER
        ) as client:
            assert (await client.post("/token", data=exchange(code))).status_code == 400
            assert (
                await client.post(
                    "/token",
                    data={
                        "grant_type": "refresh_token",
                        "client_id": "hirz-dev-sdk",
                        "refresh_token": issued["refresh_token"],
                    },
                )
            ).status_code == 400
        cache = await cache_for(restarted)
        assert await cache.verify_token(issued["access_token"])

    asyncio.run(run())


def test_timeout_bad_jwks_and_polling(monkeypatch):
    async def run():
        cache = KeyCache()

        async def slow(request):
            await asyncio.sleep(3)
            return httpx.Response(200, json={})

        async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as client:
            start = time.monotonic()
            assert not await cache.refresh(client)
            assert time.monotonic() - start < 2.5
        for keys in (
            [],
            [{"kty": "oct"}],
            [{"kty": "RSA", "alg": "RS256", "use": "sig", "kid": "x", "n": "invalid"}],
            [None],
        ):

            def respond(request):
                return httpx.Response(
                    200,
                    json={"issuer": ISSUER, "jwks_uri": ISSUER + "/keys"}
                    if "well-known" in request.url.path
                    else {"keys": keys},
                )

            async with httpx.AsyncClient(
                transport=httpx.MockTransport(respond)
            ) as client:
                assert not await cache.refresh(client)
        calls = []

        async def refresh(client):
            calls.append(True)
            return False

        cache.refresh = refresh
        import hirz.mcp.auth as auth

        sleep = asyncio.sleep

        async def poll_sleep(seconds):
            assert seconds == 60
            if len(calls) < 2:
                await sleep(0)
            else:
                await sleep(3600)

        monkeypatch.setattr(auth.asyncio, "sleep", poll_sleep)
        async with cache.run():
            for _ in range(10):
                await sleep(0)
            assert len(calls) == 2

    asyncio.run(run())


def test_signature_scope_narrowing_duplicate_parameters_and_consent_replay():
    async def run():
        p = provider()
        cache = await cache_for(p)
        assert dev_oauth.LIMIT == 1024
        assert await cache.verify_token(encode(provider(), kid=p.kid)) is None
        assert (
            await cache.verify_token(
                jwt.encode(
                    claims(p), p.key, algorithm="RS256", headers={"typ": "at+jwt"}
                )
            )
            is None
        )
        assert (
            await cache.verify_token(
                jwt.encode(
                    claims(p),
                    None,
                    algorithm="none",
                    headers={"kid": p.kid, "typ": "at+jwt"},
                )
            )
            is None
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_issuer(p)), base_url=ISSUER
        ) as client:
            response = await client.get(
                "/authorize", params=list(params().items()) + [("resource", RESOURCE)]
            )
            assert response.status_code == 400 and not p.pending
            response = await client.get(
                "/authorize", params=params(scope=" ".join(dev_oauth.SCOPES))
            )
            page = await client.get(response.headers["location"])
            hidden = dict(
                re.findall(r'name="(transaction|csrf)" value="([^"]+)"', page.text)
            )
            data = hidden | {"decision": "approve", "member": "0"}
            response = await client.post("/consent", data=data)
            assert (await client.post("/consent", data=data)).status_code == 400
            code = parse_qs(urlsplit(response.headers["location"]).query)["code"][0]
            issued = (await client.post("/token", data=exchange(code))).json()
            refresh = {
                "client_id": "hirz-dev-sdk",
                "grant_type": "refresh_token",
                "refresh_token": issued["refresh_token"],
                "scope": "hirz:read",
            }
            narrowed = (await client.post("/token", data=refresh)).json()
            assert narrowed["scope"] == "hirz:read"
            refresh["refresh_token"] = narrowed["refresh_token"]
            refresh["scope"] = "hirz:act"
            assert (await client.post("/token", data=refresh)).json()[
                "error"
            ] == "invalid_scope"
            assert (
                await client.post("/token", content=b"a" * 1_048_577)
            ).status_code == 413

    asyncio.run(run())


def test_authenticated_factory_has_no_probe_and_survives_initial_issuer_outage(
    monkeypatch,
):
    import hirz.api.app as api

    async def unavailable(self, client, url):
        raise httpx.ConnectError("injected issuer outage")

    monkeypatch.setattr(api, "read_env", lambda path: {"POSTGRES_PASSWORD": "unused"})
    monkeypatch.setattr(KeyCache, "document", unavailable)

    async def run():
        app = api.create_local_oauth_app()
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://127.0.0.1:8000",
                headers=HEADERS,
            ) as client:
                listed = await client.post(
                    "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
                )
                assert [t["name"] for t in listed.json()["result"]["tools"]] == [
                    "what_can_you_do"
                ]
                assert (
                    await client.post("/mcp", json=call("what_can_you_do"))
                ).status_code == 200
                assert (
                    await client.post(
                        "/mcp",
                        json=call("what_can_you_do"),
                        headers={"authorization": "Bearer unavailable"},
                    )
                ).status_code == 503

    asyncio.run(run())
