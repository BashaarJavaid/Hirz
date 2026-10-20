"""Signed Cognito subjects resolve only through current, unambiguous graph links."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy.ext.asyncio import create_async_engine

from hirz import db
from hirz.api.app import create_app
from hirz.graph.models import now
from hirz.graph.seeds import demo_id, load_seeds, read_seed, untouched
from tests.integration.test_database import (  # noqa: F401
    connect,
    migrate,
    scratch_database,
)
from tests.mcp_transport import post
from tests.unit.aws.test_auth import ISSUER, cache, token
from tests.unit.test_oauth import HEADERS, call, oauth_probe

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("ambiguous", [False, True])
def test_cognito_scopes_links_and_claimed_household(scratch_database, ambiguous):  # noqa: F811
    async def run():
        seeds = [
            read_seed(Path(f"constitutions/quinn-{name}.yaml"))
            for name in ("home", "parents")
        ]
        at = now()
        async with connect(scratch_database) as connection:
            await migrate(connection)
            await load_seeds(connection, seeds, lambda: at)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        verifier = cache(key)
        verifier.metadata_url = "https://runtime.example.test/invocations/.well-known/oauth-protected-resource?qualifier=DEFAULT"

        @asynccontextmanager
        async def running():
            yield

        verifier.run = running
        engine = create_async_engine(scratch_database, hide_parameters=True)
        reauthorize = []

        def register(server):
            async def probe() -> dict[str, Any]:
                request = server._mcp_server.request_context.request
                reauthorize.append(request.scope["hirz_reauthorize"])
                return await oauth_probe()

            server.add_tool(probe, name="oauth_probe")

        app = create_app(cache=verifier, engine=engine, register=register)
        # Rollback-only account view; no unaudited account link is committed.
        async with connect(scratch_database) as links:
            async with links.begin():
                for index, seed in enumerate(seeds):
                    owner = next(
                        member
                        for member in seed.graph["members"]
                        if member["role"] == "owner"
                    )
                    await links.execute(
                        db.member_accounts.insert().values(
                            household_id=seed.household_id,
                            provider=ISSUER,
                            sub="shared" if ambiguous else f"subject-{index}",
                            member_id=demo_id(seed.slug, "members", owner["id"]),
                        )
                    )
                original = verifier.identity

                async def current(connection, access):
                    return await original(links, access)

                verifier.identity = current
                async with app.router.lifespan_context(app):
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(app),
                        base_url="http://127.0.0.1:8000",
                        headers=HEADERS,
                    ) as client:
                        metadata = await client.get(
                            "/.well-known/oauth-protected-resource"
                        )
                        assert metadata.json()["scopes_supported"] == [
                            "hirz/read",
                            "hirz/plan",
                            "hirz/act",
                            "hirz/verify",
                        ]
                        anonymous = await client.post("/mcp", json=call())
                        assert anonymous.status_code == 401
                        assert (
                            f'resource_metadata="{verifier.metadata_url}"'
                            in anonymous.headers["www-authenticate"]
                        )
                        assert (
                            'scope="hirz/read"' in anonymous.headers["www-authenticate"]
                        )
                        for index, seed in enumerate(seeds):
                            signed = token(
                                key,
                                {
                                    "sub": "shared"
                                    if ambiguous
                                    else f"subject-{index}",
                                    "household_id": str(seeds[1 - index].household_id),
                                    "provider": "demo",
                                    "role": "owner",
                                    "passkey_verified": True,
                                },
                            )
                            response = await post(
                                client,
                                "/mcp",
                                json=call(),
                                headers={"authorization": "Bearer " + signed},
                            )
                            assert response.status_code == (
                                403 if ambiguous else 200
                            ), response.text
                            if not ambiguous:
                                data = response.json()["result"]["structuredContent"][
                                    "data"
                                ]
                                assert data["household"] == str(seed.household_id)
                                assert (
                                    data["surface"] == "alexa"
                                    and data["passkey"] is False
                                )
                                assert data["speaker"] is None
                        for changes, status in [
                            ({"sub": "unlinked"}, 403),
                            ({"sub": "subject-0", "scope": "hirz/act"}, 403),
                            ({"sub": "subject-0", "client_id": "machine-client"}, 401),
                        ]:
                            response = await post(
                                client,
                                "/mcp",
                                json=call(),
                                headers={
                                    "authorization": "Bearer " + token(key, changes)
                                },
                            )
                            assert response.status_code == status
                        if not ambiguous:
                            assert (await reauthorize[0]()).household_id == seeds[
                                0
                            ].household_id
                            assert (await reauthorize[1]()).household_id == seeds[
                                1
                            ].household_id
                            await links.execute(
                                db.members.update()
                                .where(
                                    db.members.c.household_id == seeds[0].household_id
                                )
                                .values(role="child")
                            )
                            response = await post(
                                client,
                                "/mcp",
                                json=call(),
                                headers={
                                    "authorization": "Bearer "
                                    + token(key, {"sub": "subject-0"})
                                },
                            )
                            assert response.status_code == 403
                            with pytest.raises(ValueError, match="membership changed"):
                                await reauthorize[0]()
                            assert (await reauthorize[1]()).household_id == seeds[
                                1
                            ].household_id
                await links.rollback()
        async with connect(scratch_database) as connection:
            for seed in seeds:
                assert await untouched(connection, seed, at)

    asyncio.run(run())
