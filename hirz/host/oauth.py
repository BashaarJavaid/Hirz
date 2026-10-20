"""Pinned Cognito login endpoints and current membership for the demo Echo labels."""

from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from addon_host import OAuthSession
from mcp.client.auth.utils import validate_metadata_issuer
from mcp.shared.auth import OAuthMetadata

from hirz.companion.api import Companion
from hirz.host.memory import identity
from hirz.mcp.auth import KeyCache
from hirz.mcp.dev_oauth import choices


@dataclass(repr=False, kw_only=True)
class CognitoSession(OAuthSession):
    login_origin: str

    def __post_init__(self) -> None:
        url = urlsplit(self.login_origin)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.path
            or url.query
            or url.fragment
        ):
            raise ValueError("Configure the exact HTTPS Cognito login origin")

    def _endpoint(self, url: str, base: str) -> str:
        # Cognito publishes login endpoints on a different origin from its issuer.
        # https://docs.aws.amazon.com/cognito/latest/developerguide/authorization-endpoint.html
        if base == self.config.issuer and url in {
            self.login_origin + "/oauth2/authorize",
            self.login_origin + "/oauth2/token",
        }:
            return url
        return super()._endpoint(url, base)

    async def _discover(self, http: httpx.AsyncClient) -> OAuthMetadata:
        try:
            return await super()._discover(http)
        except ValueError as exc:
            if str(exc) != "Issuer must support PKCE S256":
                raise
        # shortcut: addon-host 0.1 requires PKCE discovery that Cognito omits;
        # remove this adapter when the harness supports explicitly pinned Cognito.
        response = await http.get(
            self.config.issuer + "/.well-known/openid-configuration"
        )
        response.raise_for_status()
        metadata = OAuthMetadata.model_validate(response.json())
        validate_metadata_issuer(metadata, self.config.issuer)
        self._endpoint(str(metadata.authorization_endpoint), self.config.issuer)
        self._endpoint(str(metadata.token_endpoint), self.config.issuer)
        if metadata.code_challenge_methods_supported is not None:
            raise ValueError("Cognito metadata explicitly contradicts PKCE S256")
        # AWS documents S256 as its only PKCE method; begin() still requires it.
        return metadata.model_copy(
            update={"code_challenge_methods_supported": ["S256"]}
        )


async def linked(
    service: Companion, verifier: KeyCache, account: str, token: str
) -> None:
    current = await identity(service, verifier, token, required_scope="hirz:read")
    available = choices()
    household = next(
        choice.household
        for choice in available
        if choice.subject == ("mom" if account == "mom" else "malik")
        and choice.role == "owner"
    )
    expected = next(
        choice
        for choice in available
        if choice.subject == account and choice.household == household
    )
    if (
        str(current.household_id) != expected.household
        or current.member.member_id != expected.member_id
    ):
        raise ValueError("Choose the household account named by this Echo")
