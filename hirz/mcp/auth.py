"""Local JWT verification and a request-aware gate ahead of FastMCP dispatch."""

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from hirz.graph.accounts import resolve_member
from hirz.local import LocalError
from hirz.mcp.transport import MAX_BODY_BYTES, check_text
from hirz.pipeline.models import Principal, Requester

RESOURCE = "http://127.0.0.1:8000/mcp"
ISSUER = "http://127.0.0.1:8001"
SCOPES = ("hirz:read", "hirz:plan", "hirz:act", "hirz:verify")


class AuthUnavailable(Exception):
    """Required authentication dependencies are unavailable; never become a guest."""


@dataclass(frozen=True)
class Identity:
    household_id: UUID
    principal: Principal
    member: Requester


identity_context: ContextVar[Identity | None] = ContextVar(
    "hirz_identity", default=None
)


class KeyCache:
    def __init__(
        self,
        issuer: str = ISSUER,
        resource: str = RESOURCE,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.issuer = issuer
        self.resource = resource
        self.clock = clock
        self.keys: dict[str, RSAPublicKey] = {}
        self.updated: float | None = None

    async def document(self, client: httpx.AsyncClient, url: str) -> dict[str, Any]:
        # One deadline includes connection, headers and the entire bounded body.
        async with asyncio.timeout(2):
            async with client.stream("GET", url, follow_redirects=False) as response:
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BODY_BYTES:
                        raise ValueError("Oversized issuer document")
        check_text(bytes(body))
        value = json.loads(body)
        if not isinstance(value, dict):
            raise ValueError("Invalid issuer document")
        return value

    async def refresh(self, client: httpx.AsyncClient) -> bool:
        try:
            metadata = await self.document(
                client, self.issuer + "/.well-known/oauth-authorization-server"
            )
            uri = metadata.get("jwks_uri")
            if metadata.get("issuer") != self.issuer or not isinstance(uri, str):
                raise ValueError("Invalid issuer metadata")
            origin, target = urlsplit(self.issuer), urlsplit(uri)
            if (
                (origin.scheme, origin.hostname, origin.port)
                != (target.scheme, target.hostname, target.port)
                or target.username is not None
                or target.password is not None
                or target.fragment
            ):
                raise ValueError("JWKS must have the configured issuer's origin")
            jwks = await self.document(client, uri)
            keys: dict[str, RSAPublicKey] = {}
            for value in jwks["keys"]:
                if (
                    value.get("kty") != "RSA"
                    or value.get("alg") != "RS256"
                    or value.get("use") != "sig"
                ):
                    continue
                kid = value.get("kid")
                if not isinstance(kid, str) or not kid or kid in keys or "d" in value:
                    raise ValueError("Invalid signing key")
                key = jwt.PyJWK.from_dict(value, algorithm="RS256").key
                if not isinstance(key, RSAPublicKey) or key.key_size < 2048:
                    raise ValueError("Invalid signing key")
                keys[kid] = key
            if not keys:
                raise ValueError("Missing signing keys")
        except (
            httpx.HTTPError,
            TimeoutError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            jwt.PyJWTError,
        ):
            return False
        self.keys, self.updated = keys, self.clock()
        return True

    @asynccontextmanager
    async def run(self) -> AsyncIterator[None]:
        async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
            await self.refresh(client)

            async def poll() -> None:
                while True:
                    await asyncio.sleep(60)
                    await self.refresh(client)

            task = asyncio.create_task(poll())
            try:
                yield
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def verify_token(self, token: str) -> AccessToken | None:
        if self.updated is None or self.clock() - self.updated >= 300:
            raise AuthUnavailable
        try:
            header = jwt.get_unverified_header(token)
            if (
                header.get("alg") != "RS256"
                or header.get("typ") != "at+jwt"
                or header.get("crit")
            ):
                return None
            kid = header.get("kid")
            if not isinstance(kid, str) or kid not in self.keys:
                return None
            claims = jwt.decode(
                token,
                self.keys[kid],
                algorithms=["RS256"],
                issuer=self.issuer,
                audience=self.resource,
                leeway=30,
                options={
                    "require": [
                        "iss",
                        "sub",
                        "aud",
                        "iat",
                        "exp",
                        "client_id",
                        "scope",
                        "household_id",
                    ],
                    "strict_aud": True,
                },
            )
            if any(
                type(claims[k]) is not str or not claims[k]
                for k in ("iss", "sub", "aud", "client_id", "scope", "household_id")
            ):
                return None
            if any(type(claims[k]) is not int for k in ("iat", "exp")):
                return None
            if "nbf" in claims and type(claims["nbf"]) is not int:
                return None
            if not 0 < claims["exp"] - claims["iat"] <= 300:
                return None
            if "nbf" in claims and claims["nbf"] > claims["exp"]:
                return None
            if claims["aud"] != self.resource or claims["iss"] != self.issuer:
                return None
            UUID(claims["household_id"])
            scopes = claims["scope"].split(" ")
            if not set(scopes) <= set(SCOPES):
                return None
            return AccessToken(
                token=token,
                client_id=claims["client_id"],
                scopes=scopes,
                expires_at=claims["exp"],
                resource=self.resource,
                subject=claims["sub"],
                claims=claims,
            )
        except (
            jwt.PyJWTError,
            ValueError,
            TypeError,
            KeyError,
            OverflowError,
            RecursionError,
        ):
            return None


class OAuthGate:
    """Body bounds/transport checks run first; this gate never fetches issuer keys."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        cache: KeyCache | None,
        engine: AsyncEngine | None,
        tool_scopes: dict[str, str],
    ) -> None:
        self.app, self.cache, self.engine = app, cache, engine
        self.tool_scopes = tool_scopes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] != "/mcp":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive)
        body = await request.body()
        required: str | None = None
        try:
            value = json.loads(body)
            if isinstance(value, dict) and value.get("method") == "tools/call":
                params = value.get("params")
                name = params.get("name") if isinstance(params, dict) else None
                if name != "what_can_you_do":
                    required = (
                        self.tool_scopes.get(name, "hirz:read")
                        if isinstance(name, str)
                        else "hirz:read"
                    )
        except (ValueError, TypeError):
            pass  # The SDK owns protocol errors, including unsupported batches.

        async def error(status: int, code: str, message: str) -> None:
            headers = {"Cache-Control": "no-store"}
            if status in (401, 403) and code in ("invalid_token", "insufficient_scope"):
                resource = self.cache.resource if self.cache else RESOURCE
                prm = (
                    resource.rsplit("/", 1)[0] + "/.well-known/oauth-protected-resource"
                )
                challenge = f'Bearer resource_metadata="{prm}", error="{code}"'
                if required:
                    challenge += f', scope="{required}"'
                headers["WWW-Authenticate"] = challenge
            await JSONResponse(
                {"error": code, "message": message}, status_code=status, headers=headers
            )(scope, receive, send)

        headers = request.headers.getlist("authorization")
        access: AccessToken | None = None
        identity: Identity | None = None
        if headers:
            if self.cache is None:
                await error(
                    503,
                    "temporarily_unavailable",
                    "Authentication is not configured in this preview.",
                )
                return
            if len(headers) != 1 or not re.fullmatch(
                r"Bearer [A-Za-z0-9_.~-]+", headers[0], re.IGNORECASE
            ):
                await error(401, "invalid_token", "Please link your account again.")
                return
            try:
                access = await self.cache.verify_token(headers[0][7:])
            except AuthUnavailable:
                await error(
                    503,
                    "temporarily_unavailable",
                    "Account verification is temporarily unavailable.",
                )
                return
            if access is None:
                await error(401, "invalid_token", "Please link your account again.")
                return
        if required:
            if access is None:
                await error(
                    401, "invalid_token", "Link your account to use household tools."
                )
                return
            if required not in access.scopes:
                await error(
                    403,
                    "insufficient_scope",
                    "Please approve the requested permission to use this tool.",
                )
                return
            try:
                if self.engine is None:
                    raise AuthUnavailable
                assert access.claims is not None and access.subject is not None
                household = UUID(access.claims["household_id"])
                principal = Principal(
                    provider="demo", sub=access.subject, surface="alexa"
                )
                async with asyncio.timeout(2):
                    async with self.engine.connect() as connection:
                        member = await resolve_member(connection, household, principal)
                identity = Identity(household, principal, member)
            except (
                AuthUnavailable,
                SQLAlchemyError,
                OSError,
                TimeoutError,
                LocalError,
            ):
                await error(
                    503,
                    "temporarily_unavailable",
                    "Household access is temporarily unavailable.",
                )
                return
            if member.member_id is None or member.role in ("child", "unknown"):
                await error(
                    403,
                    "account_not_linked",
                    "This account cannot access household tools. You can still ask what Hirz can do.",
                )
                return
        sent = False

        async def replay() -> Message:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        auth_token = auth_context_var.set(AuthenticatedUser(access) if access else None)
        identity_token = identity_context.set(identity)
        try:
            await self.app(scope, replay, send)
        finally:
            identity_context.reset(identity_token)
            auth_context_var.reset(auth_token)
