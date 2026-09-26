"""WebAuthn ceremonies and credential lifecycle. No simulated login authority.

Verification contract: https://www.w3.org/TR/webauthn-3/#sctn-rp-operations
Tokens/challenges never enter the audit payload. Call credential mutations inside
one household Pipeline transaction, after consuming the browser-bound ceremony.
"""

import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialCreationOptions,
    PublicKeyCredentialDescriptor,
    PublicKeyCredentialRequestOptions,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from hirz import db
from hirz.companion.governance import credentials
from hirz.graph.models import now
from hirz.pipeline.models import Principal
from hirz.pipeline.service import Pipeline

SESSION_COOKIE = "__Host-hirz-session"
BROWSER_COOKIE = "__Host-hirz-browser"


def digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def csrf(token: str) -> str:
    return digest("hirz-csrf:" + token)


def same_origin_client(response: dict[str, Any]) -> None:
    data = json.loads(base64url_to_bytes(response["response"]["clientDataJSON"]))
    if data.get("crossOrigin", False) is not False or "topOrigin" in data:
        raise ValueError("Cross-origin credential ceremony refused")


@dataclass(frozen=True)
class Config:
    origin: str
    rp_id: str

    def __post_init__(self) -> None:
        parsed = urlsplit(self.origin)
        if (
            parsed.scheme != "https"
            or parsed.hostname != self.rp_id
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.netloc != self.rp_id
        ):
            raise ValueError(
                "Configure one exact HTTPS origin and matching RP hostname"
            )


def guard(
    config: Config,
    origin: str | None,
    token: str | None = None,
    supplied_csrf: str | None = None,
) -> None:
    if origin != config.origin:
        raise ValueError("Origin refused")
    if token is not None and not secrets.compare_digest(
        csrf(token), supplied_csrf or ""
    ):
        raise ValueError("CSRF refused")


