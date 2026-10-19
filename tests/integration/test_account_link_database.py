"""Cognito link backend: real passkeys, signed tokens, Pipeline grants and private audit."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
import sqlalchemy as sa
from cryptography.hazmat.primitives.asymmetric import rsa
from test_companion_auth_database import enroll
from test_database import connect
from test_database import scratch_database as scratch_database
from test_pipeline_database import setup
from webauthn.helpers import base64url_to_bytes

from hirz import db
from hirz.api.app import create_app
from hirz.audit import verify_database
from hirz.companion import accounts, auth
from hirz.companion.api import Companion
from hirz.graph.models import now
from hirz.graph.seeds import demo_id, load_seeds, read_seed
from tests.unit.aws.test_auth import ISSUER, cache, token
from tests.unit.test_companion_auth import CONFIG, Authenticator
from tests.unit.test_pipeline import ident

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "failure", [None, "token", "passkey", "session", "rollback", "revoked"]
)
@pytest.mark.parametrize("person", ["malik", "mom"])
def test_bound_self_link_and_atomic_audit(
    scratch_database, monkeypatch, failure, person
):
    async def run():
        async with connect(scratch_database) as c:
            p = await setup(c, native=True)
            p.clock = now
            key = Authenticator()
            login = await enroll(
                p, await auth.initial_invitation(p, ident("members", person)), key
            )
            rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            verifier = cache(rsa_key)
            service = Companion(
                c.engine,
                p.audit,
                CONFIG,
                account_verifier=verifier,
                account_login_origin="https://login.example.test",
            )
            signed = token(rsa_key)
            async with (
                service.boundary.persistent(),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(create_app(companion=service)),
                    base_url=CONFIG.origin,
                ) as http,
            ):
                http.cookies.set(auth.SESSION_COOKIE, login["session"])
                http.cookies.set(auth.BROWSER_COOKIE, "account-link-browser")
                http.headers.update(
                    {
                        "origin": CONFIG.origin,
                        "x-hirz-csrf": auth.csrf(login["session"]),
                    }
                )
                before = await http.get("/api/account-link")
                assert before.status_code == 200
                assert before.json()["linked"] is False
                assert before.json()["login"] == {
                    "origin": "https://login.example.test",
                    "client_id": verifier.client_id,
                    "resource": verifier.resource,
                    "redirect_uri": CONFIG.origin + "/account-link",
                }
                request = {
                    "operation": "link_account",
                    "account_token": signed,
                    "account_binding": before.json()["session_binding"],
                }
                assert (
                    await http.post(
                        "/api/auth/begin",
                        json=request | {"member_id": str(ident("members", person))},
                    )
                ).status_code == 422
                if failure == "session":
                    assert (
                        await http.post(
                            "/api/auth/begin",
                            json=request | {"account_binding": "0" * 64},
                        )
                    ).status_code == 400
                    return
                options = (await http.post("/api/auth/begin", json=request)).json()
                async with c.begin():
                    record = (
                        (
                            await c.execute(
                                sa.select(db.companion_ceremonies).where(
                                    db.companion_ceremonies.c.id == options["id"]
                                )
                            )
                        )
                        .mappings()
                        .one()
                    )
                    assert signed not in json.dumps(dict(record), default=str)
                    assert record["binding"]["token_digest"] == auth.digest(signed)
                if failure == "rollback":
                    original = accounts.link

                    async def crash(*args, **kwargs):
                        await original(*args, **kwargs)
                        raise RuntimeError("failure after graph and audit mutation")

                    monkeypatch.setattr(accounts, "link", crash)
                if failure == "revoked":
                    async with p.repo.write(p.clock):
                        member = await auth.session(c, login["session"], p.clock())
                        await auth.revoke(
                            p,
                            member["principal"].model_copy(
                                update={"passkey_verified": True}
                            ),
                            member["principal"].credential_id,
                            True,
                        )
                device = Authenticator() if failure == "passkey" else key
                finish = {
                    "id": options["id"],
                    "account_token": token(rsa_key, {"sub": "substituted"})
                    if failure == "token"
                    else signed,
                    "credential": device.response(
                        base64url_to_bytes(options["publicKey"]["challenge"])
                    ),
                }
                answer = await http.post("/api/auth/finish", json=finish)
                assert answer.status_code == (200 if failure is None else 400), (
                    answer.text
                )
                assert (
                    await http.post("/api/auth/finish", json=finish)
                ).status_code == 400
                after = await http.get("/api/account-link")
                if failure == "revoked":
                    assert after.status_code == 403
                else:
                    assert after.json()["linked"] is (failure is None)
                if failure is None:
                    # Even a fresh passkey cannot reassign an already-linked identity.
                    retry = (await http.post("/api/auth/begin", json=request)).json()
                    finish.update(
                        id=retry["id"],
                        credential=key.response(
                            base64url_to_bytes(retry["publicKey"]["challenge"])
                        ),
                    )
                    assert (
                        await http.post("/api/auth/finish", json=finish)
                    ).status_code == 400
            async with c.begin():
                rows = (
                    (
                        await c.execute(
                            sa.select(db.member_accounts).where(
                                db.member_accounts.c.provider == ISSUER
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
                assert len(rows) == (1 if failure is None else 0)
                if rows:
                    assert rows[0]["member_id"] == ident("members", person)
                grants = (
                    (
                        await c.execute(
                            sa.select(db.actions).where(
                                db.actions.c.proposal["params"][
                                    "credential_kind"
                                ].astext
                                == "cognito_link"
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
                assert len(grants) == (1 if failure is None else 0)
            _, audit = await verify_database(
                c, p.household_id, p.audit.key.public_key(), collect=True
            )
            serialized = json.dumps([r.payload for r in audit])
            assert signed not in serialized
            for grant in grants:
                event = next(r for r in audit if r.seq == grant["grant_seq"])
                assert event.payload["action_id"] == grant["action_id"]
                assert event.event_type == "EXECUTE"

    asyncio.run(run())


def test_same_login_cannot_race_into_two_households(scratch_database):
    async def run():
        async with connect(scratch_database) as c:
            p = await setup(c, native=True)
            p.clock = now
            parent = read_seed(Path("constitutions/quinn-parents.yaml"))
            await load_seeds(c, [parent], now)
            rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            verifier = cache(rsa_key)
            service = Companion(c.engine, p.audit, CONFIG, account_verifier=verifier)
            principals = []
            parent_owner = demo_id(
                parent.slug,
                "members",
                next(m["id"] for m in parent.graph["members"] if m["role"] == "owner"),
            )
            async with service.boundary.persistent():
                for household, member_id in (
                    (p.household_id, ident("members", "malik")),
                    (parent.household_id, parent_owner),
                ):
                    async with service.pipeline(household) as q:
                        login = await enroll(
                            q,
                            await auth.initial_invitation(q, member_id),
                            Authenticator(),
                        )
                        async with q.connection.begin():
                            member = await auth.session(
                                q.connection, login["session"], now()
                            )
                            principals.append(
                                (
                                    household,
                                    member["principal"].model_copy(
                                        update={"passkey_verified": True}
                                    ),
                                )
                            )
                signed = token(rsa_key)
                confirmed = await accounts.binding(verifier, signed)
                entered = 0
                ready = asyncio.Event()

                async def attempt(household, principal):
                    nonlocal entered
                    async with service.pipeline(household) as q:
                        async with q.repo.write(q.clock):
                            entered += 1
                            if entered == 2:
                                ready.set()
                            await ready.wait()
                            await accounts.link(
                                q, principal, verifier, signed, confirmed
                            )

                async with asyncio.timeout(15):
                    results = await asyncio.gather(
                        *(attempt(*pair) for pair in principals), return_exceptions=True
                    )
                assert sum(result is None for result in results) == 1, results
                refused = next(result for result in results if result is not None)
                assert isinstance(refused, ValueError) and "already linked" in str(
                    refused
                )
            async with c.begin():
                assert (
                    await c.scalar(
                        sa.select(sa.func.count())
                        .select_from(db.member_accounts)
                        .where(db.member_accounts.c.provider == ISSUER)
                    )
                    == 1
                )
            for household, _ in principals:
                await verify_database(c, household, p.audit.key.public_key())

    asyncio.run(run())
