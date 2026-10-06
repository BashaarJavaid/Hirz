"""Credential lifecycle and native governance in disposable PostgreSQL only."""

import asyncio
from datetime import timedelta

import pytest
import sqlalchemy as sa
from test_database import connect
from test_database import scratch_database as scratch_database
from test_pipeline_database import setup
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url

from hirz import db
from hirz.companion import auth
from hirz.companion.governance import credentials
from tests.unit.test_companion_auth import CONFIG, Authenticator
from tests.unit.test_pipeline import PRINCIPAL, ident

pytestmark = pytest.mark.integration


async def start(p, *, token=None, session=None, binding=None):
    async with p.connection.begin():
        return await auth.ceremony(
            p.connection,
            CONFIG,
            "browser",
            token=token,
            session_token=session,
            binding=binding,
            at=p.clock(),
        )


async def consume(p, options, session=None):
    async with p.connection.begin():
        return await auth.consume(
            p.connection, options["id"], "browser", session, p.clock()
        )


async def enroll(p, token, authenticator, *, session=None):
    options = await start(
        p,
        token=token,
        session=session,
        binding={"operation": "add_credential"} if session else None,
    )
    record = await consume(p, options, session)
    async with p.repo.write(p.clock):
        return await auth.register(
            p,
            CONFIG,
            record,
            authenticator.response(
                base64url_to_bytes(options["publicKey"]["challenge"]), register=True
            ),
            "Test passkey",
            session,
        )


def test_passkeys_recovery_sessions_and_governance(scratch_database):
    async def run():
        async with connect(scratch_database) as c:
            p = await setup(c, native=True)
            member = ident("members", "malik")
            invitation = await auth.initial_invitation(p, member)
            first = Authenticator()
            result = await enroll(p, invitation, first)
            assert result["recovery_code"]
            async with c.begin():
                current = await auth.session(c, result["session"], p.clock())
                assert current["member_id"] == member
                assert current["principal"].credential_id == bytes_to_base64url(
                    first.id
                )
            with pytest.raises(ValueError):
                await auth.initial_invitation(p, member)
            with pytest.raises(ValueError):
                await start(p, token=invitation)
            second = Authenticator()
            extra = await enroll(p, None, second, session=result["session"])
            assert not extra["recovery_code"]
            expired = await start(p)
            with pytest.raises(ValueError):
                async with c.begin():
                    await auth.consume(
                        c,
                        expired["id"],
                        "browser",
                        None,
                        p.clock() + timedelta(minutes=5),
                    )
            wrong_browser = await start(p)
            with pytest.raises(ValueError):
                async with c.begin():
                    await auth.consume(
                        c, wrong_browser["id"], "another-browser", None, p.clock()
                    )
            options = await start(p)
            record = await consume(p, options)
            with pytest.raises(ValueError):
                await consume(p, options)
            async with p.repo.write(p.clock):
                key = await auth.assertion(
                    c,
                    CONFIG,
                    record,
                    first.response(
                        base64url_to_bytes(options["publicKey"]["challenge"])
                    ),
                    p.clock(),
                )
                assert key["member_id"] == member
            async with p.repo.write(p.clock):
                await auth.revoke(
                    p,
                    current["principal"].model_copy(update={"passkey_verified": True}),
                    bytes_to_base64url(second.id),
                    False,
                )
                assert not await p.credential_current(
                    current["principal"].model_copy(
                        update={"credential_id": bytes_to_base64url(second.id)}
                    )
                )
            with pytest.raises(ValueError):
                async with c.begin():
                    await auth.session(c, extra["session"], p.clock())
            with pytest.raises(ValueError, match="last passkey"):
                async with p.repo.write(p.clock):
                    await auth.revoke(
                        p,
                        current["principal"].model_copy(
                            update={"passkey_verified": True}
                        ),
                        bytes_to_base64url(first.id),
                        False,
                    )
            replacement = await enroll(p, result["recovery_code"], Authenticator())
            assert replacement["recovery_code"] != result["recovery_code"]
            with pytest.raises(ValueError):
                async with c.begin():
                    await auth.session(c, result["session"], p.clock())
            with pytest.raises(ValueError):
                await start(p, token=result["recovery_code"])
            with pytest.raises(ValueError):
                async with p.repo.write(p.clock):
                    await credentials(p, PRINCIPAL, member, "enroll")
            async with c.begin():
                assert (
                    await c.scalar(sa.select(sa.func.count()).select_from(db.audit_log))
                    > 0
                )
                payloads = (
                    (await c.execute(sa.select(db.audit_log.c.payload))).scalars().all()
                )
                assert all(
                    result["recovery_code"] not in str(payload)
                    and invitation not in str(payload)
                    for payload in payloads
                )
                with pytest.raises(ValueError):
                    await auth.session(
                        c, replacement["session"], p.clock() + timedelta(minutes=30)
                    )

    asyncio.run(run())


def test_absolute_session_limit_and_owner_reinvitation(scratch_database):
    from hirz.companion import policy
    from hirz.constitution.schema import dump
    from hirz.executor.local import policy as reload_policy

    async def run():
        async with connect(scratch_database) as c:
            p = await setup(c, native=True)
            owner_id, adult_id = ident("members", "malik"), ident("members", "mom")
            owner = await enroll(
                p, await auth.initial_invitation(p, owner_id), Authenticator()
            )
            adult = await enroll(
                p, await auth.initial_invitation(p, adult_id), Authenticator()
            )
            async with c.begin():
                current = await auth.session(c, owner["session"], p.clock())
                other = await auth.session(c, adult["session"], p.clock())
            principal = current["principal"].model_copy(
                update={"passkey_verified": True}
            )
            async with p.repo.write(p.clock):
                draft = await policy.draft(p, principal, dump(p.bundle.policy()))
                await policy.activate(
                    p,
                    principal,
                    draft["id"],
                    draft["candidate_hash"],
                    current["digest"],
                )
            p.bundle = await reload_policy(p)
            for caller, target in (
                (principal, owner_id),
                (
                    other["principal"].model_copy(update={"passkey_verified": True}),
                    adult_id,
                ),
                (current["principal"], adult_id),
            ):
                with pytest.raises(ValueError):
                    async with p.repo.write(p.clock):
                        await auth.reinvite(p, caller, target)
            async with p.repo.write(p.clock):
                old = await auth.reinvite(p, principal, adult_id)
                replacement = await auth.reinvite(p, principal, adult_id)
            with pytest.raises(ValueError):
                await start(p, token=old)
            recovered = await enroll(p, replacement, Authenticator())
            assert recovered["recovery_code"]
            for token in (replacement, adult["recovery_code"]):
                with pytest.raises(ValueError):
                    await start(p, token=token)
            with pytest.raises(ValueError):
                async with c.begin():
                    await auth.session(c, adult["session"], p.clock())

            # Stay active every 20 minutes so only the absolute limit can expire it.
            for minutes in range(20, 720, 20):
                async with c.begin():
                    await auth.session(
                        c, owner["session"], p.clock() + timedelta(minutes=minutes)
                    )
            with pytest.raises(ValueError):
                async with c.begin():
                    await auth.session(
                        c, owner["session"], p.clock() + timedelta(hours=12)
                    )

    asyncio.run(run())