async def account(c: AsyncConnection, household: UUID, member: UUID) -> Principal:
    row = (
        (
            await c.execute(
                sa.select(db.member_accounts)
                .join(
                    db.members,
                    sa.and_(
                        db.members.c.household_id == db.member_accounts.c.household_id,
                        db.members.c.id == db.member_accounts.c.member_id,
                    ),
                )
                .where(
                    db.member_accounts.c.household_id == household,
                    db.member_accounts.c.member_id == member,
                )
                .order_by(db.member_accounts.c.provider, db.member_accounts.c.sub)
                .limit(1)
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ValueError("A currently linked member is required")
    return Principal(provider=row["provider"], sub=row["sub"], surface="app")


async def initial_invitation(p: Pipeline, member: UUID) -> str:
    """Explicit local setup only. An enrolled member can never use this as reset."""
    async with p.repo.write(p.clock):
        await account(p.connection, p.household_id, member)
        enrolled = await p.connection.scalar(
            sa.select(db.member_passkeys.c.credential_id)
            .where(
                p.scope(db.member_passkeys), db.member_passkeys.c.member_id == member
            )
            .limit(1)
        )
        if enrolled:
            raise ValueError("Member already enrolled; use a passkey or recovery")
        await p.connection.execute(
            db.companion_enrollment.update()
            .where(
                p.scope(db.companion_enrollment),
                db.companion_enrollment.c.member_id == member,
                db.companion_enrollment.c.kind == "invitation",
                db.companion_enrollment.c.used_at.is_(None),
            )
            .values(used_at=p.clock())
        )
        token = secrets.token_urlsafe(32)
        await p.connection.execute(
            db.companion_enrollment.insert().values(
                digest=digest(token),
                household_id=p.household_id,
                member_id=member,
                kind="invitation",
                expires_at=p.clock() + timedelta(hours=24),
            )
        )
        return token


async def enrollment(
    c: AsyncConnection, token_digest: str, at: datetime
) -> dict[str, Any]:
    row = (
        (
            await c.execute(
                sa.select(db.companion_enrollment).where(
                    db.companion_enrollment.c.digest == token_digest,
                    db.companion_enrollment.c.used_at.is_(None),
                    sa.or_(
                        db.companion_enrollment.c.expires_at.is_(None),
                        db.companion_enrollment.c.expires_at > at,
                    ),
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ValueError("Enrollment link or recovery code is unavailable")
    return dict(row)


async def session(
    c: AsyncConnection, token: str, at: datetime, *, touch: bool = True
) -> dict[str, Any]:
    row = (
        (
            await c.execute(
                sa.select(
                    db.companion_sessions.c.digest,
                    db.member_passkeys.c.credential_id,
                    db.member_passkeys.c.household_id,
                    db.member_passkeys.c.member_id,
                    db.members.c.display_name,
                    db.members.c.role,
                )
                .select_from(db.companion_sessions)
                .join(db.member_passkeys)
                .join(
                    db.members,
                    sa.and_(
                        db.members.c.household_id == db.member_passkeys.c.household_id,
                        db.members.c.id == db.member_passkeys.c.member_id,
                    ),
                )
                .where(
                    db.companion_sessions.c.digest == digest(token),
                    db.companion_sessions.c.created_at > at - timedelta(hours=12),
                    db.companion_sessions.c.seen_at > at - timedelta(minutes=30),
                    db.member_passkeys.c.revoked_at.is_(None),
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ValueError("Sign in with a current passkey")
    principal = await account(c, row["household_id"], row["member_id"])
    if touch:
        await c.execute(
            db.companion_sessions.update()
            .where(db.companion_sessions.c.digest == row["digest"])
            .values(seen_at=at)
        )
    return dict(row) | {
        "principal": principal.model_copy(
            update={"credential_id": row["credential_id"]}
        )
    }


async def create_session(c: AsyncConnection, credential_id: str, at: datetime) -> str:
    token = secrets.token_urlsafe(32)
    await c.execute(
        db.companion_sessions.insert().values(
            digest=digest(token),
            credential_id=credential_id,
            created_at=at,
            seen_at=at,
        )
    )
    return token


async def ceremony(
    c: AsyncConnection,
    config: Config,
    browser: str,
    *,
    token: str | None = None,
    session_token: str | None = None,
    binding: dict[str, Any] | None = None,
    at: datetime | None = None,
) -> dict[str, Any]:
    at = at or now()
    challenge = secrets.token_bytes(32)
    options: PublicKeyCredentialCreationOptions | PublicKeyCredentialRequestOptions
    data: dict[str, Any] = {}
    current = await session(c, session_token, at) if session_token else None
    if token or binding == {"operation": "add_credential"}:
        if token:
            data = await enrollment(c, digest(token), at)
            data = {
                "enrollment": data["digest"],
                "household_id": str(data["household_id"]),
                "member_id": str(data["member_id"]),
            }
        elif current:
            data = {
                "household_id": str(current["household_id"]),
                "member_id": str(current["member_id"]),
            }
        else:
            raise ValueError(
                "Enrollment requires an invitation, recovery code or session"
            )
        household, member = UUID(data["household_id"]), UUID(data["member_id"])
        await account(c, household, member)
        name = await c.scalar(
            sa.select(db.members.c.display_name).where(
                db.members.c.household_id == household, db.members.c.id == member
            )
        )
        existing = (
            (
                await c.execute(
                    sa.select(db.member_passkeys.c.credential_id).where(
                        db.member_passkeys.c.household_id == household,
                        db.member_passkeys.c.member_id == member,
                    )
                )
            )
            .scalars()
            .all()
        )
        from webauthn.helpers import base64url_to_bytes

        options = generate_registration_options(
            rp_id=config.rp_id,
            rp_name="Hirz",
            user_name=str(name),
            user_id=household.bytes + member.bytes,
            challenge=challenge,
            timeout=300000,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
            exclude_credentials=[
                PublicKeyCredentialDescriptor(id=base64url_to_bytes(v))
                for v in existing
            ],
        )
        kind = "register"
    else:
        if binding and current is None:
            raise ValueError("Sign in before confirming an action")
        kind = "confirm" if binding else "login"
        data = binding or {}
        from webauthn.helpers import base64url_to_bytes

        options = generate_authentication_options(
            rp_id=config.rp_id,
            challenge=challenge,
            timeout=300000,
            user_verification=UserVerificationRequirement.REQUIRED,
            allow_credentials=[
                PublicKeyCredentialDescriptor(
                    id=base64url_to_bytes(current["credential_id"])
                )
            ]
            if current
            else [],
        )
    ceremony_id = secrets.token_urlsafe(32)
    await c.execute(
        db.companion_ceremonies.insert().values(
            id=ceremony_id,
            browser_digest=digest(browser),
            session_digest=digest(session_token) if session_token else None,
            kind=kind,
            challenge=challenge,
            binding=data,
            expires_at=at + timedelta(minutes=5),
        )
    )
    return {
        "id": ceremony_id,
        "kind": kind,
        "publicKey": json.loads(options_to_json(options)),
    }


async def consume(
    c: AsyncConnection,
    ceremony_id: str,
    browser: str,
    session_token: str | None,
    at: datetime,
) -> dict[str, Any]:
    """Commit consumption independently, including on failed verification."""
    row = (
        (
            await c.execute(
                db.companion_ceremonies.update()
                .where(
                    db.companion_ceremonies.c.id == ceremony_id,
                    db.companion_ceremonies.c.browser_digest == digest(browser),
                    db.companion_ceremonies.c.session_digest.is_(None)
                    if session_token is None
                    else db.companion_ceremonies.c.session_digest
                    == digest(session_token),
                    db.companion_ceremonies.c.used_at.is_(None),
                    db.companion_ceremonies.c.expires_at > at,
                )
                .values(used_at=at)
                .returning(db.companion_ceremonies)
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ValueError("Ceremony expired, used or bound to another browser")
    return dict(row)


async def assertion(
    c: AsyncConnection,
    config: Config,
    record: dict[str, Any],
    response: dict[str, Any],
    at: datetime,
) -> dict[str, Any]:
    if record["kind"] not in {"login", "confirm"} or at >= record["expires_at"]:
        raise ValueError("Wrong or expired ceremony")
    key = (
        (
            await c.execute(
                sa.select(db.member_passkeys)
                .where(
                    db.member_passkeys.c.credential_id == response.get("id"),
                    db.member_passkeys.c.revoked_at.is_(None),
                )
                .with_for_update()
            )
        )
        .mappings()
        .one_or_none()
    )
    if key is None:
        raise ValueError("Credential unavailable")
    if record["session_digest"]:
        bound = await c.scalar(
            sa.select(db.companion_sessions.c.credential_id).where(
                db.companion_sessions.c.digest == record["session_digest"],
                db.companion_sessions.c.created_at > at - timedelta(hours=12),
                db.companion_sessions.c.seen_at > at - timedelta(minutes=30),
            )
        )
        if bound != key["credential_id"]:
            raise ValueError("Assertion must use the session credential")
    same_origin_client(response)
    result = verify_authentication_response(
        credential=response,
        expected_challenge=record["challenge"],
        expected_rp_id=config.rp_id,
        expected_origin=config.origin,
        credential_public_key=key["public_key"],
        credential_current_sign_count=key["sign_count"],
        require_user_verification=True,
    )
    # The optional userHandle is an opaque server-created member binding.
    handle = response.get("response", {}).get("userHandle")
    if handle is not None and handle != bytes_to_base64url(
        key["household_id"].bytes + key["member_id"].bytes
    ):
        raise ValueError("Credential user handle mismatch")
    await account(c, key["household_id"], key["member_id"])
    await c.execute(
        db.member_passkeys.update()
        .where(db.member_passkeys.c.credential_id == key["credential_id"])
        .values(sign_count=result.new_sign_count)
    )
    return dict(key)


async def register(
    p: Pipeline,
    config: Config,
    record: dict[str, Any],
    response: dict[str, Any],
    label: str,
    session_token: str | None,
) -> dict[str, str]:
    at = p.clock()
    if (
        record["kind"] != "register"
        or at >= record["expires_at"]
        or not 1 <= len(label.strip()) <= 100
    ):
        raise ValueError("Invalid registration")
    data = record["binding"]
    household, member = UUID(data["household_id"]), UUID(data["member_id"])
    if household != p.household_id:
        raise ValueError("Wrong household")
    principal = await account(p.connection, household, member)
    grant = (
        await enrollment(p.connection, data["enrollment"], at)
        if data.get("enrollment")
        else None
    )
    if grant and (grant["household_id"], grant["member_id"]) != (household, member):
        raise ValueError("Enrollment binding changed")
    if grant is None:
        current = await session(p.connection, session_token or "", at)
        if (current["household_id"], current["member_id"], current["digest"]) != (
            household,
            member,
            record["session_digest"],
        ):
            raise ValueError("Enrollment session mismatch")
    previous = (
        (
            await p.connection.execute(
                sa.select(db.member_passkeys).where(
                    p.scope(db.member_passkeys),
                    db.member_passkeys.c.member_id == member,
                )
            )
        )
        .mappings()
        .all()
    )
    if grant and grant["kind"] == "invitation" and previous:
        raise ValueError("Invitation cannot reset an enrolled member")
    same_origin_client(response)
    verified = verify_registration_response(
        credential=response,
        expected_challenge=record["challenge"],
        expected_rp_id=config.rp_id,
        expected_origin=config.origin,
        require_user_presence=True,
        require_user_verification=True,
    )
    credential_id = bytes_to_base64url(verified.credential_id)
    recovering = grant is not None and grant["kind"] in {"recovery", "reinvite"}
    await credentials(
        p,
        principal.model_copy(update={"passkey_verified": True}),
        member,
        "recover" if recovering else "enroll",
    )
    if recovering:
        await revoke_keys(p, member)
    await p.connection.execute(
        db.member_passkeys.insert().values(
            credential_id=credential_id,
            household_id=household,
            member_id=member,
            public_key=verified.credential_public_key,
            sign_count=verified.sign_count,
            label=label.strip(),
            added_at=at,
        )
    )
    if grant:
        await p.connection.execute(
            db.companion_enrollment.update()
            .where(db.companion_enrollment.c.digest == grant["digest"])
            .values(used_at=at)
        )
    recovery = ""
    if not previous or recovering:
        await p.connection.execute(
            db.companion_enrollment.update()
            .where(
                p.scope(db.companion_enrollment),
                db.companion_enrollment.c.member_id == member,
                db.companion_enrollment.c.used_at.is_(None),
            )
            .values(used_at=at)
        )
        recovery = secrets.token_urlsafe(32)
        await p.connection.execute(
            db.companion_enrollment.insert().values(
                digest=digest(recovery),
                household_id=household,
                member_id=member,
                kind="recovery",
            )
        )
    return {
        "session": await create_session(p.connection, credential_id, at),
        "recovery_code": recovery,
    }


async def revoke_keys(
    p: Pipeline, member: UUID, credential_id: str | None = None
) -> None:
    keys = sa.select(db.member_passkeys.c.credential_id).where(
        p.scope(db.member_passkeys),
        db.member_passkeys.c.member_id == member,
    )
    if credential_id is not None:
        keys = keys.where(db.member_passkeys.c.credential_id == credential_id)
    await p.connection.execute(
        db.companion_sessions.delete().where(
            db.companion_sessions.c.credential_id.in_(keys)
        )
    )
    await p.connection.execute(
        db.member_passkeys.update()
        .where(db.member_passkeys.c.credential_id.in_(keys))
        .values(revoked_at=p.clock())
    )
    # Votes retain their history; eligibility and redemption recheck credential status.


async def revoke(
    p: Pipeline, principal: Principal, credential_id: str, confirm_lockout: bool
) -> None:
    row = (
        (
            await p.connection.execute(
                sa.select(db.member_passkeys).where(
                    p.scope(db.member_passkeys),
                    db.member_passkeys.c.credential_id == credential_id,
                    db.member_passkeys.c.revoked_at.is_(None),
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ValueError("Credential unavailable")
    remaining = await p.connection.scalar(
        sa.select(sa.func.count())
        .select_from(db.member_passkeys)
        .where(
            p.scope(db.member_passkeys),
            db.member_passkeys.c.member_id == row["member_id"],
            db.member_passkeys.c.revoked_at.is_(None),
        )
    )
    if remaining == 1 and not confirm_lockout:
        raise ValueError(
            "Confirm that revoking the last passkey can lock this member out"
        )
    await credentials(p, principal, row["member_id"], "revoke")
    await revoke_keys(p, row["member_id"], credential_id)


async def reinvite(p: Pipeline, principal: Principal, member: UUID) -> str:
    role = await p.connection.scalar(
        sa.select(db.members.c.role).where(
            p.scope(db.members), db.members.c.id == member
        )
    )
    if role is None or role == "owner":
        raise ValueError("Owner recovery requires a remaining passkey or recovery code")
    await account(p.connection, p.household_id, member)
    await credentials(p, principal, member, "reinvite")
    await p.connection.execute(
        db.companion_enrollment.update()
        .where(
            p.scope(db.companion_enrollment),
            db.companion_enrollment.c.member_id == member,
            db.companion_enrollment.c.kind == "reinvite",
            db.companion_enrollment.c.used_at.is_(None),
        )
        .values(used_at=p.clock())
    )
    token = secrets.token_urlsafe(32)
    await p.connection.execute(
        db.companion_enrollment.insert().values(
            digest=digest(token),
            household_id=p.household_id,
            member_id=member,
            kind="reinvite",
            expires_at=p.clock() + timedelta(hours=24),
        )
    )
    return token
