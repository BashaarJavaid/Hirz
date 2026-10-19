"""Real passkey sessions, subject consent and atomic memory review over HTTP."""

import asyncio
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from test_companion_auth_database import enroll
from test_database import connect
from test_database import scratch_database as scratch_database
from test_pipeline_database import setup

from hirz.api.app import create_app
from hirz.audit import verify_database
from hirz.companion import auth, policy
from hirz.companion.api import Companion
from hirz.constitution.schema import dump
from hirz.graph.models import now
from hirz.memory.models import Candidate, TurnInput
from hirz.memory.service import MemoryService
from hirz.pipeline.audit import PipelineError
from hirz.pipeline.models import Principal
from tests.unit.test_companion_auth import CONFIG, Authenticator
from tests.unit.test_pipeline import ident

pytestmark = pytest.mark.integration


def test_authenticated_subject_consent_and_atomic_review(scratch_database):
    async def run():
        async with connect(scratch_database) as c:
            p = await setup(c, native=True)
            p.clock = now
            owner, subject = [
                await enroll(
                    p,
                    await auth.initial_invitation(p, ident("members", name)),
                    Authenticator(),
                )
                for name in ("malik", "mom")
            ]
            async with p.repo.write(p.clock):
                member = await auth.session(c, owner["session"], now())
                phone = member["principal"].model_copy(
                    update={"passkey_verified": True}
                )
                draft = await policy.draft(p, phone, dump(p.bundle.policy()))
                await policy.activate(
                    p, phone, draft["id"], draft["candidate_hash"], member["digest"]
                )
            principal = Principal(provider="demo", sub="mom", surface="app")
            memory = MemoryService(p)
            turn = await memory.record_turn(
                principal,
                action_id=uuid4().hex,
                turn=TurnInput(session_id="private", role="user", text="Private text"),
            )
            proposals = []
            for value in (73, 74, 75):
                result = await memory.propose(
                    principal,
                    action_id=uuid4().hex,
                    source_turn=turn.record.id,
                    candidate=Candidate(value=value, confidence=0.9),
                )
                assert result.decision.decision == "execute"
                proposals.append(result.record)
            with pytest.raises(PipelineError, match="owned Pipeline transaction"):
                await memory.review(
                    principal,
                    action_id="unowned",
                    proposal_id=proposals[0].id,
                    accept=True,
                    locked=True,
                )
            service = Companion(c.engine, p.audit, CONFIG)
            async with (
                service.boundary.persistent(),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=create_app(companion=service)),
                    base_url=CONFIG.origin,
                ) as client,
            ):
                body = {
                    "proposal_id": str(proposals[0].id),
                    "accept": True,
                    "request_id": "accept",
                }
                assert (await client.get("/api/memory/proposals")).status_code == 403
                assert (
                    await client.post("/api/memory/review", json=body)
                ).status_code == 403

                def login(session):
                    client.cookies.set(auth.SESSION_COOKIE, session)
                    client.cookies.set(auth.BROWSER_COOKIE, "memory-browser")
                    client.headers.update(
                        {"origin": CONFIG.origin, "x-hirz-csrf": auth.csrf(session)}
                    )

                login(owner["session"])
                assert (await client.get("/api/memory/proposals")).json() == []
                refused = await client.post("/api/memory/review", json=body)
                assert refused.json()["decision"]["decision"] == "deny"
                assert refused.json()["record"] is None

                login(subject["session"])
                body["request_id"] = "subject-accept"
                listed = await client.get("/api/memory/proposals", params={"limit": 1})
                assert listed.headers["cache-control"] == "no-store"
                assert [r["id"] for r in listed.json()] == [str(proposals[0].id)]
                assert "Private text" not in listed.text
                remaining = await client.get(
                    "/api/memory/proposals", params={"after": proposals[0].audit_seq}
                )
                assert len(remaining.json()) == 2
                for params in ({"limit": 101}, {"limit": 0}, {"after": -1}):
                    assert (
                        await client.get("/api/memory/proposals", params=params)
                    ).status_code == 422
                for extra in (
                    {"member_id": str(ident("members", "malik"))},
                    {"accept": "true"},
                    {"candidate": {"value": 99}},
                ):
                    assert (
                        await client.post("/api/memory/review", json=body | extra)
                    ).status_code == 422
                for headers in (
                    {"origin": "https://foreign.example"},
                    {"x-hirz-csrf": "wrong"},
                ):
                    assert (
                        await client.post(
                            "/api/memory/review", json=body, headers=headers
                        )
                    ).status_code == 403

                # Failure after the mutation must roll back consent and its effects.
                original = MemoryService.review

                async def fail_after_commit(self, *args, **kwargs):
                    result = await original(self, *args, **kwargs)
                    assert result.decision.decision == "execute", result.decision
                    raise ValueError("synthetic response failure")

                with patch.object(MemoryService, "review", fail_after_commit):
                    assert (
                        await client.post("/api/memory/review", json=body)
                    ).status_code == 403
                assert len((await client.get("/api/memory/proposals")).json()) == 3
                accepted = await client.post("/api/memory/review", json=body)
                assert accepted.headers["cache-control"] == "no-store"
                assert accepted.json()["record"]["status"] == "accepted", accepted.text
                replay = await client.post("/api/memory/review", json=body)
                assert replay.json()["decision"] == accepted.json()["decision"]
                opposite = await client.post(
                    "/api/memory/review", json=body | {"accept": False}
                )
                assert opposite.json()["decision"]["decision"] == "deny"
                stale = await client.post(
                    "/api/memory/review",
                    json=body
                    | {"proposal_id": str(proposals[1].id), "request_id": "stale"},
                )
                assert stale.json()["decision"]["decision"] == "deny"
                rejected = await client.post(
                    "/api/memory/review",
                    json=body
                    | {
                        "proposal_id": str(proposals[1].id),
                        "accept": False,
                        "request_id": "reject",
                    },
                )
                assert rejected.json()["record"]["status"] == "rejected"
                assert len((await client.get("/api/memory/proposals")).json()) == 1

                async with p.repo.write(p.clock):
                    member = await auth.session(c, subject["session"], now())
                    await auth.revoke(
                        p,
                        member["principal"].model_copy(
                            update={"passkey_verified": True}
                        ),
                        member["credential_id"],
                        True,
                    )
                assert (await client.get("/api/memory/proposals")).status_code == 403
                assert (
                    await client.post("/api/memory/review", json=body)
                ).status_code == 403
            snapshot = await p.snapshot(now())
            learned = [
                r
                for r in snapshot.data["preferences"]
                if r["member_id"] == str(ident("members", "mom"))
            ]
            assert len(learned) == 1 and learned[0]["value"] == 73
            assert learned[0]["source"] == "learned_accepted"
            await c.rollback()
            summary, rows = await verify_database(
                c, p.household_id, p.audit.key.public_key(), collect=True
            )
            assert summary["status"] == "valid"
            assert all("Private text" not in str(row.payload) for row in rows)
            await c.rollback()

    asyncio.run(run())
