"""Publication uses real Pipeline grants and disposable PostgreSQL transactions."""

import asyncio
import json
from contextlib import aclosing, asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import sqlalchemy as sa
from test_companion_auth_database import enroll
from test_database import connect, migrate
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
    "minutes,bad_key", [(0, False), (31, False), (721, False), (31, True)]
)
def test_acceptance_activation_renews_expired_phone_session(
    scratch_database, monkeypatch, minutes, bad_key
):
    from hirz.aws.routing import Routing
    from hirz.companion import api
    from scripts import smoke_policy
    from tests.unit.test_pipeline import SEED

    async def run():
        async with connect(scratch_database) as c:
            p = await setup(c, native=True)
            start = at = smoke_policy.now()
            monkeypatch.setattr(api, "now", lambda: at)
            monkeypatch.setattr(auth, "now", lambda: at)
            p.clock = lambda: at
            route = Route(
                "engine",
                "arn:aws:bedrock-agentcore:us-east-1:123456789012:gateway/test",
                "https://example.test/mcp",
            )
            service = api.Companion(
                c.engine,
                p.audit,
                smoke_policy.CONFIG,
                policy_routes=Routing(frozenset({p.household_id}), frozenset(), route),
            )
            http, key = await smoke_policy.phone(service, p, SEED)
            async with aclosing(http):
                previous = http.cookies.get(auth.SESSION_COOKIE)
                if minutes > 720:
                    # Keep it active until the absolute limit; idle expiry is separate.
                    for minute in range(20, 720, 20):
                        at = start + timedelta(minutes=minute)
                        assert (await http.get("/api/auth/session")).json()[
                            "authenticated"
                        ]
                at = start + timedelta(minutes=minutes)
                if minutes:
                    refused = await http.post(
                        "/api/constitution/draft", json={"yaml": SEED.yaml}
                    )
                    assert refused.status_code == 403
                if bad_key:
                    with pytest.raises(httpx.HTTPStatusError) as error:
                        await smoke_policy.activate(
                            http, smoke_policy.Authenticator(), SEED.yaml
                        )
                    assert error.value.response.status_code == 400
                    async with c.begin():
                        assert (
                            await c.scalar(
                                sa.select(sa.func.count()).select_from(
                                    db.companion_drafts
                                )
                            )
                            == 0
                        )
                    return
                reference = await smoke_policy.activate(http, key, SEED.yaml)
                current = http.cookies.get(auth.SESSION_COOKIE)
                assert (current != previous) == bool(minutes)
                assert http.headers["x-hirz-csrf"] == auth.csrf(current)
                async with c.begin():
                    job = (
                        (await c.execute(sa.select(db.policy_publications)))
                        .mappings()
                        .one()
                    )
                    assert job["id"] == reference
                    assert job["status"] == "queued"

    asyncio.run(run())


def test_acceptance_phone_publication_failure_exports_audit(
    scratch_database, tmp_path, monkeypatch
):
    from scripts import smoke_policy

    @asynccontextmanager
    async def database(_):
        async with connect(scratch_database) as connection:
            await migrate(connection)
            yield connection

    publisher = AsyncMock()

    async def step(desired, *, recovering=False):
        if not recovering:
            raise Findings({"test_fixture": "publication refused"})
        assert desired == {}
        return True

    publisher.step.side_effect = step
    sdk = Mock()
    sdk.get_secret_value.return_value = {"SecretString": "test-only"}
    acceptance = SimpleNamespace(
        folder=tmp_path,
        outputs={
            "PolicyEngine": "engine",
            "GatewayArn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:gateway/test",
            "Gateway": "https://example.test/mcp",
            "GatewayTarget": "target",
            "MachineClient": "client",
            "MachineSecret": "secret",
        },
        client=lambda _: sdk,
        within_window=lambda: None,
    )
    monkeypatch.setattr(smoke_policy, "disposable", database)
    monkeypatch.setattr(smoke_policy, "Publisher", lambda *a, **kw: publisher)
    with pytest.raises(ValueError, match="Policy publication did not commit"):
        asyncio.run(smoke_policy.live(acceptance))
    job = json.loads((tmp_path / "item37-home-publication.json").read_text())
    assert job["status"] == "failed"
    assert job["findings"] == [{"test_fixture": "publication refused"}]
    assert len(list(tmp_path.glob("*-audit.json"))) == 2
    assert publisher.step.call_count == 2


