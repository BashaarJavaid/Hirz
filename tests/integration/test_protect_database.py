"""Durable advice, immutable preview, private receipts and worker isolation."""

import asyncio
import threading
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from test_database import connect
from test_database import scratch_database as scratch_database
from test_pipeline_database import setup

from hirz import db
from hirz.mcp.household import HouseholdTools
from hirz.mcp.persistence import command
from hirz.pipeline.models import VerificationCase
from hirz.pipeline.service import Pipeline
from hirz.protect.advice import publish
from hirz.protect.scoring import signals
from hirz.protect.worker import advance, transition
from tests.unit.test_pipeline import PRINCIPAL
from tests.unit.test_protect import SCAM

pytestmark = pytest.mark.integration


def test_durable_enrichment_and_concurrent_bookkeeping(scratch_database, monkeypatch):
    monkeypatch.setenv("HIRZ_LLM", "bedrock")

    async def run():
        async with (
            connect(scratch_database) as c,
            connect(scratch_database) as other,
            connect(scratch_database) as third,
        ):
            p = await setup(c, native=True)
            q = Pipeline(other, p.bundle, p.boundary, p.audit, p.clock)
            r = Pipeline(third, p.bundle, p.boundary, p.audit, p.clock)
            tools = HouseholdTools(p, PRINCIPAL)
            args = {"text": SCAM, "party": "person", "request_id": "one"}
            first = await tools.call("assess_request_risk", args)
            identity = first.data.case.case_id
            assert first.data.case.risk_band.value == "critical"
            assert first.data.case.subject.claimed_party is None
            assert first.data.case.verification is None
            assert first.data.case.number_comparison is None
            async with c.begin():
                stored = await c.scalar(
                    sa.select(db.verification_cases.c.document).where(
                        db.verification_cases.c.id == identity
                    )
                )
                assert (
                    await c.scalar(
                        sa.select(sa.func.count()).select_from(db.checkin_jobs)
                    )
                    == 0
                )
            original = VerificationCase.model_validate(stored)
            assert original.assessment_decision is not None
            assert not any(
                f.factor == "scam_pattern"
                for f in original.assessment_decision.risk.factors
            )
            started, release = threading.Event(), threading.Event()

            def provider(text):
                assert text == SCAM
                started.set()
                assert release.wait(10)
                return signals("urgent")

            with patch("hirz.protect.worker.extract", provider):
                job = asyncio.create_task(advance(q))
                try:
                    assert await asyncio.to_thread(started.wait, 10)
                    assert not other.in_transaction()
                    assert not await advance(r)
                    # The provider holds neither a transaction nor household mutation lock.
                    async with asyncio.timeout(3):
                        assert (
                            await tools.call("assess_request_risk", args)
                        ).model_dump() == first.model_dump()
                        second = await tools.call(
                            "assess_request_risk",
                            args
                            | {
                                "text": "Dad wants to know when dinner is",
                                "request_id": "two",
                            },
                        )
                        assert second.data.case.risk_band.value == "low"
                finally:
                    release.set()
                    await job
            latest = await tools.call(
                "verify_trusted_identity", {"operation": "status", "case_id": identity}
            )
            assert latest.data.case.extraction.status == "complete"
            assert latest.data.case.assessment_decision == original.assessment_decision
            assert latest.data.case.verification is None
            assert latest.data.case.extraction.model_signals == signals("urgent")
            assert (
                await tools.call("assess_request_risk", args)
            ).model_dump() == first.model_dump()
            assert (
                "Possible pressure to act quickly" in latest.data.presentation.signals
            )
            assert latest.data.case.claim == original.claim
            # Persist an abandoned attempt with genuine bookkeeping, then recover it.
            async with q.repo.write(q.clock):
                row = (
                    (
                        await other.execute(
                            sa.select(db.verification_cases).where(
                                db.verification_cases.c.id == second.data.case.case_id
                            )
                        )
                    )
                    .mappings()
                    .one()
                )
                abandoned = VerificationCase.model_validate(row["document"])
                await transition(
                    q,
                    row,
                    publish(
                        abandoned,
                        abandoned.extraction.model_copy(
                            update={"status": "running", "started_at": q.clock()}
                        ),
                    ),
                )
            with patch(
                "hirz.protect.worker.extract",
                side_effect=AssertionError("No automatic retry"),
            ):
                assert await advance(q)
            done = await tools.call(
                "verify_trusted_identity",
                {"operation": "status", "case_id": second.data.case.case_id},
            )
            assert done.data.case.extraction.failure_code == "interrupted"
            cancelled = await tools.call(
                "assess_request_risk", args | {"request_id": "cancelled"}
            )
            started.clear()
            release.clear()
            with patch("hirz.protect.worker.extract", provider):
                job = asyncio.create_task(advance(q))
                assert await asyncio.to_thread(started.wait, 10)
                job.cancel()
                await asyncio.sleep(0)
                try:
                    assert not await advance(r)
                finally:
                    release.set()
                    with pytest.raises(asyncio.CancelledError):
                        await job
            with patch(
                "hirz.protect.worker.extract",
                side_effect=AssertionError("No automatic retry"),
            ):
                assert await advance(r)
            recovered = await tools.call(
                "verify_trusted_identity",
                {"operation": "status", "case_id": cancelled.data.case.case_id},
            )
            assert recovered.data.case.extraction.failure_code == "interrupted"
            # A model publication cannot alter the private preview or the claim.
            async with p.repo.write(p.clock):
                with pytest.raises(ValueError, match="immutable"):
                    await command(
                        p,
                        "record_verification",
                        {
                            "operation": "extraction",
                            "case": original.model_copy(
                                update={"assessment_decision": None}
                            ).model_dump(mode="json"),
                        },
                        PRINCIPAL.model_copy(update={"surface": "scheduler"}),
                    )

    asyncio.run(run())


