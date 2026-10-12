"""Courier publication uses durable native grants and household serialization."""

import asyncio
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from test_companion_auth_database import enroll
from test_database import connect
from test_database import scratch_database as scratch_database
from test_pipeline_database import setup

from hirz import db
from hirz.companion import auth
from hirz.constitution.schema import load
from hirz.contacts.secrets import Config
from hirz.contacts.service import Command, command
from hirz.graph.seeds import demo_id, load_seeds, read_seed
from hirz.mcp.household import HouseholdTools
from hirz.pipeline.models import VerificationCase
from hirz.pipeline.service import Pipeline, PolicyBundle
from hirz.protect.courier import advance, warnings
from tests.unit.test_companion_auth import Authenticator
from tests.unit.test_pipeline import AT, PRINCIPAL, ident, policy_edit, snapshot
from tests.unit.test_protect import SCAM

pytestmark = pytest.mark.integration


def fresh_worker(database, household, policy_yaml, key_pem, at):
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    from hirz.constitution.boundary import Dogwood
    from hirz.constitution.schema import loads
    from hirz.pipeline.audit import AuditWriter

    async def run():
        async with connect(database) as c:
            boundary = Dogwood()
            p = Pipeline(
                c,
                await PolicyBundle.validate(household, loads(policy_yaml), boundary),
                boundary,
                AuditWriter(load_pem_private_key(key_pem, password=None)),
                lambda: at,
            )
            await advance(p)

    try:
        asyncio.run(run())
    except Exception:
        raise SystemExit(
            "Courier restart check failed; private inputs withheld"
        ) from None


@pytest.mark.parametrize("mode", ["auto", "ask", "never"])
def test_independent_member_publication_and_restart(scratch_database, mode):
    async def run():
        async with connect(scratch_database) as c, connect(scratch_database) as other:
            snap = snapshot()
            bell = next(
                r for r in snap.data["observations"] if r["domain"] == "doorbell"
            )
            bell["state"]["last_press_at"] = AT.isoformat()
            p = await setup(
                c,
                policy_edit("communication.notify_member", mode=mode),
                native=True,
                snap=snap,
            )
            p.clock = lambda: AT
            tools = HouseholdTools(p, PRINCIPAL)
            result = await tools.call(
                "assess_request_risk",
                {"text": SCAM, "party": "person", "request_id": "courier"},
            )
            case_id = result.data.case.case_id
            q = Pipeline(other, p.bundle, p.boundary, p.audit, p.clock)
            await asyncio.gather(advance(p), advance(q))
            async with c.begin():
                document = await c.scalar(
                    sa.select(db.verification_cases.c.document).where(
                        db.verification_cases.c.id == case_id
                    )
                )
                state = VerificationCase.model_validate(document).courier
                assert state.contact.status == "stopped"
                assert state.contact.reason == "no_eligible_contact"
                assert (
                    state.member.status
                    == {"auto": "published", "ask": "approval", "never": "stopped"}[
                        mode
                    ]
                )
                inbox = await warnings(p, ident("members", "malik"))
                assert len(inbox) == (1 if mode == "auto" else 0)
                assert await warnings(p, ident("members", "dad")) == []
                before = await c.scalar(
                    sa.select(sa.func.count()).select_from(db.audit_log)
                )
            await advance(q)
            if mode == "auto":
                import multiprocessing

                from cryptography.hazmat.primitives import serialization

                from hirz.constitution.schema import dump

                child = multiprocessing.get_context("spawn").Process(
                    target=fresh_worker,
                    args=(
                        scratch_database,
                        p.household_id,
                        dump(p.bundle.policy()),
                        p.audit.key.private_bytes(
                            serialization.Encoding.PEM,
                            serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption(),
                        ),
                        AT,
                    ),
                )
                child.start()
                try:
                    await asyncio.to_thread(child.join, 20)
                    assert child.exitcode == 0
                finally:
                    if child.is_alive():
                        child.terminate()
                        await asyncio.to_thread(child.join, 5)
                    child.close()
            async with c.begin():
                assert (
                    await c.scalar(sa.select(sa.func.count()).select_from(db.audit_log))
                    == before
                )
            if mode == "ask":
                p.clock = lambda: AT + timedelta(minutes=5)
                await advance(p)
                async with c.begin():
                    document = await c.scalar(
                        sa.select(db.verification_cases.c.document).where(
                            db.verification_cases.c.id == case_id
                        )
                    )
                    assert document["courier"]["member"]["reason"] == "expired"

    asyncio.run(run())


