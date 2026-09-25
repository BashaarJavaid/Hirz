"""Current account roles and concurrent request-local identity over disposable PG."""

import asyncio
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from hirz import db
from hirz.graph.models import now
from hirz.graph.seeds import load_seeds, read_seed, untouched
from hirz.mcp.auth import ISSUER, SCOPES, identity_context
from hirz.mcp.dev_oauth import create_issuer
from tests.integration.test_database import (  # noqa: F401
    connect,
    migrate,
    scratch_database,  # noqa: F401
)
from tests.unit.test_oauth import call, claims, consent, encode, gated, provider, tokens

pytestmark = pytest.mark.integration


def test_scope_household_roles_current_membership_and_no_writes(scratch_database):  # noqa: F811
    async def run():
        seeds = [
            read_seed(Path(f"constitutions/{name}.yaml"))
            for name in ("quinn-home", "quinn-parents")
        ]
        at = now()
        async with connect(scratch_database) as c:
            await migrate(c)
            await load_seeds(c, seeds, lambda: at)
        p = provider()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_issuer(p)), base_url=ISSUER
        ) as issuer:
            issued = [
                await tokens(issuer, choice=i, scopes=" ".join(SCOPES))
                for i in range(5)
            ]
            # A child can never approve a simulated link.
            p.choices[0] = replace(p.choices[0], role="child")
            assert (await consent(issuer))["error"] == ["access_denied"]
        for required in SCOPES:
            engine = create_async_engine(scratch_database, hide_parameters=True)
            async with gated(p, engine, required) as (client, cache):
                for i, t in enumerate(issued):
                    response = await client.post(
                        "/mcp",
                        json=call(),
                        headers={"authorization": "Bearer " + t["access_token"]},
                    )
                    assert response.status_code == 200
                    assert "structuredContent" in response.json()["result"], (
                        response.json()
                    )
                    value = response.json()["result"]["structuredContent"]["data"]
                    assert value["household"] == p.choices[i].household
                    assert value["role"] == ("owner" if i in (0, 3) else "adult")
                    assert (
                        value["surface"] == "alexa"
                        and value["passkey"] is False
                        and value["speaker"] is None
                    )
                wrong_scope = next(scope for scope in SCOPES if scope != required)
                response = await client.post(
                    "/mcp",
                    json=call(),
                    headers={
                        "authorization": "Bearer "
                        + encode(p, claims(p, scope=wrong_scope))
                    },
                )
                assert (
                    response.status_code == 403
                    and "insufficient_scope" in response.headers["www-authenticate"]
                )
                # Same subject has distinct membership/role per household, concurrently.
                responses = await asyncio.gather(
                    *(
                        client.post(
                            "/mcp",
                            json=call(),
                            headers={
                                "authorization": "Bearer " + issued[i]["access_token"]
                            },
                        )
                        for i in [1, 3] * 8
                    )
                )
                values = [
                    r.json()["result"]["structuredContent"]["data"] for r in responses
                ]
                assert all(
                    v["role"] == ("adult" if i % 2 == 0 else "owner")
                    for i, v in enumerate(values)
                )
                assert values[0]["member"] != values[1]["member"]
                assert identity_context.get() is None
        # No writes of any kind occurred during the real gate requests.
        async with connect(scratch_database) as c:
            assert all([await untouched(c, seed, at) for seed in seeds])
            assert (
                await c.scalar(sa.select(sa.func.count()).select_from(db.actions)) == 0
            )
        async with gated(
            p, create_async_engine(scratch_database, hide_parameters=True)
        ) as (client, _):
            # Token-supplied authority is ignored; real role is re-read each call.
            adult = encode(
                p,
                claims(
                    p,
                    sub="mom",
                    role="owner",
                    surface="app",
                    provider="admin",
                    passkey_verified=True,
                ),
            )
            response = await client.post(
                "/mcp", json=call(), headers={"authorization": "Bearer " + adult}
            )
            assert (
                response.json()["result"]["structuredContent"]["data"]["role"]
                == "adult"
            )
            for subject in ("unmapped", "malik-does-not-exist"):
                headers = {
                    "authorization": "Bearer " + encode(p, claims(p, sub=subject))
                }
                assert (
                    await client.post("/mcp", json=call(), headers=headers)
                ).status_code == 403
                assert (
                    await client.post(
                        "/mcp", json=call("what_can_you_do"), headers=headers
                    )
                ).status_code == 200
            # Rollback-only mutation simulates an externally committed membership change
            # through the same connection supplied to the resolver. No mutation is retained.
            async with connect(scratch_database) as c:
                async with c.begin():
                    await c.execute(
                        db.members.update()
                        .where(db.members.c.household_id == seeds[0].household_id)
                        .values(role="child")
                    )
                    import hirz.mcp.auth as auth

                    original = auth.resolve_member

                    async def current(connection, household, principal):
                        return await original(c, household, principal)

                    with pytest.MonkeyPatch.context() as patch:
                        patch.setattr(auth, "resolve_member", current)
                        assert (
                            await client.post(
                                "/mcp",
                                json=call(),
                                headers={"authorization": "Bearer " + adult},
                            )
                        ).status_code == 403
                        assert (
                            await client.post(
                                "/mcp",
                                json=call("what_can_you_do"),
                                headers={"authorization": "Bearer " + adult},
                            )
                        ).status_code == 200
                    await c.rollback()
            assert (
                await client.post(
                    "/mcp", json=call(), headers={"authorization": "Bearer " + adult}
                )
            ).status_code == 200

    asyncio.run(run())