def test_contact_reply_during_extraction_and_retry_copy(
    scratch_database, monkeypatch, tmp_path
):
    from datetime import timedelta

    from test_database import migrate

    from hirz.mcp.trust import advance as reply
    from hirz.protect.advice import OFFLINE
    from scripts.smoke_household_tools import mcp_process
    from scripts.smoke_tool_budget import Environment

    monkeypatch.setenv("HIRZ_LLM", "bedrock")

    async def run():
        async with connect(scratch_database) as c, connect(scratch_database) as other:
            await migrate(c)
            env = Environment(c, tmp_path, "demo-evening")
            await env.prepare()
            p = env.pipelines[1]
            q = Pipeline(other, p.bundle, p.boundary, p.audit, p.clock)
            started, release = threading.Event(), threading.Event()

            def provider(text):
                started.set()
                assert release.wait(15)
                return signals("urgent")

            try:
                async with (
                    env.servers(),
                    mcp_process(env.listeners[1], env.config),
                    env.client(3) as client,
                ):
                    result = await client.call(
                        "",
                        "verify_trusted_identity",
                        {
                            "operation": "start",
                            "contact": "Malik",
                            "text": SCAM,
                            "request_id": "named",
                        },
                    )
                    original = result.data.case
                    assert original.verification.status == "pending"
                    with patch("hirz.protect.worker.extract", provider):
                        task = asyncio.create_task(advance(q))
                        try:
                            assert await asyncio.to_thread(started.wait, 10)
                            at = p.clock() + timedelta(minutes=3)
                            p.clock = lambda: at
                            env.clock_file.write_text(at.isoformat())
                            await reply(p, None)
                            done = await client.call(
                                "",
                                "verify_trusted_identity",
                                {"operation": "status", "case_id": original.case_id},
                            )
                            assert done.data.case.verification.status == "no_answer"
                            copied = await client.call(
                                "",
                                "verify_trusted_identity",
                                {
                                    "operation": "retry",
                                    "method": "app",
                                    "case_id": original.case_id,
                                    "request_id": "retry",
                                },
                            )
                            assert (
                                copied.data.case.extraction.failure_code
                                == "retry_unfinished"
                            )
                            assert OFFLINE in copied.speakable.details
                        finally:
                            release.set()
                            await task
                    current = await client.call(
                        "",
                        "verify_trusted_identity",
                        {"operation": "status", "case_id": original.case_id},
                    )
                    assert current.data.case.verification == done.data.case.verification
                    assert current.data.case.extraction.status == "complete"
                    assert current.data.case.claim == original.claim
                    with patch(
                        "hirz.protect.worker.extract",
                        side_effect=AssertionError("Retry cannot extract"),
                    ):
                        assert not await advance(q)
                    async with env.client(1) as another:
                        refused = await another.call(
                            "",
                            "verify_trusted_identity",
                            {"operation": "status", "case_id": original.case_id},
                            error=True,
                        )
                        assert refused.data.case is None
            finally:
                env.close()

    asyncio.run(run())


def test_authenticated_phone_reads_current_advice(scratch_database, monkeypatch):
    import httpx
    from test_companion_auth_database import enroll

    from hirz.api.app import create_app
    from hirz.companion import auth, policy
    from hirz.companion.api import Companion
    from hirz.constitution.schema import dump
    from hirz.graph.models import now
    from tests.unit.test_companion_auth import CONFIG, Authenticator
    from tests.unit.test_pipeline import ident

    monkeypatch.setenv("HIRZ_LLM", "bedrock")

    async def run():
        async with connect(scratch_database) as c:
            p = await setup(c, native=True)
            p.clock = now
            owner = await enroll(
                p,
                await auth.initial_invitation(p, ident("members", "malik")),
                Authenticator(),
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
            first = await HouseholdTools(p, actor).call(
                "assess_request_risk",
                {"text": SCAM, "party": "person", "request_id": "phone"},
            )
            app = create_app(companion=Companion(c.engine, p.audit, CONFIG))
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=CONFIG.origin
            ) as client:
                client.headers["origin"] = CONFIG.origin
                assert (await client.get("/api/checkins")).status_code == 403
                client.cookies.set(auth.SESSION_COOKIE, owner["session"])
                client.cookies.set(auth.BROWSER_COOKIE, "protect-phone")
                pending = await client.get("/api/checkins")
                assert pending.status_code == 200
                before = pending.json()["cases"][0]
                assert before["data"]["case"]["extraction"]["status"] == "pending"
                assert "assessment_decision" not in before["data"]["case"]
                with patch(
                    "hirz.protect.worker.extract", return_value=signals("urgent")
                ):
                    assert await advance(p)
                complete = (await client.get("/api/checkins")).json()["cases"][0]
                assert complete["data"]["case"]["case_id"] == first.data.case.case_id
                assert complete["data"]["case"]["extraction"]["status"] == "complete"
                assert complete["data"]["case"]["verification"] is None
                assert "completed" in complete["speakable"]["details"][0]

    asyncio.run(run())
