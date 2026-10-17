"""Publication uses real Pipeline grants and disposable PostgreSQL transactions."""

import asyncio
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from test_companion_auth_database import enroll
from test_database import connect
from test_database import scratch_database as scratch_database
from test_pipeline_database import setup

from hirz import db
from hirz.aws.policy import Findings
from hirz.aws.publication import advance
from hirz.aws.routing import Route
from hirz.companion import auth, policy
from hirz.constitution.schema import dump
from tests.unit.test_companion_auth import Authenticator
from tests.unit.test_pipeline import POLICY, ident

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "failure", [None, "finding", "crash", "revoked", "restore", "audit"]
)
def test_queued_activation_and_recovery(scratch_database, failure):
    async def run():
        async with connect(scratch_database) as c:
            p = await setup(c, native=True)
            p.require_active = True
            login = await enroll(
                p,
                await auth.initial_invitation(p, ident("members", "malik")),
                Authenticator(),
            )
            async with c.begin():
                member = await auth.session(c, login["session"], p.clock())
            principal = member["principal"].model_copy(
                update={"passkey_verified": True}
            )
            if failure == "revoked":
                async with p.repo.write(p.clock):
                    initial = await policy.draft(p, principal, dump(POLICY))
                    await policy.activate(
                        p,
                        principal,
                        initial["id"],
                        initial["candidate_hash"],
                        member["digest"],
                    )
                from hirz.executor.local import policy as reload_policy

                p.bundle = await reload_policy(p)
            original_status = "active" if failure == "revoked" else "unvalidated"
            p.policy_route = Route(
                "engine",
                "arn:aws:bedrock-agentcore:us-east-1:123456789012:gateway/test",
                "https://example.test/mcp",
            )
            async with p.repo.write(p.clock):
                draft = await policy.draft(p, principal, dump(POLICY))
                assert (
                    await policy.activate(
                        p,
                        principal,
                        draft["id"],
                        draft["candidate_hash"],
                        member["digest"],
                    )
                    is None
                )
                assert (await policy.current(p))["status"] == original_status
            publisher = AsyncMock()
            publisher.step.return_value = True
            await advance(p, publisher)
            publisher.step.assert_not_called()
            async with c.begin():
                engine = (
                    (await c.execute(sa.select(db.policy_engines))).mappings().one()
                )
                assert not engine["ready"] and engine["generation"] == 1
            if failure in {"finding", "restore"}:
                publisher.step.side_effect = Findings(
                    {
                        "policyId": "bad",
                        "status": "CREATE_FAILED",
                        "statusReasons": ["always allow"],
                    }
                )
            if failure == "crash":
                publisher.step.side_effect = asyncio.CancelledError()
                with pytest.raises(asyncio.CancelledError):
                    await advance(p, publisher)
                publisher.step.side_effect = None
            if failure == "revoked":
                async with p.repo.write(p.clock):
                    await auth.revoke(p, principal, principal.credential_id, True)
            if failure == "audit":
                original = p.audit.append
                p.audit.append = AsyncMock(
                    side_effect=RuntimeError("audit unavailable")
                )
                with pytest.raises(RuntimeError):
                    await advance(p, publisher)
                p.audit.append = original
                publisher.step.assert_not_called()
                return
            await advance(p, publisher)
            if failure:
                async with c.begin():
                    assert (await policy.current(p))["status"] == original_status
                    assert not await c.scalar(sa.select(db.policy_engines.c.ready))
                if failure != "restore":
                    publisher.step.side_effect = None
                await advance(p, publisher)
            async with c.begin():
                job = (
                    (await c.execute(sa.select(db.policy_publications)))
                    .mappings()
                    .one()
                )
                engine = (
                    (await c.execute(sa.select(db.policy_engines))).mappings().one()
                )
                assert job["status"] == (
                    "committed"
                    if failure is None
                    else "blocked"
                    if failure == "restore"
                    else "failed"
                )
                assert engine["ready"] is (failure != "restore")
                assert (await policy.current(p))["status"] == (
                    "active" if failure is None else original_status
                )
                if failure == "finding":
                    assert job["findings"][0]["statusReasons"] == ["always allow"]

    asyncio.run(run())