@pytest.mark.parametrize(
    "failure",
    [None, "finding", "crash", "revoked", "restore", "audit", "sdk", "binding"],
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
                assert draft["review"]["engine"] == "agentcore-policy"
                assert p.policy_route.gateway_arn in draft["review"]["cedar"]
                assert "eventResource: resource" in draft["review"]["cedar"]
                assert "callerResource:" not in draft["review"]["cedar"]
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
            if failure == "binding":
                # Deliberate corruption probe: replace the initiating audit reference.
                async with c.begin():
                    await c.execute(
                        db.policy_publications.update().values(decision_seq=1)
                    )
            if failure in {"finding", "restore"}:
                publisher.step.side_effect = Findings(
                    {
                        "policyId": "bad",
                        "status": "CREATE_FAILED",
                        "statusReasons": ["always allow"],
                    }
                )
            if failure == "sdk":
                from botocore.exceptions import ClientError

                publisher.step.side_effect = ClientError(
                    {
                        "Error": {
                            "Code": "ValidationException",
                            "Message": "schema finding",
                        }
                    },
                    "CreatePolicy",
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
                if failure == "sdk":
                    assert job["findings"][0]["Error"]["Message"] == "schema finding"
                if failure == "binding":
                    assert "signed initiating binding" in str(job["findings"])

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
            p.gateway = AsyncMock()
            p.gateway.invoke.return_value = Verdict(
                True, "request", "trace", ("policy",), "ENFORCE", {"executed": False}
            )
            a = action()
            paused = await p.redeem(a, PRINCIPAL)
            assert (
                paused.event_type == "DENY_BOUNDARY"
                and "paused" in paused.boundary.reason
            )
            p.gateway.invoke.assert_not_awaited()
            await advance(p, publisher)
            p.bundle = await reload_policy(p)
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
            pending = await p.propose(
                action("security.door_unlock"),
                PRINCIPAL.model_copy(update={"requester_confirmed": True}),
            )
            assert pending.approval is not None
            deadline = pending.approval.expires_at
            async with p.repo.write(p.clock):
                draft = await policy.draft(p, owner, dump(POLICY))
                await policy.activate(
                    p, owner, draft["id"], draft["candidate_hash"], member["digest"]
                )
            await advance(p, publisher)
            await advance(p, publisher)
            p.bundle = await reload_policy(p)
            p.gateway.invoke.side_effect = None
            rotated = await p.redeem(a, PRINCIPAL)
            assert rotated.boundary.requests[0].session_id != first
            async with c.begin():
                replacement = (
                    (
                        await c.execute(
                            sa.select(db.approvals).where(
                                db.approvals.c.status == "pending"
                            )
                        )
                    )
                    .mappings()
                    .one()
                )
                assert replacement["expires_at"] == deadline
                assert replacement["approval_id"] != pending.approval.approval_id

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


@pytest.mark.parametrize("defect", [None, "forged", "audit", "recovery"])
def test_hard_deny_exception_is_durable_and_requires_signed_evidence(
    scratch_database, defect
):
    from hirz.aws.policy import HardDenyFinding
    from hirz.aws.publication import exceptions
    from tests.unit.aws.test_policy import hard_deny_row

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
            principal = member["principal"].model_copy(
                update={"passkey_verified": True}
            )
            p.policy_route = Route("engine", "test-gateway", "https://example.test/mcp")
            async with p.repo.write(p.clock):
                draft = await policy.draft(p, principal, dump(POLICY))
                await policy.activate(
                    p, principal, draft["id"], draft["candidate_hash"], member["digest"]
                )
            publisher = AsyncMock()
            await advance(p, publisher)
            rejected = hard_deny_row()
            publisher.step.side_effect = HardDenyFinding(rejected)
            if defect == "forged":
                async with c.begin():
                    await c.execute(
                        db.policy_publications.update().values(
                            findings=[{"accepted_hard_deny": rejected}]
                        )
                    )
            if defect == "audit":
                append = p.audit.append

                async def failing_append(*args, **kwargs):
                    if isinstance(args[-1], dict) and args[-1].get(
                        "hard_deny_exception"
                    ):
                        raise RuntimeError("exception audit unavailable")
                    return await append(*args, **kwargs)

                p.audit.append = failing_append
                with pytest.raises(RuntimeError, match="exception audit"):
                    await advance(p, publisher)
                p.audit.append = append
            else:
                await advance(p, publisher)
            async with c.begin():
                job = dict(
                    (await c.execute(sa.select(db.policy_publications)))
                    .mappings()
                    .one()
                )
                assert not await c.scalar(sa.select(db.policy_engines.c.ready))
                if defect == "forged":
                    publisher.step.assert_not_called()
                    with pytest.raises(sa.exc.NoResultFound):
                        await exceptions(p, job)
                elif defect == "audit":
                    assert job["findings"] == [] and job["status"] == "applying"
                else:
                    assert job["status"] == "publishing"
                    assert await exceptions(p, job) == [rejected]
            if defect in {"forged", "audit"}:
                return
            publisher = AsyncMock()  # A fresh worker has no in-memory exception state.
            publisher.step.return_value = True
            if defect == "recovery":
                publisher.step.side_effect = Findings({"statusReasons": ["unexpected"]})
                await advance(p, publisher)
                publisher.step.side_effect = None
            await advance(p, publisher)
            assert publisher.step.call_args.kwargs["exceptions"] == [rejected]
            async with c.begin():
                job = dict(
                    (await c.execute(sa.select(db.policy_publications)))
                    .mappings()
                    .one()
                )
                assert job["status"] == (
                    "failed" if defect == "recovery" else "committed"
                )
                assert await c.scalar(sa.select(db.policy_engines.c.ready))
                if defect is None:
                    activated = await c.scalar(
                        sa.select(db.audit_log.c.payload).where(
                            db.audit_log.c.event_type == "CONSTITUTION_ACTIVATED"
                        )
                    )
                    assert "hard-deny exceptions" in activated["analysis"]

    asyncio.run(run())
