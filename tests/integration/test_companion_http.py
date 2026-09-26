"""Authenticated HTTP isolation with real WebAuthn signatures and native governance."""

import asyncio
from pathlib import Path

import httpx
import pytest
from test_companion_auth_database import enroll
from test_database import connect
from test_database import scratch_database as scratch_database
from test_pipeline_database import setup
from webauthn.helpers import base64url_to_bytes

from hirz.api.app import create_app
from hirz.companion import auth, policy
from hirz.companion.api import Companion
from hirz.constitution.schema import dump
from hirz.graph.models import now
from hirz.graph.seeds import demo_id, load_seeds, read_seed
from tests.unit.test_companion_auth import CONFIG, Authenticator
from tests.unit.test_pipeline import ident

pytestmark = pytest.mark.integration


def test_authenticated_household_isolation_and_ceremony_binding(scratch_database):
    async def run():
        async with connect(scratch_database) as c:
            p = await setup(c, native=True)
            p.clock = now
            parent = read_seed(Path("constitutions/quinn-parents.yaml"))
            await load_seeds(c, [parent], now)
            service = Companion(c.engine, p.audit, CONFIG)
            owner_key, parent_key = Authenticator(), Authenticator()
            owner = await enroll(
                p,
                await auth.initial_invitation(p, ident("members", "malik")),
                owner_key,
            )
            parent_id = parent.household_id
            parent_owner = demo_id(
                parent.slug,
                "members",
                next(m["id"] for m in parent.graph["members"] if m["role"] == "owner"),
            )
            async with service.pipeline(parent_id) as q:
                other = await enroll(
                    q, await auth.initial_invitation(q, parent_owner), parent_key
                )
                async with q.repo.write(q.clock):
                    member = await auth.session(
                        q.connection, other["session"], q.clock()
                    )
                    draft = await policy.draft(
                        q, member["principal"], dump(q.bundle.policy())
                    )
            app = create_app(companion=service)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=CONFIG.origin
            ) as client:
                client.cookies.set(auth.SESSION_COOKIE, owner["session"])
                client.cookies.set(auth.BROWSER_COOKIE, "http-isolation-browser")
                client.headers.update(
                    {
                        "origin": CONFIG.origin,
                        "x-hirz-csrf": auth.csrf(owner["session"]),
                    }
                )
                for endpoint in (
                    "constitution",
                    "household",
                    "audit",
                    "approvals",
                    "twin",
                    "tonight",
                ):
                    response = await client.get(
                        f"/api/{endpoint}", params={"household_id": str(parent_id)}
                    )
                    assert response.status_code == 200, endpoint
                    assert str(parent_id) not in response.text
                for path, body in (
                    ("constitution/review", {"id": draft["id"]}),
                    ("constitution/dismiss", {"id": draft["id"]}),
                ):
                    assert (
                        await client.post(f"/api/{path}", json=body)
                    ).status_code == 403
                # A valid signature by another home's credential cannot finish a
                # ceremony bound to this session, even though both are real owners.
                begin = await client.post(
                    "/api/auth/begin",
                    json={
                        "operation": "activate",
                        "draft_id": draft["id"],
                        "candidate_hash": draft["candidate_hash"],
                    },
                )
                assert begin.status_code == 200
                options = begin.json()
                for key in (parent_key, owner_key):
                    response = await client.post(
                        "/api/auth/finish",
                        json={
                            "id": options["id"],
                            "credential": key.response(
                                base64url_to_bytes(options["publicKey"]["challenge"])
                            ),
                        },
                    )
                    assert response.status_code == 400
                # Fresh own signatures still cannot reach another household's IDs.
                for operation in (
                    {
                        "operation": "activate",
                        "draft_id": draft["id"],
                        "candidate_hash": draft["candidate_hash"],
                    },
                    {
                        "operation": "revoke",
                        "credential_id": member["principal"].credential_id,
                        "confirm_lockout": True,
                    },
                    {"operation": "reinvite", "member_id": str(parent_owner)},
                ):
                    options = (
                        await client.post("/api/auth/begin", json=operation)
                    ).json()
                    response = await client.post(
                        "/api/auth/finish",
                        json={
                            "id": options["id"],
                            "credential": owner_key.response(
                                base64url_to_bytes(options["publicKey"]["challenge"])
                            ),
                        },
                    )
                    assert response.status_code in {400, 409}
                # Authenticated cookies do not bypass CSRF or exact-origin checks.
                for headers in (
                    {"x-hirz-csrf": "wrong"},
                    {"origin": "https://evil.test"},
                ):
                    assert (
                        await client.post(
                            "/api/auth/begin",
                            json={"operation": "add_credential"},
                            headers=headers,
                        )
                    ).status_code == 400
            async with service.pipeline(parent_id) as q:
                async with q.connection.begin():
                    assert (await auth.session(q.connection, other["session"], now()))[
                        "member_id"
                    ] == parent_owner
                    assert (await policy.get(q, draft["id"]))["status"] == "ready"

    asyncio.run(run())
