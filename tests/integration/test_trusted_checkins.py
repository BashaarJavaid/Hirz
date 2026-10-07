"""Real-channel services in disposable databases with signed native Pipeline decisions."""

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
from hirz.contacts import checkins
from hirz.contacts.secrets import Config
from hirz.contacts.service import Command, command, guess
from hirz.graph.seeds import demo_id, load_seeds, read_seed
from hirz.mcp.household import HouseholdTools
from hirz.mcp.trust import advance as simulated
from hirz.pipeline.service import Pipeline, PolicyBundle
from tests.unit.test_companion_auth import Authenticator
from tests.unit.test_pipeline import ident, policy_edit

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("mode", ["auto", "ask"])
@pytest.mark.parametrize("answer", ["genuine", "not_genuine", "will_call", "no_answer"])
def test_real_cross_household_receipt_isolation_and_deadline(
    scratch_database, monkeypatch, answer, mode, tmp_path
):
    config = Config(Fernet.generate_key().decode(), "https://home.example")
    monkeypatch.setenv("HIRZ_CONTACT_ENCRYPTION_KEY", config.encryption_key)
    monkeypatch.setenv("HIRZ_COMPANION_ORIGIN", config.origin)

    async def run():
        async with connect(scratch_database) as c:
            p = await setup(
                c,
                policy_edit("communication.contact_trusted_contact", mode=mode),
                native=True,
            )
            clock = [p.clock()]
            monkeypatch.setattr("hirz.contacts.service.now", lambda: clock[0])
            p.clock = lambda: clock[0]
            seed = read_seed(Path("constitutions/quinn-parents.yaml"))
            await load_seeds(c, [seed], lambda: clock[0] - timedelta(seconds=1))
            q = Pipeline(
                c,
                await PolicyBundle.validate(
                    seed.household_id,
                    load(Path("constitutions/quinn-parents.yaml")),
                    p.boundary,
                ),
                p.boundary,
                p.audit,
                lambda: clock[0],
            )

            async def owner(pipeline, member_id):
                session = await enroll(
                    pipeline,
                    await auth.initial_invitation(pipeline, member_id),
                    Authenticator(),
                )
                async with c.begin():
                    current = await auth.session(c, session["session"], clock[0])
                return current["principal"].model_copy(
                    update={"passkey_verified": True, "requester_confirmed": True}
                )

            actor = await owner(p, ident("members", "malik"))
            recipient = await owner(q, demo_id(seed.slug, "members", "mom"))
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
            with pytest.raises(ValueError):
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
                await command(
                    p,
                    actor,
                    Command(operation="word", contact_id=contact, value="CaféSecret"),
                    config,
                )
            tools = HouseholdTools(p, actor)
            started = await tools.call(
                "verify_trusted_identity",
                {
                    "operation": "start",
                    "contact": str(contact),
                    "text": "Did you request five hundred dollars?",
                    "request_id": "real-start",
                },
            )
            case = started.data.case
            if mode == "ask":
                assert case.verification is None
                async with c.begin():
                    assert (
                        await c.scalar(sa.select(db.checkin_jobs.c.expires_at)) is None
                    )
                clock[0] += timedelta(minutes=3)
                approved = await tools.call(
                    "approve_action",
                    {
                        "action_id": started.data.decision.action_id,
                        "approval_id": started.data.decision.approval.approval_id,
                        "approved": True,
                        "request_id": "approve-real",
                    },
                )
                assert approved.data.decision.decision == "execute", approved
                started = await tools.call(
                    "verify_trusted_identity",
                    {"operation": "status", "case_id": case.case_id},
                )
                case = started.data.case
                assert case.verification.expires_at == clock[0] + timedelta(minutes=2)
            assert case.verification.source == "real", started
            assert "number" not in case.claim.model_dump_json(exclude_none=True)
            async with c.begin():
                job = dict(
                    (
                        await c.execute(
                            sa.select(db.checkin_jobs).where(
                                db.checkin_jobs.c.case_id == case.case_id
                            )
                        )
                    )
                    .mappings()
                    .one()
                )
            # No simulated worker can close an explicitly real case.
            await simulated(p, None)
            await checkins.advance(p)
            with pytest.raises(ValueError):
                await HouseholdTools(q, recipient).call(
                    "verify_trusted_identity",
                    {"operation": "status", "case_id": case.case_id},
                )
            with pytest.raises(ValueError):
                async with p.repo.write(p.clock):
                    await command(
                        p,
                        actor,
                        Command(
                            operation="reply",
                            reference=job["id"],
                            request_hash=job["request_hash"],
                            answer="genuine",
                        ),
                        config,
                    )
            with pytest.raises(ValueError):
                async with q.repo.write(q.clock):
                    await command(
                        q,
                        recipient,
                        Command(
                            operation="reply",
                            reference=job["id"],
                            request_hash="changed",
                            answer="genuine",
                        ),
                        config,
                    )
            async with p.repo.write(p.clock):
                assert (await guess(p, actor, case.case_id, "Cafe\u0301Secret"))[
                    "matches"
                ]
                for _ in range(4):
                    assert not (await guess(p, actor, case.case_id, "incorrect"))[
                        "matches"
                    ]
                assert (await guess(p, actor, case.case_id, "CaféSecret"))["limited"]
            if answer != "no_answer":
                async with q.repo.write(q.clock):
                    value = Command(
                        operation="reply",
                        reference=job["id"],
                        request_hash=job["request_hash"],
                        answer=answer,
                    )
                    assert (await command(q, recipient, value, config))["ok"]
                    assert (await command(q, recipient, value, config))["ok"]
                with pytest.raises(ValueError):
                    async with q.repo.write(q.clock):
                        await command(
                            q,
                            recipient,
                            value.model_copy(
                                update={
                                    "answer": "will_call"
                                    if answer != "will_call"
                                    else "not_genuine"
                                }
                            ),
                            config,
                        )
            # Revocation serializes with accepted receipts; an earlier receipt wins.
            if answer == "will_call":
                async with q.repo.write(q.clock):
                    await command(
                        q,
                        recipient,
                        Command(operation="withdraw", reference=invitation["id"]),
                        config,
                    )
            clock[0] += timedelta(minutes=3)
            await checkins.advance(p)
            result = await tools.call(
                "verify_trusted_identity",
                {"operation": "status", "case_id": case.case_id},
            )
            assert result.data.case.verification.status == answer
            assert result.data.case.risk_band == case.risk_band
            if answer == "no_answer":
                assert "saved in your own phone" in result.speakable.headline
            async with c.begin():
                payloads = str(
                    (await c.execute(sa.select(db.audit_log.c.payload))).scalars().all()
                )
                assert (
                    "CaféSecret" not in payloads
                    and invitation["invitation"] not in payloads
                )
                from alembic.autogenerate import compare_metadata
                from alembic.migration import MigrationContext

                drift = await c.run_sync(
                    lambda sync: compare_metadata(
                        MigrationContext.configure(sync), db.metadata
                    )
                )
                assert not drift, drift
            from hirz.audit import retain_export

            for pipeline in (p, q):
                folder = tmp_path / str(pipeline.household_id)
                folder.mkdir(mode=0o700)
                verified, _ = await retain_export(
                    c, pipeline.household_id, p.audit.key.public_key(), folder
                )
                assert verified["status"] == "valid"

    asyncio.run(run())