def test_gateway_sessions_persist_and_conflicts_fail_closed(scratch_database):
    from hirz.aws.gateway import SessionConflict, Verdict
    from hirz.executor.local import policy as reload_policy
    from tests.unit.test_pipeline import PRINCIPAL, action

    async def run():
        async with connect(scratch_database) as c:
            p = await setup(c, native=True)
            login = await enroll(
                p,
                await auth.initial_invitation(p, ident("members", "malik")),
                Authenticator(),
            )
            async with c.begin():
                member = await auth.session(c, login["session"], p.clock())
            owner = member["principal"].model_copy(update={"passkey_verified": True})
            p.policy_route = Route(
                "engine",
                "arn:aws:bedrock-agentcore:us-east-1:123456789012:gateway/test",
                "https://example.test/mcp",
            )
            async with p.repo.write(p.clock):
                draft = await policy.draft(p, owner, dump(POLICY))
                await policy.activate(
                    p, owner, draft["id"], draft["candidate_hash"], member["digest"]
                )
            publisher = AsyncMock()
            publisher.step.return_value = True
            await advance(p, publisher)
            await advance(p, publisher)
            p.bundle = await reload_policy(p)
            p.gateway = AsyncMock()
            p.gateway.invoke.return_value = Verdict(
                True, "request", "trace", ("policy",), "ENFORCE", {"executed": False}
            )
            a = action()
            decision = await p.redeem(a, PRINCIPAL)
            assert decision.event_type == "DENY_BOUNDARY", decision
            assert decision.boundary.result == "allow", decision
            first = decision.boundary.requests[0].session_id
            decision = await p.redeem(a, PRINCIPAL)
            assert decision.boundary.requests[0].session_id == first
            p.gateway.invoke.side_effect = SessionConflict("changed")
            decision = await p.redeem(a, PRINCIPAL)
            assert decision.event_type == "DENY_BOUNDARY"
            assert "conflicted" in decision.boundary.reason
            calls = p.gateway.invoke.await_count
            await p.redeem(a, PRINCIPAL)
            assert p.gateway.invoke.await_count == calls
            async with c.begin():
                session = (
                    (await c.execute(sa.select(db.gateway_sessions))).mappings().one()
                )
                assert session["conflicted"] and session["session_id"] == first

    asyncio.run(run())


def test_queued_reviews_serialize_and_recheck_the_base(scratch_database):
    from hirz.executor.local import policy as reload_policy

    async def run():
        async with connect(scratch_database) as c:
            p = await setup(c, native=True)
            login = await enroll(
                p,
                await auth.initial_invitation(p, ident("members", "malik")),
                Authenticator(),
            )
            async with c.begin():
                member = await auth.session(c, login["session"], p.clock())
            owner = member["principal"].model_copy(update={"passkey_verified": True})
            p.policy_route = Route(
                "engine",
                "arn:aws:bedrock-agentcore:us-east-1:123456789012:gateway/test",
                "https://example.test/mcp",
            )
            drafts = []
            for _ in range(2):
                async with p.repo.write(p.clock):
                    draft = await policy.draft(p, owner, dump(POLICY))
                    drafts.append(draft)
                    await policy.activate(
                        p, owner, draft["id"], draft["candidate_hash"], member["digest"]
                    )
            with pytest.raises(policy.ReviewError, match="already has"):
                async with p.repo.write(p.clock):
                    await policy.activate(
                        p, owner, draft["id"], draft["candidate_hash"], member["digest"]
                    )
            publisher = AsyncMock()
            publisher.step.return_value = True
            await advance(p, publisher)
            await advance(p, publisher)
            p.bundle = await reload_policy(p)
            calls = publisher.step.await_count
            await advance(p, publisher)
            assert publisher.step.await_count == calls
            async with c.begin():
                jobs = (
                    (await c.execute(sa.select(db.policy_publications)))
                    .mappings()
                    .all()
                )
                assert {j["status"] for j in jobs} == {"committed", "failed"}
                failed = next(j for j in jobs if j["status"] == "failed")
                assert "Stale" in str(failed["findings"])
                assert await c.scalar(sa.select(db.policy_engines.c.ready))

    asyncio.run(run())
