"""Verify resource-bound Cognito access tokens without granting household membership."""

import jwt
import sqlalchemy as sa
from mcp.server.auth.provider import AccessToken
from sqlalchemy.ext.asyncio import AsyncConnection

from hirz import db
from hirz.graph.accounts import resolve_member
from hirz.mcp.auth import SCOPES, AuthUnavailable, Identity, KeyCache
from hirz.pipeline.models import Principal


class CognitoCache(KeyCache):
    scope_names = {scope: scope.replace(":", "/") for scope in SCOPES}

    def __init__(
        self,
        issuer: str,
        resource: str,
        client_id: str,
        *,
        metadata_url: str | None = None,
    ) -> None:
        super().__init__(
            issuer,
            resource,
            discovery_path="/.well-known/openid-configuration",
            metadata_url=metadata_url,
        )
        if not client_id:
            raise ValueError("Cognito requires the configured human app client")
        self.client_id = client_id

    async def identity(
        self, connection: AsyncConnection, access: AccessToken
    ) -> Identity | None:
        assert access.subject is not None
        principal = Principal(provider=self.issuer, sub=access.subject, surface="alexa")
        households = (
            (
                await connection.execute(
                    sa.select(db.member_accounts.c.household_id)
                    .where(
                        db.member_accounts.c.provider == principal.provider,
                        db.member_accounts.c.sub == principal.sub,
                    )
                    .limit(2)
                )
            )
            .scalars()
            .all()
        )
        # V1 has no cross-household login; ambiguous links never select a home.
        if len(households) != 1:
            return None
        member = await resolve_member(connection, households[0], principal)
        return Identity(households[0], principal, member)

    async def verify_token(self, token: str) -> AccessToken | None:
        if self.updated is None or self.clock() - self.updated >= 300:
            raise AuthUnavailable
        try:
            header = jwt.get_unverified_header(token)
            if (
                header.get("alg") != "RS256"
                or header.get("typ") != "JWT"
                or header.get("crit")
            ):
                return None
            kid = header.get("kid")
            if not isinstance(kid, str) or kid not in self.keys:
                return None
            # Cognito resource binding: authorization requests supply resource=aud.
            # https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-define-resource-servers.html
            required = ("iss", "sub", "aud", "client_id", "scope", "token_use")
            claims = jwt.decode(
                token,
                self.keys[kid],
                algorithms=["RS256"],
                issuer=self.issuer,
                audience=self.resource,
                leeway=30,
                options={"require": [*required, "iat", "exp"], "strict_aud": True},
            )
            if any(type(claims[k]) is not str or not claims[k] for k in required):
                return None
            if (
                claims["client_id"] != self.client_id
                or claims["token_use"] != "access"
                or any(type(claims[k]) is not int for k in ("iat", "exp"))
                or not 0 < claims["exp"] - claims["iat"] <= 300
            ):
                return None
            if "nbf" in claims and (
                type(claims["nbf"]) is not int or claims["nbf"] > claims["exp"]
            ):
                return None
            granted = claims["scope"].split()
            scopes = [
                scope for scope, public in self.scope_names.items() if public in granted
            ]
            return AccessToken(
                token=token,
                client_id=self.client_id,
                scopes=scopes,
                expires_at=claims["exp"],
                resource=self.resource,
                subject=claims["sub"],
                # Membership and roles come from the linked-account graph only.
                claims={k: claims[k] for k in (*required, "iat", "exp")},
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
