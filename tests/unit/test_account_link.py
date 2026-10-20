"""Account proofs grant no authority without current credentials and a bound ceremony."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from hirz.companion import accounts
from hirz.mcp.auth import AuthUnavailable
from hirz.pipeline.models import Requester
from tests.unit.aws.test_auth import cache, token
from tests.unit.test_pipeline import PRINCIPAL


@pytest.mark.parametrize("claims", [{"scope": "openid hirz/act"}, {"iat": 1, "exp": 2}])
def test_link_proof_requires_read_scope_and_current_login(claims):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(ValueError, match="current resource-bound human login"):
        asyncio.run(accounts.binding(cache(key), token(key, claims)))


def test_link_proof_fails_closed_when_keys_are_stale():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier = cache(key)
    verifier.updated -= 300
    with pytest.raises(AuthUnavailable):
        asyncio.run(accounts.binding(verifier, token(key)))


@pytest.mark.parametrize("role,current", [("child", True), ("adult", False)])
def test_children_and_revoked_credentials_cannot_link(role, current):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    verifier, signed = cache(key), token(key)
    principal = PRINCIPAL.model_copy(
        update={"surface": "app", "passkey_verified": True, "credential_id": "enrolled"}
    )
    p = Mock()
    p.requester = AsyncMock(
        return_value=Requester(member_id="existing", role=role, surface="app")
    )
    p.credential_current = AsyncMock(return_value=current)

    async def run():
        with pytest.raises(ValueError, match="currently enrolled member"):
            await accounts.link(
                p, principal, verifier, signed, await accounts.binding(verifier, signed)
            )
        p.connection.execute.assert_not_called()

    asyncio.run(run())
