"""Self-link a verified Cognito login after the session's bound passkey ceremony."""

from hashlib import sha256
from uuid import UUID

import sqlalchemy as sa

from hirz import db
from hirz.aws.auth import CognitoCache
from hirz.companion.auth import digest
from hirz.companion.governance import credentials
from hirz.pipeline.models import Principal
from hirz.pipeline.service import Pipeline


async def binding(verifier: CognitoCache, token: str) -> dict[str, str]:
    access = await verifier.verify_token(token)
    if access is None or access.subject is None or "hirz:read" not in access.scopes:
        raise ValueError("A current resource-bound human login is required")
    return {
        "operation": "link_account",
        "token_digest": digest(token),
        "provider": verifier.issuer,
        "sub": access.subject,
    }


async def link(
    p: Pipeline,
    principal: Principal,
    verifier: CognitoCache,
    token: str,
    confirmed: dict[str, str],
) -> None:
    if (
        p.repo._at is None
        or principal.surface != "app"
        or not principal.passkey_verified
        or principal.credential_id is None
    ):
        raise ValueError("Linking requires an owned transaction and a fresh passkey")
    verified = await binding(verifier, token)
    if verified != confirmed:
        raise ValueError("The verified login differs from the passkey confirmation")
    member = await p.requester(principal)
    if (
        member.member_id is None
        or member.role == "child"
        or not await p.credential_current(principal)
    ):
        raise ValueError("A currently enrolled member is required")
    provider, sub = verified["provider"], verified["sub"]
    # Household locks alone cannot serialize competing cross-household links.
    key = int.from_bytes(
        sha256(("hirz:account-link:" + provider + "\0" + sub).encode()).digest()[:8],
        signed=True,
    )
    await p.connection.execute(
        sa.text("SELECT pg_advisory_xact_lock(:key)"), {"key": key}
    )
    if await p.connection.scalar(
        sa.select(db.member_accounts.c.member_id)
        .where(
            db.member_accounts.c.provider == provider, db.member_accounts.c.sub == sub
        )
        .limit(1)
    ):
        raise ValueError("Login is already linked; it cannot be reassigned")
    member_id = UUID(member.member_id)
    await credentials(p, principal, member_id, "enroll", account=(provider, sub))
    await p.connection.execute(
        db.member_accounts.insert().values(
            household_id=p.household_id,
            member_id=member_id,
            provider=provider,
            sub=sub,
        )
    )
