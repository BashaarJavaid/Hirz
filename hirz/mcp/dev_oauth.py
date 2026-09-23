"""Loopback-only simulated login. Temporary grants never mutate the household graph."""

import hashlib
import html
import json
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp.server.auth.handlers.authorize import AuthorizationHandler
from mcp.server.auth.handlers.token import TokenHandler
from mcp.server.auth.middleware.client_auth import ClientAuthenticator
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp

from hirz.graph.models import now
from hirz.graph.seeds import read_seed
from hirz.local import LocalError
from hirz.mcp.auth import ISSUER, RESOURCE, SCOPES
from hirz.mcp.transport import MCPGuard, local_security

CALLBACK = "http://127.0.0.1:8765/callback"
KEY_NAME = "HIRZ_DEV_OAUTH_SIGNING_KEY"
LIMIT = 1024
NO_STORE = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
}


def signing_key(values: dict[str, str]) -> rsa.RSAPrivateKey:
    try:
        key = serialization.load_pem_private_key(
            values[KEY_NAME].encode(), password=None
        )
        if not isinstance(key, rsa.RSAPrivateKey) or key.key_size != 2048:
            raise ValueError
        return key
    except (KeyError, ValueError, TypeError):
        raise LocalError(
            "Dev OAuth requires an existing RSA-2048 private key; run dev_oauth.py init for a missing key, or restore the original malformed key."
        ) from None


def registered_client(callback: str = CALLBACK) -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id="hirz-dev-sdk",
        redirect_uris=[AnyUrl(callback)],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope=" ".join(SCOPES),
    )


@dataclass(frozen=True)
class Choice:
    household: str
    subject: str
    label: str
    role: str


def choices() -> list[Choice]:
    result = []
    for name in ("quinn-home", "quinn-parents"):
        seed = read_seed(Path("constitutions") / f"{name}.yaml")
        models = seed.models(now())
        members = {str(m.id): m for m in models["members"]}  # type: ignore[attr-defined]
        for account in models["member_accounts"]:
            data = account.model_dump()
            member = members[str(data["member_id"])].model_dump()
            result.append(
                Choice(
                    str(seed.household_id),
                    data["sub"],
                    f"{member['display_name']} — {seed.graph['household']['name']}",
                    member["role"],
                )
            )
    return result


@dataclass
class Consent:
    params: AuthorizationParams
    expires_at: float
    csrf: str


class Code(AuthorizationCode):
    household: str


class Grant(RefreshToken):
    household: str
    family: str


@dataclass
class Family:
    current: Grant
    secret: bytes
    generation: int = 0
    revoked: bool = False