def test_contact_http_passkey_binding_mailbox_and_failure(
    scratch_database, monkeypatch
):
    from unittest.mock import patch

    import httpx
    from webauthn.helpers import base64url_to_bytes

    from hirz.api.app import create_app
    from hirz.companion import policy
    from hirz.companion.api import Companion
    from hirz.constitution.schema import dump
    from hirz.contacts.worker import advance
    from hirz.graph.models import now
    from tests.unit.test_companion_auth import CONFIG

    config = Config(Fernet.generate_key().decode(), CONFIG.origin)
    monkeypatch.setenv("HIRZ_CONTACT_ENCRYPTION_KEY", config.encryption_key)
    monkeypatch.setenv("HIRZ_COMPANION_ORIGIN", config.origin)

    async def run():
        async with connect(scratch_database) as c:
            p = await setup(c, native=True)
            p.clock = now
            key = Authenticator()
            owner = await enroll(
                p, await auth.initial_invitation(p, ident("members", "malik")), key
            )
            async with p.repo.write(p.clock):
                current = await auth.session(c, owner["session"], p.clock())
                actor = current["principal"].model_copy(
                    update={"passkey_verified": True, "requester_confirmed": True}
                )
                draft = await policy.draft(p, actor, dump(p.bundle.policy()))
                await policy.activate(
                    p, actor, draft["id"], draft["candidate_hash"], current["digest"]
                )
            service = Companion(c.engine, p.audit, CONFIG)
            app = create_app(companion=service)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=CONFIG.origin
            ) as client:
                client.cookies.set(auth.SESSION_COOKIE, owner["session"])
                client.cookies.set(auth.BROWSER_COOKIE, "contact-http")
                client.headers.update(
                    {
                        "origin": CONFIG.origin,
                        "x-hirz-csrf": auth.csrf(owner["session"]),
                    }
                )

                async def change(value, altered=None):
                    begin = await client.post(
                        "/api/auth/begin",
                        json={"operation": "contact", "contact": value},
                    )
                    assert begin.status_code == 200, begin.text
                    options = begin.json()
                    return await client.post(
                        "/api/auth/finish",
                        json={
                            "id": options["id"],
                            "contact": altered or value,
                            "credential": key.response(
                                base64url_to_bytes(options["publicKey"]["challenge"])
                            ),
                        },
                    )

                value = {
                    "operation": "create",
                    "name": "Email contact",
                    "relationship": "family",
                }
                refused = await change(value, value | {"name": "Changed contact"})
                assert refused.status_code == 400
                result = await change(value)
                assert result.status_code == 200, result.text
                contact = result.json()["id"]
                result = await change(
                    {
                        "operation": "invite",
                        "contact_id": contact,
                        "method": "email",
                        "value": "Test.Local+Tag@EXAMPLE.COM",
                    }
                )
                assert result.status_code == 200, result.text
                reference = result.json()["id"]
                async with c.begin():
                    row = (
                        (
                            await c.execute(
                                sa.select(db.contact_links).where(
                                    db.contact_links.c.id == reference
                                )
                            )
                        )
                        .mappings()
                        .one()
                    )
                    private = config.open(row["ciphertext"])
                    assert private["destination"] == "Test.Local+Tag@example.com"
                    assert "Test.Local" not in str(
                        (await c.execute(sa.select(db.audit_log.c.payload)))
                        .scalars()
                        .all()
                    )
                assert (await client.get("/contact-links")).status_code == 200
                assert (await client.get("/api/contact-links/confirm")).status_code in {
                    405,
                    421,
                }
                confirm = {
                    "operation": "confirm",
                    "contact_id": contact,
                    "reference": reference,
                }
                assert (await change(confirm)).status_code == 400
                preview = await client.post(
                    "/api/contact-links/view", json={"token": private["token"]}
                )
                assert (
                    preview.status_code == 200
                    and preview.json()["kind"] == "enrollment"
                )
                assert (
                    await client.post(
                        "/api/contact-links/confirm", json={"token": private["token"]}
                    )
                ).status_code == 200
                assert (
                    await client.post(
                        "/api/contact-links/confirm", json={"token": private["token"]}
                    )
                ).status_code == 403
                confirmed = await change(confirm)
                assert confirmed.status_code == 200, confirmed.text
                async with service.pipeline(p.household_id) as q:
                    result = await HouseholdTools(q, actor).call(
                        "verify_trusted_identity",
                        {
                            "operation": "start",
                            "contact": contact,
                            "text": "Exact reported request",
                            "request_id": "email-check",
                        },
                    )
                    assert result.data.case.verification.method == "verified_email", (
                        result
                    )
                    case = result.data.case
                    async with q.connection.begin():
                        job = (
                            (
                                await q.connection.execute(
                                    sa.select(db.checkin_jobs).where(
                                        db.checkin_jobs.c.case_id == case.case_id
                                    )
                                )
                            )
                            .mappings()
                            .one()
                        )
                        token = config.open(job["ciphertext"])["token"]
                    with patch("hirz.contacts.checkins.send_email") as smtp:
                        await advance(q)
                    smtp.assert_called_once()
                preview = await client.post(
                    "/api/contact-links/view", json={"token": token}
                )
                assert preview.status_code == 200, preview.text
                assert preview.json()["text"] == "Exact reported request"
                assert (
                    await client.post(
                        "/api/contact-links/confirm",
                        json={
                            "token": token,
                            "request_hash": "wrong",
                            "answer": "genuine",
                        },
                    )
                ).status_code == 403
                response = {
                    "token": token,
                    "request_hash": preview.json()["request_hash"],
                    "answer": "not_genuine",
                }
                assert (
                    await client.post("/api/contact-links/confirm", json=response)
                ).status_code == 200
                assert (
                    await client.post("/api/contact-links/confirm", json=response)
                ).status_code == 200
                assert (
                    await client.post("/api/contact-links/view", json={"token": token})
                ).status_code == 403
                async with service.pipeline(p.household_id) as q:
                    await advance(q)
                    result = await HouseholdTools(q, actor).call(
                        "verify_trusted_identity",
                        {"operation": "status", "case_id": case.case_id},
                    )
                    assert result.data.case.verification.status == "not_genuine"
                retry = await client.post(
                    "/api/checkins/retry",
                    json={
                        "case_id": case.case_id,
                        "method": "email",
                        "confirmed": True,
                        "request_id": "email-retry",
                    },
                )
                assert retry.status_code == 200, retry.text
                retried = retry.json()["data"]["case"]
                assert retried["previous_case_id"] == case.case_id
                import smtplib

                async with service.pipeline(p.household_id) as q:
                    with patch(
                        "hirz.contacts.checkins.send_email",
                        side_effect=smtplib.SMTPAuthenticationError(535, b"fixture"),
                    ):
                        await advance(q)
                    await advance(q)
                    result = await HouseholdTools(q, actor).call(
                        "verify_trusted_identity",
                        {"operation": "status", "case_id": retried["case_id"]},
                    )
                    assert result.data.case.verification.reason == "delivery_failed"
                inbox = await client.get("/api/checkins")
                assert inbox.status_code == 200
                assert private["token"] not in inbox.text and token not in inbox.text

    asyncio.run(run())