def test_retry_case_and_reply_preserve_independent_courier_state(scratch_database):
    from test_database import migrate

    from hirz.executor.local import compose
    from hirz.executor.observations import ingest
    from hirz.mcp.persistence import command as case_command
    from hirz.pipeline.models import Principal
    from hirz.twin.execution import bootstrap
    from hirz.twin.scenario import LoadedScenario

    async def run():
        async with connect(scratch_database) as c:
            await migrate(c)
            loaded = LoadedScenario(Path("scenarios/parents-scam-check.yaml"))
            p = await bootstrap(loaded, c)
            principal = Principal(
                provider="demo", sub="mom", surface="app", requester_confirmed=True
            )
            registry = await compose(
                p, world=loaded.world, config="presence:twin,energy:twin"
            )
            await registry.start()
            try:
                await ingest(p, registry, principal)
                tools = HouseholdTools(p, principal)
                started = await tools.call(
                    "verify_trusted_identity",
                    {
                        "operation": "start",
                        "contact": "Malik",
                        "text": SCAM,
                        "request_id": "start",
                    },
                )
                loaded.world.clock.jump(loaded.world.clock() + timedelta(seconds=1))
                loaded.world.doorbell_event("doorbell.front_door", None, "press", None)
                await ingest(p, registry, principal)
                current = await tools.call(
                    "verify_trusted_identity",
                    {"operation": "status", "case_id": started.data.case.case_id},
                )
                original = current.data.case
                assert original.courier.member.status == "published"
                async with p.repo.write(p.clock):
                    await case_command(
                        p,
                        "record_verification",
                        {
                            "operation": "finish",
                            "case": original.model_copy(
                                update={
                                    "verification": original.verification.model_copy(
                                        update={"status": "genuine"}
                                    )
                                }
                            ).model_dump(mode="json"),
                        },
                        principal.model_copy(update={"surface": "scheduler"}),
                    )
                retried = await tools.call(
                    "verify_trusted_identity",
                    {
                        "operation": "retry",
                        "case_id": original.case_id,
                        "request_id": "retry",
                        "method": "app",
                    },
                )
                assert retried.data.case.courier is None
                assert retried.data.case.previous_case_id == original.case_id
                retained = await tools.call(
                    "verify_trusted_identity",
                    {"operation": "status", "case_id": original.case_id},
                )
                assert retained.data.case.courier == original.courier
                assert retained.data.case.verification.status == "genuine"
            finally:
                await registry.close()

    asyncio.run(run())


async def press(p):
    from hirz.executor.plans import governance
    from hirz.graph.repository import row_model
    from hirz.pipeline.hashing import digest

    async with p.connection.begin():
        row = (
            (
                await p.connection.execute(
                    sa.select(db.observations).where(
                        p.scope(db.observations),
                        db.observations.c.attributes["domain"].astext == "doorbell",
                    )
                )
            )
            .mappings()
            .one()
        )
    old = row_model("observations", row)
    reading = old.model_copy(
        update={
            "observed_at": p.clock(),
            "state": old.state.model_copy(update={"last_press_at": p.clock()}),
        }
    )
    principal = PRINCIPAL.model_copy(update={"surface": "scheduler"})
    p._observation_batch = (reading,)
    try:
        result = await p.redeem(
            governance(
                p,
                "record_observations",
                {"batch_hash": digest([reading.model_dump(mode="json")])},
                principal,
            ),
            principal,
        )
        assert result.decision == "execute"
    finally:
        p._observation_batch = None


@pytest.mark.parametrize("change", ["policy", "reject", "expired", "member_removed"])
def test_unsent_warning_stops_when_authority_changes(
    scratch_database, monkeypatch, change
):
    async def run():
        async with connect(scratch_database) as c:
            p = await setup(
                c, policy_edit("communication.notify_member", mode="ask"), native=True
            )
            clock = [p.clock()]
            p.clock = lambda: clock[0]
            tools = HouseholdTools(p, PRINCIPAL)
            result = await tools.call(
                "assess_request_risk",
                {"text": SCAM, "party": "person", "request_id": change},
            )
            clock[0] += timedelta(seconds=1)
            await press(p)
            await advance(p)
            if change == "policy":
                p.bundle = await PolicyBundle.validate(
                    p.household_id,
                    policy_edit("communication.notify_member", mode="never"),
                    p.boundary,
                )
            elif change == "reject":
                async with c.begin():
                    approval = (
                        (await c.execute(sa.select(db.approvals))).mappings().one()
                    )
                await tools.call(
                    "approve_action",
                    {
                        "action_id": approval["action_id"],
                        "approval_id": approval["approval_id"],
                        "approved": False,
                        "request_id": "reject-approval",
                    },
                )
            elif change == "member_removed":
                original_account = auth.account

                async def removed(connection, household, member):
                    if member == ident("members", "malik"):
                        raise ValueError("Member no longer linked")
                    return await original_account(connection, household, member)

                monkeypatch.setattr("hirz.protect.courier.account", removed)
            else:
                clock[0] += timedelta(minutes=5)
            await advance(p)
            async with c.begin():
                document = await c.scalar(
                    sa.select(db.verification_cases.c.document).where(
                        db.verification_cases.c.id == result.data.case.case_id
                    )
                )
                assert document["courier"]["member"]["status"] == "stopped"
                assert await warnings(p, ident("members", "malik")) == []

    asyncio.run(run())