class DevProvider:
    def __init__(
        self,
        key: rsa.RSAPrivateKey,
        *,
        issuer: str = ISSUER,
        resource: str = RESOURCE,
        callback: str = CALLBACK,
    ) -> None:
        self.key, self.issuer, self.resource = key, issuer, resource
        self.client = registered_client(callback)
        self.callback = callback
        self.choices = choices()
        self.pending: dict[str, Consent] = {}
        self.codes: dict[str, Code] = {}
        self.families: dict[str, Family] = {}
        public = key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        self.kid = hashlib.sha256(public).hexdigest()

    def purge(self) -> None:
        at = time.time()
        self.pending = {k: v for k, v in self.pending.items() if v.expires_at > at}
        self.codes = {k: v for k, v in self.codes.items() if v.expires_at > at}
        self.families = {
            k: v
            for k, v in self.families.items()
            if v.current.expires_at is not None and v.current.expires_at > at
        }

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self.client if client_id == self.client.client_id else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        raise NotImplementedError("Static registration only")

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        self.purge()
        if len(self.pending) >= LIMIT:
            raise AuthorizeError("temporarily_unavailable", "Too many pending consents")
        transaction = secrets.token_urlsafe(32)
        params = params.model_copy(
            update={
                "scopes": params.scopes if params.scopes is not None else ["hirz:read"]
            }
        )
        self.pending[transaction] = Consent(
            params, time.time() + 300, secrets.token_urlsafe(32)
        )
        return self.issuer + "/consent?" + urlencode({"transaction": transaction})

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> Code | None:
        self.purge()
        return self.codes.get(authorization_code)

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: Code
    ) -> OAuthToken:
        self.purge()
        if len(self.families) >= LIMIT:
            raise TokenError("invalid_grant", "Too many active grants; try later")
        code = self.codes.pop(authorization_code.code, None)
        if code is None:
            raise TokenError(
                "invalid_grant", "Authorization code expired or already used"
            )
        family_id = secrets.token_urlsafe(32)
        grant = Grant(
            token="",
            client_id=code.client_id,
            scopes=code.scopes,
            expires_at=int(time.time()) + 8 * 3600,
            resource=code.resource,
            subject=code.subject,
            household=code.household,
            family=family_id,
        )
        family = Family(grant, secrets.token_bytes(32))
        grant.token = self.refresh_value(family_id, family)
        self.families[family_id] = family
        return self.issue(grant)

    @staticmethod
    def refresh_value(family_id: str, family: Family) -> str:
        # Authenticated generation counters retain replay detection in constant space
        # per family; no unbounded list of spent refresh tokens.
        import hmac

        generation = str(family.generation)
        tag = hmac.new(family.secret, generation.encode(), hashlib.sha256).hexdigest()
        return f"{family_id}.{generation}.{tag}"

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> Grant | None:
        import hmac

        self.purge()
        parts = refresh_token.split(".")
        if len(parts) != 3 or not re.fullmatch(r"0|[1-9][0-9]{0,10}", parts[1]):
            return None
        family = self.families.get(parts[0])
        if family is None or family.revoked:
            return None
        tag = hmac.new(family.secret, parts[1].encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(tag, parts[2]):
            return None
        if int(parts[1]) != family.generation:
            family.revoked = True
            return None
        return family.current

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: Grant,
        scopes: list[str],
    ) -> OAuthToken:
        # No await between checking and rotation: atomic on this single-process AS.
        self.purge()
        family = self.families.get(refresh_token.family)
        if family is None or family.revoked:
            raise TokenError("invalid_grant", "Refresh family unavailable")
        if family.current.token != refresh_token.token:
            family.revoked = True
            raise TokenError("invalid_grant", "Refresh token already used")
        if not scopes or not set(scopes) <= set(refresh_token.scopes):
            raise TokenError("invalid_scope", "Refresh cannot add permissions")
        family.generation += 1
        family.current = refresh_token.model_copy(
            update={
                "scopes": scopes,
                "token": self.refresh_value(refresh_token.family, family),
            }
        )
        return self.issue(family.current)

    def issue(self, grant: Grant) -> OAuthToken:
        at = int(time.time())
        access = jwt.encode(
            {
                "iss": self.issuer,
                "sub": grant.subject,
                "aud": grant.resource,
                "iat": at,
                "exp": at + 300,
                "client_id": grant.client_id,
                "scope": " ".join(grant.scopes),
                "household_id": grant.household,
            },
            self.key,
            algorithm="RS256",
            headers={"kid": self.kid, "typ": "at+jwt"},
        )
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=300,
            refresh_token=grant.token,
            scope=" ".join(grant.scopes),
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        raise NotImplementedError("Resource server validates JWTs independently")

    async def revoke_token(self, token: AccessToken | Grant) -> None:
        raise NotImplementedError("No revocation endpoint")

    async def consent(self, request: Request) -> Response:
        self.purge()
        params = (
            request.query_params if request.method == "GET" else await request.form()
        )
        transaction = str(params.get("transaction", ""))
        pending = self.pending.get(transaction)
        if pending is None:
            return JSONResponse(
                {"error": "invalid_request"}, status_code=400, headers=NO_STORE
            )
        if request.method == "GET":
            options = "".join(
                f'<option value="{i}" {"disabled" if c.role == "child" else ""}>{html.escape(c.label)}</option>'
                for i, c in enumerate(self.choices)
            )
            scopes = html.escape(" ".join(pending.params.scopes or []))
            response = HTMLResponse(
                f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Hirz simulated login</title><main><h1>Hirz simulated login</h1><p>Local development only. Choose a synthetic member and home.</p><p>Requested scopes: <strong>{scopes}</strong></p><form method="post" action="/consent"><input type="hidden" name="transaction" value="{html.escape(transaction)}"><input type="hidden" name="csrf" value="{pending.csrf}"><label for="member">Member and home</label> <select id="member" name="member">{options}</select><p><button name="decision" value="approve">Approve</button> <button name="decision" value="deny">Deny</button></p></form></main></html>''',
                headers=NO_STORE
                | {
                    # no-referrer makes browser form POST Origin null; preserve
                    # same-origin CSRF checks without leaking cross-origin URLs.
                    "Referrer-Policy": "same-origin",
                    "Content-Security-Policy": f"default-src 'none'; form-action 'self' {self.callback}; frame-ancestors 'none'; base-uri 'none'",
                },
            )
            response.set_cookie(
                "hirz_dev_consent",
                transaction,
                max_age=300,
                httponly=True,
                samesite="strict",
                path="/consent",
            )
            return response
        if (
            request.headers.get("origin") not in (None, self.issuer)
            or request.cookies.get("hirz_dev_consent") != transaction
            or not secrets.compare_digest(str(params.get("csrf", "")), pending.csrf)
            or any(len(params.getlist(k)) != 1 for k in params)
        ):
            return JSONResponse(
                {"error": "invalid_request"}, status_code=400, headers=NO_STORE
            )
        self.pending.pop(transaction)
        target = str(pending.params.redirect_uri)
        state = pending.params.state
        if params.get("decision") != "approve":
            return RedirectResponse(
                construct_redirect_uri(target, error="access_denied", state=state),
                status_code=302,
                headers=NO_STORE,
            )
        try:
            member = int(str(params.get("member", "")))
            if (
                not 0 <= member < len(self.choices)
                or self.choices[member].role == "child"
            ):
                raise ValueError
        except ValueError:
            return RedirectResponse(
                construct_redirect_uri(target, error="access_denied", state=state),
                status_code=302,
                headers=NO_STORE,
            )
        if len(self.codes) >= LIMIT:
            return RedirectResponse(
                construct_redirect_uri(
                    target, error="temporarily_unavailable", state=state
                ),
                status_code=302,
                headers=NO_STORE,
            )
        choice = self.choices[member]
        code = secrets.token_urlsafe(32)
        self.codes[code] = Code(
            code=code,
            scopes=pending.params.scopes or ["hirz:read"],
            expires_at=time.time() + 60,
            client_id="hirz-dev-sdk",
            code_challenge=pending.params.code_challenge,
            redirect_uri=pending.params.redirect_uri,
            redirect_uri_provided_explicitly=True,
            resource=self.resource,
            subject=choice.subject,
            household=choice.household,
        )
        return RedirectResponse(
            construct_redirect_uri(target, code=code, state=state),
            status_code=302,
            headers=NO_STORE,
        )


def create_issuer(provider: DevProvider, *, port: int = 8001) -> ASGIApp:
    authorize = AuthorizationHandler(provider)
    token = TokenHandler(provider, ClientAuthenticator(provider))

    async def checked(request: Request) -> Response:
        params = (
            request.query_params if request.method == "GET" else await request.form()
        )
        error = None
        if any(len(params.getlist(k)) != 1 for k in params):
            error = "invalid_request"
        elif request.url.path == "/authorize":
            if params.get("redirect_uri") != provider.callback:
                error = "invalid_request"
            elif params.get("code_challenge_method") != "S256" or not re.fullmatch(
                r"[A-Za-z0-9_-]{43}", str(params.get("code_challenge", ""))
            ):
                error = "invalid_request"
            elif params.get("resource") != provider.resource:
                error = "invalid_target"
        else:
            refresh = params.get("grant_type") == "refresh_token"
            resource = params.get("resource")
            if (not refresh or resource is not None) and resource != provider.resource:
                error = "invalid_target"
            elif not refresh and params.get("redirect_uri") != provider.callback:
                error = "invalid_request"
            elif not refresh and not re.fullmatch(
                r"[A-Za-z0-9._~-]{43,128}", str(params.get("code_verifier", ""))
            ):
                error = "invalid_request"
        if error:
            return JSONResponse({"error": error}, status_code=400, headers=NO_STORE)
        return await (
            authorize.handle(request)
            if request.url.path == "/authorize"
            else token.handle(request)
        )

    async def metadata(request: Request) -> Response:
        return JSONResponse(
            {
                "issuer": provider.issuer,
                "authorization_endpoint": provider.issuer + "/authorize",
                "token_endpoint": provider.issuer + "/token",
                "jwks_uri": provider.issuer + "/.well-known/jwks.json",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "token_endpoint_auth_methods_supported": ["none"],
                "code_challenge_methods_supported": ["S256"],
                "scopes_supported": list(SCOPES),
            },
            headers=NO_STORE,
        )

    async def jwks(request: Request) -> Response:
        key: dict[str, Any] = json.loads(
            jwt.algorithms.RSAAlgorithm.to_jwk(provider.key.public_key())
        )
        return JSONResponse(
            {"keys": [key | {"kid": provider.kid, "alg": "RS256", "use": "sig"}]},
            headers=NO_STORE,
        )

    app = Starlette(
        routes=[
            Route("/.well-known/oauth-authorization-server", metadata),
            Route("/.well-known/jwks.json", jwks),
            Route("/authorize", checked, methods=["GET", "POST"]),
            Route("/token", checked, methods=["POST"]),
            Route("/consent", provider.consent, methods=["GET", "POST"]),
        ]
    )
    return MCPGuard(app, local_security(port))