def test_no_answer_scenario_through_authenticated_mcp(scratch_database, tmp_path):
    import yaml

    from hirz.twin.scenario import LoadedScenario
    from scripts.smoke_household_tools import mcp_process
    from scripts.smoke_tool_budget import Environment

    async def run():
        async with connect(scratch_database) as c:
            from test_database import migrate

            await migrate(c)
            env = Environment(c, tmp_path, "demo-evening")
            await env.prepare()
            scenario = LoadedScenario(Path("scenarios/parents-scam-no-answer.yaml"))
            spec = yaml.safe_load(
                Path("scenarios/parents-scam-no-answer.yaml").read_text()
            )
            sentence = next(
                row["text"] for row in spec["timeline"] if row["event"] == "voice"
            )
            env.clock_file.write_text(scenario.time("17:35").isoformat())
            try:
                async with (
                    env.servers(),
                    mcp_process(env.listeners[1], env.config),
                    env.client(3) as client,
                ):
                    args = {
                        "operation": "start",
                        "contact": "Malik",
                        "text": sentence,
                        "request_id": "not-confirmed",
                    }
                    refused = await client.session.call_tool(
                        "verify_trusted_identity", args
                    )
                    assert (
                        refused.structuredContent["data"]["code"] == "CONFIRM_REQUIRED"
                    )
                    started = await client.call(
                        "",
                        "verify_trusted_identity",
                        args | {"request_id": "confirmed"},
                    )
                    assert started.data.case.verification.status == "pending", started
                    assert started.data.case.verification.source == "twin"
                    case = started.data.case
                    env.clock_file.write_text(scenario.time("17:38").isoformat())
                    p = env.pipelines[1]
                    p.clock = lambda: scenario.time("17:38")
                    await simulated(p, None)
                    done = await client.call(
                        "",
                        "verify_trusted_identity",
                        {"operation": "status", "case_id": case.case_id},
                    )
                    assert done.data.case.verification.status == "no_answer"
                    assert "contact saved in your own phone" in done.speakable.headline
                    retry = await client.call(
                        "",
                        "verify_trusted_identity",
                        {
                            "operation": "retry",
                            "method": "app",
                            "case_id": case.case_id,
                            "request_id": "retry-confirmed",
                        },
                    )
                    assert retry.data.case.previous_case_id == case.case_id
                    assert retry.data.case.claim == case.claim
                    assert retry.data.case.verification.status == "pending"
                    original = await client.call(
                        "",
                        "verify_trusted_identity",
                        {"operation": "status", "case_id": case.case_id},
                    )
                    assert original.data.case == done.data.case
                    assert original.speakable == done.speakable
                from hirz.audit import retain_export

                folder = tmp_path / "parents-signed"
                folder.mkdir(mode=0o700)
                result, _ = await retain_export(
                    c, p.household_id, p.audit.key.public_key(), folder
                )
                assert result["status"] == "valid"
            finally:
                for listener in env.listeners:
                    listener.close()

    asyncio.run(run())
