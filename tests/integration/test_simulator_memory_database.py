"""Simulator intake uses signed OAuth, current account mapping and audited grants."""

import asyncio
import time
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from test_companion_auth_database import enroll
from test_database import connect
from test_database import scratch_database as scratch_database
from test_pipeline_database import setup

from hirz import db
from hirz.api.app import create_app
from hirz.audit import verify_database
from hirz.companion import auth, policy
from hirz.companion.api import Companion
from hirz.constitution.schema import dump
from hirz.graph.models import now
from hirz.host.memory import record
from hirz.host.simulator import Simulator
from hirz.mcp.auth import ISSUER, RESOURCE, AuthUnavailable
from hirz.memory.models import TurnInput
from hirz.memory.service import MemoryService
from tests.unit.test_companion_auth import CONFIG, Authenticator
from tests.unit.test_oauth import cache_for, claims, encode, provider
from tests.unit.test_pipeline import HOME, PRINCIPAL, ident

pytestmark = pytest.mark.integration


def test_authenticated_private_turns_and_refusals(scratch_database):
    async def run():
        async with connect(scratch_database) as connection:
            p = await setup(connection, native=True)
            p.clock = now
            login = await enroll(
                p,
                await auth.initial_invitation(p, ident("members", "malik")),
                Authenticator(),
            )
            async with p.repo.write(p.clock):
                member = await auth.session(connection, login["session"], now())
                phone = member["principal"].model_copy(
                    update={"passkey_verified": True}
                )
                draft = await policy.draft(p, phone, dump(p.bundle.policy()))
                await policy.activate(
                    p, phone, draft["id"], draft["candidate_hash"], member["digest"]
                )
            issuer = provider()
            verifier = await cache_for(issuer)
            service = Companion(connection.engine, p.audit, CONFIG)
            simulator = Simulator(origin=CONFIG.origin, mcp_url=RESOURCE, issuer=ISSUER)
            create_app(companion=service, cache=verifier, simulator=simulator)
            assert simulator.memory is not None
            signed = encode(issuer, claims(issuer, scope="hirz:read hirz:plan"))
            listener = PRINCIPAL.model_copy(update={"surface": "alexa"})
            user = TurnInput(
                session_id="simulator:private-session",
                role="user",
                text="I prefer the room at 72 degrees.",
            )
            async with service.boundary.persistent():
                for turn in (
                    user,
                    user.model_copy(
                        update={"role": "assistant", "text": "Which room?"}
                    ),
                ):
                    await simulator.memory(signed, turn)
                stored = await MemoryService(p).turns(listener, user.session_id)
                assert [(t.role, t.text) for t in stored] == [
                    ("user", user.text),
                    ("assistant", "Which room?"),
                ]
                assert all(
                    t.session.household_id == HOME
                    and t.session.member_id == ident("members", "malik")
                    for t in stored
                )
                assert (
                    await MemoryService(p).turns(
                        listener.model_copy(update={"sub": "mom"}), user.session_id
                    )
                    == ()
                )
                for values in (
                    claims(issuer),
                    claims(issuer, scope="hirz:plan", aud="https://other.example/mcp"),
                    claims(
                        issuer,
                        scope="hirz:plan",
                        iat=int(time.time()) - 600,
                        exp=int(time.time()) - 300,
                    ),
                    claims(issuer, scope="hirz:plan", sub="not-linked"),
                ):
                    with pytest.raises(ValueError):
                        await record(service, verifier, encode(issuer, values), user)
                with pytest.raises(ValueError):
                    await record(service, verifier, signed + "tampered", user)
                updated = verifier.updated
                verifier.updated -= 301
                with pytest.raises(AuthUnavailable):
                    await record(service, verifier, signed, user)
                verifier.updated = updated
                writer = service.audit
                service.audit = AsyncMock(wraps=writer)
                service.audit.append.side_effect = RuntimeError(
                    "synthetic audit outage"
                )
                with pytest.raises(RuntimeError):
                    await record(service, verifier, signed, user)
                service.audit = writer
                assert await MemoryService(p).turns(listener, user.session_id) == stored
                assert await MemoryService(p).turns(PRINCIPAL, user.session_id) == ()
            summary, rows = await verify_database(
                connection, HOME, p.audit.key.public_key(), collect=True
            )
            assert summary["status"] == "valid"
            assert all(
                user.text not in str(row.payload) and signed not in str(row.payload)
                for row in rows
            )
            assert (
                await connection.scalar(
                    sa.select(sa.func.count()).select_from(db.memory_proposals)
                )
                == 0
            )
            await connection.rollback()

    asyncio.run(run())