def test_real_member_approval_deadline_uses_wall_time(scratch_database, monkeypatch):
    async def run():
        async with connect(scratch_database) as c:
            p = await setup(
                c,
                policy_edit(
                    "communication.notify_member", mode="ask", approval_ttl_minutes=1
                ),
                native=True,
            )
            wall = [p.clock()]
            monkeypatch.setattr("hirz.contacts.service.now", lambda: wall[0])
            await enroll(
                p,
                await auth.initial_invitation(p, ident("members", "malik")),
                Authenticator(),
            )
            tools = HouseholdTools(p, PRINCIPAL)
            result = await tools.call(
                "assess_request_risk",
                {"text": SCAM, "party": "organization", "request_id": "short-approval"},
            )
            await press(p)
            await advance(p)
            async with c.begin():
                before = await c.scalar(
                    sa.select(db.verification_cases.c.document).where(
                        db.verification_cases.c.id == result.data.case.case_id
                    )
                )
                assert before["courier"]["member"]["status"] == "approval"
                assert before["courier"]["contact"]["reason"] == "no_eligible_contact"
            wall[0] += timedelta(seconds=61)
            await advance(p)
            async with c.begin():
                after = await c.scalar(
                    sa.select(db.verification_cases.c.document).where(
                        db.verification_cases.c.id == result.data.case.case_id
                    )
                )
                assert after["courier"]["member"]["reason"] == "expired"
                assert await warnings(p, ident("members", "malik")) == []

    asyncio.run(run())


def test_multiple_cases_enrichment_and_audit_rollback(scratch_database, monkeypatch):
    from unittest.mock import patch

    from hirz.protect.advice import publish
    from hirz.protect.scoring import signals
    from hirz.protect.worker import transition

    async def run():
        async with connect(scratch_database) as c:
            p = await setup(c, native=True)
            clock = [p.clock()]
            p.clock = lambda: clock[0]
            tools = HouseholdTools(p, PRINCIPAL)
            ids = []
            for n in range(3):
                result = await tools.call(
                    "assess_request_risk",
                    {"text": SCAM, "party": "person", "request_id": str(n)},
                )
                ids.append(result.data.case.case_id)
            monkeypatch.setenv("HIRZ_LLM", "bedrock")
            later = await tools.call(
                "assess_request_risk",
                {
                    "text": "Please send dollars",
                    "party": "person",
                    "request_id": "enrich",
                },
            )
            clock[0] += timedelta(seconds=1)
            await press(p)
            with patch.object(
                p.audit, "append", side_effect=ValueError("audit unavailable")
            ):
                with pytest.raises(ValueError, match="audit unavailable"):
                    await advance(p)
            async with c.begin():
                assert await warnings(p, ident("members", "malik")) == []
            await advance(p)
            async with c.begin():
                assert len(await warnings(p, ident("members", "malik"))) == 3
            async with p.repo.write(p.clock):
                row = (
                    (
                        await c.execute(
                            sa.select(db.verification_cases).where(
                                db.verification_cases.c.id == later.data.case.case_id
                            )
                        )
                    )
                    .mappings()
                    .one()
                )
                case = VerificationCase.model_validate(row["document"])
                running = publish(
                    case,
                    case.extraction.model_copy(
                        update={"status": "running", "started_at": p.clock()}
                    ),
                )
                await transition(p, row, running)
                await transition(
                    p,
                    row,
                    publish(
                        running,
                        running.extraction.model_copy(
                            update={
                                "status": "complete",
                                "finished_at": p.clock(),
                                "model_signals": signals("strange number"),
                            }
                        ),
                    ),
                )
            await advance(p)
            async with c.begin():
                assert len(await warnings(p, ident("members", "malik"))) == 4
                before = await c.scalar(
                    sa.select(sa.func.count()).select_from(db.audit_log)
                )
            await advance(p)
            async with c.begin():
                assert (
                    await c.scalar(sa.select(sa.func.count()).select_from(db.audit_log))
                    == before
                )

    asyncio.run(run())


