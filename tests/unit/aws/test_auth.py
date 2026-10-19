"""Cognito contract checks with ephemeral signatures and bounded local discovery."""

import asyncio
import json
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from hirz.aws.auth import CognitoCache
from hirz.mcp.auth import AuthUnavailable

ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_test"
RESOURCE = "https://runtime.example.test/mcp"
CLIENT = "human-client"


@pytest.fixture
def key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def token(key, changes=None, *, omit=(), headers=None):
    at = int(time.time())
    claims = {
        "iss": ISSUER,
        "sub": "linked-account-subject",
        "aud": RESOURCE,
        "client_id": CLIENT,
        "token_use": "access",
        "scope": "openid hirz/read hirz/act",
        "iat": at,
        "exp": at + 300,
    } | (changes or {})
    for name in omit:
        claims.pop(name)
    return jwt.encode(
        claims,
        key,
        algorithm="RS256",
        headers={"kid": "test", "typ": "JWT"} | (headers or {}),
    )


def cache(key):
    value = CognitoCache(ISSUER, RESOURCE, CLIENT)
    value.keys = {"test": key.public_key()}
    value.updated = value.clock()
    return value


def test_cognito_discovery_and_native_scopes(key):
    async def run():
        seen = []
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
        jwk.update(kid="test", alg="RS256", use="sig")

        def respond(request):
            seen.append(str(request.url))
            if request.url.path.endswith("openid-configuration"):
                return httpx.Response(
                    200,
                    json={
                        "issuer": ISSUER,
                        "jwks_uri": ISSUER + "/.well-known/jwks.json",
                    },
                )
            assert str(request.url) == ISSUER + "/.well-known/jwks.json"
            return httpx.Response(200, json={"keys": [jwk]})

        value = CognitoCache(ISSUER, RESOURCE, CLIENT)
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            assert await value.refresh(client)
        access = await value.verify_token(
            token(key, {"household_id": "invented", "role": "owner"})
        )
        assert access is not None
        assert access.subject == "linked-account-subject"
        assert access.client_id == CLIENT
        assert access.resource == RESOURCE
        assert access.scopes == ["hirz:read", "hirz:act"]
        assert "household_id" not in access.claims and "role" not in access.claims
        assert seen == [
            ISSUER + "/.well-known/openid-configuration",
            ISSUER + "/.well-known/jwks.json",
        ]

    asyncio.run(run())


@pytest.mark.parametrize(
    "changes",
    [
        {"iss": "https://other.example.test"},
        {"aud": "https://other.example.test/mcp"},
        {"aud": [RESOURCE]},
        {"client_id": "machine-client"},
        {"token_use": "id"},
        {"sub": ""},
        {"sub": True},
        {"scope": ["hirz/read"]},
        {"iat": True},
        {"exp": True},
        {"iat": 1, "exp": 2},
        {"iat": 2000000000, "exp": 2000000300},
        {"iat": int(time.time()) - 1},
        {"nbf": True},
        {"nbf": 2000000000},
    ],
)
def test_cognito_refuses_wrong_identity_resource_and_lifetime(key, changes):
    assert asyncio.run(cache(key).verify_token(token(key, changes))) is None


@pytest.mark.parametrize(
    "name", ["iss", "sub", "aud", "client_id", "scope", "token_use", "iat", "exp"]
)
def test_cognito_requires_bound_access_claims(key, name):
    assert asyncio.run(cache(key).verify_token(token(key, omit=(name,)))) is None


@pytest.mark.parametrize(
    "headers", [{"kid": "unknown"}, {"typ": "at+jwt"}, {"crit": ["custom"]}]
)
def test_cognito_refuses_unexpected_headers(key, headers):
    assert asyncio.run(cache(key).verify_token(token(key, headers=headers))) is None


def test_cognito_refuses_bad_signature_and_stale_keys(key):
    value = cache(key)
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert asyncio.run(value.verify_token(token(other))) is None
    value.updated -= 300
    with pytest.raises(AuthUnavailable):
        asyncio.run(value.verify_token(token(key)))


def test_unrelated_and_local_scopes_grant_no_hirz_authority(key):
    access = asyncio.run(
        cache(key).verify_token(
            token(key, {"scope": "openid hirz:act hirz-gateway/invoke"})
        )
    )
    assert access is not None and access.scopes == []