@pytest.mark.parametrize("contact_mode", ["auto", "ask", "never"])
@pytest.mark.parametrize("member_mode", ["auto", "ask", "never"])
def test_real_link_independent_permissions_and_private_projection(
    scratch_database, monkeypatch, contact_mode, member_mode
):
    async def run():
        async with connect(scratch_database) as c:
            snap = snapshot()
            bell = next(
                r for r in snap.data["observations"] if r["domain"] == "doorbell"
            )
            bell["state"]["last_press_at"] = AT.isoformat()
            policy = policy_edit(
                "communication.contact_trusted_contact", mode=contact_mode
            ).model_dump()
            policy["autonomy"]["communication"]["notify_member"]["mode"] = member_mode
            from hirz.constitution.schema import Constitution

            p = await setup(
                c, Constitution.model_validate(policy), native=True, snap=snap
            )
            p.clock = lambda: AT
            monkeypatch.setattr("hirz.contacts.service.now", lambda: AT)
            config = Config(Fernet.generate_key().decode(), "https://home.example")
            seed = read_seed(Path("constitutions/quinn-parents.yaml"))
            await load_seeds(c, [seed], lambda: AT - timedelta(seconds=1))
            q = Pipeline(
                c,
                await PolicyBundle.validate(
                    seed.household_id,
                    load(Path("constitutions/quinn-parents.yaml")),
                    p.boundary,
                ),
                p.boundary,
                p.audit,
                p.clock,
            )

            async def owner(pipeline, member_id):
                session = await enroll(
                    pipeline,
                    await auth.initial_invitation(pipeline, member_id),
                    Authenticator(),
                )
                async with c.begin():
                    current = await auth.session(c, session["session"], AT)
                return current["principal"].model_copy(
                    update={"passkey_verified": True, "requester_confirmed": True}
                )

            actor = await owner(p, ident("members", "malik"))
            target = demo_id(seed.slug, "members", "mom")
            recipient = await owner(q, target)
            async with p.repo.write(p.clock):
                created = await command(
                    p,
                    actor,
                    Command(
                        operation="create", name="Other owner", relationship="family"
                    ),
                    config,
                )
                contact = UUID(created["id"])
                invitation = await command(
                    p,
                    actor,
                    Command(operation="invite", contact_id=contact, method="app"),
                    config,
                )
            async with q.repo.write(q.clock):
                await command(
                    q,
                    recipient,
                    Command(operation="accept", value=invitation["invitation"]),
                    config,
                )
            async with p.repo.write(p.clock):
                await command(
                    p,
                    actor,
                    Command(
                        operation="confirm",
                        contact_id=contact,
                        reference=invitation["id"],
                    ),
                    config,
                )
            tools = HouseholdTools(p, actor)
            result = await tools.call(
                "assess_request_risk",
                {
                    "text": SCAM,
                    "claimed_party": "Other owner",
                    "party": "person",
                    "request_id": "real-courier",
                },
            )
            case_id = result.data.case.case_id
            await advance(p)
            async with c.begin():
                state = (
                    await c.scalar(
                        sa.select(db.verification_cases.c.document).where(
                            db.verification_cases.c.id == case_id
                        )
                    )
                )["courier"]
                assert (
                    state["member"]["status"]
                    == {"auto": "published", "ask": "approval", "never": "stopped"}[
                        member_mode
                    ]
                )
                assert (
                    state["contact"]["status"]
                    == {"auto": "published", "ask": "approval", "never": "stopped"}[
                        contact_mode
                    ]
                )
                assert (
                    await c.scalar(
                        sa.select(sa.func.count()).select_from(db.checkin_jobs)
                    )
                    == 0
                )
                assert await warnings(q, demo_id(seed.slug, "members", "dad")) == []
                approvals = (
                    (
                        await c.execute(
                            sa.select(db.approvals).where(
                                p.scope(db.approvals),
                                db.approvals.c.status == "pending",
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
            for approval in approvals:
                await tools.call(
                    "approve_action",
                    {
                        "action_id": approval["action_id"],
                        "approval_id": approval["approval_id"],
                        "approved": True,
                        "request_id": approval["approval_id"],
                    },
                )
            await advance(p)
            async with c.begin():
                inbox = await warnings(q, target)
                assert len(inbox) == (contact_mode != "never")
                if inbox:
                    assert inbox[0]["label"] == "Simulated doorbell event."
                    assert inbox[0]["delivery_source"] == "real"
                    assert "Malik reported a suspicious request." in inbox[0]["text"]
                    assert SCAM not in str(inbox) and "five hundred" not in str(inbox)
                    assert (
                        inbox[0]["expires_at"]
                        == (AT + timedelta(minutes=5)).isoformat()
                    )
                assert len(await warnings(p, ident("members", "malik"))) == (
                    member_mode != "never"
                )
            if member_mode == contact_mode == "auto":
                from unittest.mock import AsyncMock, patch

                from hirz.companion import push
                from tests.unit.test_companion_push import config as push_config
                from tests.unit.test_companion_push import subscription

                wall = [AT]
                monkeypatch.setattr("hirz.contacts.service.now", lambda: wall[0])
                settings = push_config()
                async with q.repo.write(q.clock):
                    await push.subscribe(
                        q,
                        recipient,
                        target,
                        push.Subscription.model_validate(subscription()),
                        settings,
                    )
                transport = AsyncMock(
                    side_effect=RuntimeError("controlled push failure")
                )
                with patch("pywebpush.webpush_async", transport):
                    for _ in range(4):
                        await push.advance(q, settings)
                        wall[0] += timedelta(seconds=61)
                assert transport.await_count == 3
                assert '"url": "/checkins"' in transport.call_args.kwargs["data"]
                async with c.begin():
                    assert len(await warnings(q, target)) == 1
                    assert (
                        await c.scalar(sa.select(db.companion_delivery.c.status))
                        == "failed"
                    )
                for n in range(3):
                    limited = await tools.call(
                        "assess_request_risk",
                        {
                            "text": SCAM,
                            "claimed_party": "Other owner",
                            "party": "person",
                            "request_id": f"limited-{n}",
                        },
                    )
                    await advance(p)
                async with c.begin():
                    assert len(await warnings(q, target)) == 3
                    document = await c.scalar(
                        sa.select(db.verification_cases.c.document).where(
                            db.verification_cases.c.id == limited.data.case.case_id
                        )
                    )
                    assert document["courier"]["member"]["status"] == "published"
                    assert document["courier"]["contact"]["status"] == "pending"
                wall[0] += timedelta(minutes=5)
                await advance(p)
                async with c.begin():
                    document = await c.scalar(
                        sa.select(db.verification_cases.c.document).where(
                            db.verification_cases.c.id == limited.data.case.case_id
                        )
                    )
                    assert document["courier"]["contact"]["reason"] == "expired"
                # Advancing only wall time clears the short cap but not the daily cap.
                for n in range(18):
                    wall[0] += timedelta(minutes=16)
                    daily = await tools.call(
                        "assess_request_risk",
                        {
                            "text": SCAM,
                            "claimed_party": "Other owner",
                            "party": "person",
                            "request_id": f"daily-{n}",
                        },
                    )
                    await advance(p)
                async with c.begin():
                    assert len(await warnings(q, target)) == 20
                    document = await c.scalar(
                        sa.select(db.verification_cases.c.document).where(
                            db.verification_cases.c.id == daily.data.case.case_id
                        )
                    )
                    assert document["courier"]["contact"]["status"] == "pending"
            pending = None
            if member_mode == "auto" and contact_mode == "ask":
                pending = await tools.call(
                    "assess_request_risk",
                    {
                        "text": SCAM,
                        "claimed_party": "Other owner",
                        "party": "person",
                        "request_id": "revoked-before-approval",
                    },
                )
                await advance(p)
            # Revocation removes retained contact warnings and cannot reroute to fixtures.
            async with p.repo.write(p.clock):
                await command(
                    p,
                    actor,
                    Command(
                        operation="revoke",
                        contact_id=contact,
                        reference=invitation["id"],
                    ),
                    config,
                )
            await advance(p)
            async with c.begin():
                assert await warnings(q, target) == []
                if pending:
                    document = await c.scalar(
                        sa.select(db.verification_cases.c.document).where(
                            db.verification_cases.c.id == pending.data.case.case_id
                        )
                    )
                    assert document["courier"]["member"]["status"] == "published"
                    assert document["courier"]["contact"]["reason"] == "channel_revoked"

    asyncio.run(run())
