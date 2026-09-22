"""Consent, privacy, replay and atomic memory writes against disposable Postgres."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from test_database import connect
from test_database import scratch_database as scratch_database
from test_pipeline_database import setup

from hirz import db
from hirz.audit import verify_database
from hirz.memory.models import Candidate, Page, References, TurnInput
from hirz.memory.service import MemoryService
from hirz.pipeline.audit import PipelineError
from hirz.pipeline.models import Principal
from hirz.pipeline.service import Pipeline, PolicyBundle
from hirz.planner.coordinator import Clarification
from tests.unit.test_pipeline import HOME, POLICY, PRINCIPAL, action, ident

pytestmark = pytest.mark.integration


async def turn(
    service,
    principal=PRINCIPAL,
    action_id=None,
    text="Mom says make it warmer",
    session="one",
    references=References(),
):
    result = await service.record_turn(
        principal,
        action_id=action_id or uuid4().hex,
        turn=TurnInput(
            session_id=session, role="user", text=text, references=references
        ),
    )
    assert result.decision.decision == "execute", result
    return result


async def propose(service, source, value=74, action_id=None):
    result = await service.propose(
        PRINCIPAL,
        action_id=action_id or uuid4().hex,
        source_turn=source.record.id,
        candidate=Candidate(value=value, confidence=0.8),
    )
    assert result.decision.decision == "execute", result
    return result


def test_consent_replay_versions_private_storage_and_outage(scratch_database):
    async def run():
        async with connect(scratch_database) as c:
            p = await setup(c, native=True)
            clock = [p.clock()]
            p.clock = lambda: clock[0]
            provider = AsyncMock()
            provider.append.side_effect = RuntimeError("provider offline")
            provider.hints.side_effect = RuntimeError("provider offline")
            service = MemoryService(p, provider)
            source = await turn(service, action_id="turn")
            assert source.record.session.member_id == ident("members", "malik")
            assert await turn(service, action_id="turn") == source
            mismatch = await service.record_turn(
                PRINCIPAL,
                action_id="turn",
                turn=TurnInput(session_id="one", role="user", text="changed"),
            )
            assert mismatch.decision.event_type == "DENY_APPROVAL_MISMATCH"
            for i in range(4):
                await turn(service, text=str(i))
            assert [
                t.sequence
                for t in await service.turns(PRINCIPAL, "one", Page(after=2, limit=2))
            ] == [3, 4]
            assert len(await MemoryService(p).turns(PRINCIPAL, "one")) == 5
            assert await service.hints(PRINCIPAL, "one") == ()
            dad = Principal(provider="demo", sub="dad", surface="app")
            assert await service.turns(dad, "one") == ()
            assert (
                await service.turns(
                    PRINCIPAL.model_copy(update={"surface": "alexa"}), "one"
                )
                == ()
            )
            assert await service.turns(PRINCIPAL, "other") == ()
            with pytest.raises(Clarification):
                await service.turns(
                    Principal(provider="demo", sub="foreign", surface="app"), "one"
                )
            before = await p.snapshot(p.clock())
            await c.rollback()
            pending = await propose(service, source, action_id="proposal")
            assert (await p.snapshot(p.clock())).data["preferences"] == before.data[
                "preferences"
            ]
            await c.rollback()
            assert (
                await propose(service, source, action_id="proposal")
            ).decision == pending.decision
            assert await service.proposals(dad) == ()
            assert len(await service.proposals(PRINCIPAL)) == 1
            for principal in (
                dad,
                PRINCIPAL.model_copy(update={"surface": "alexa"}),
                PRINCIPAL.model_copy(update={"surface": "scheduler"}),
            ):
                refused = await service.review(
                    principal,
                    action_id=uuid4().hex,
                    proposal_id=pending.record.id,
                    accept=True,
                )
                assert refused.decision.decision == "deny"
            # Another linked member cannot manufacture evidence about the subject.
            assert (
                await service.propose(
                    dad,
                    action_id="claim",
                    source_turn=source.record.id,
                    candidate=Candidate(value=72, confidence=1),
                )
            ).decision.decision == "deny"
            stale = await propose(service, source, value=73)
            clock[0] += timedelta(seconds=1)
            accepted = await service.review(
                PRINCIPAL,
                action_id="accept",
                proposal_id=pending.record.id,
                accept=True,
            )
            assert accepted.decision.decision == "execute"
            assert accepted.record.status == "accepted"
            assert (
                await service.review(
                    PRINCIPAL,
                    action_id="accept",
                    proposal_id=pending.record.id,
                    accept=True,
                )
            ).decision == accepted.decision
            assert (
                await service.review(
                    PRINCIPAL,
                    action_id="stale",
                    proposal_id=stale.record.id,
                    accept=True,
                )
            ).decision.decision == "deny"
            changed = await p.snapshot(p.clock())
            learned = [
                r
                for r in changed.data["preferences"]
                if r["member_id"] == str(ident("members", "malik"))
            ]
            assert (
                len(learned) == 1
                and learned[0]["source"] == "learned_accepted"
                and learned[0]["value"] == 74
            )
            assert (
                await c.scalar(
                    sa.select(sa.func.count()).select_from(
                        db.HISTORY_TABLES["preferences"]
                    )
                )
                == 1
            )
            rows = (await c.execute(sa.select(db.actions.c.proposal))).scalars().all()
            audit = (await c.execute(sa.select(db.audit_log.c.payload))).scalars().all()
            assert "Mom says" not in str(rows) + str(audit)
            await c.rollback()
            summary, _ = await verify_database(c, HOME, p.audit.key.public_key())
            assert summary["status"] == "valid"

    asyncio.run(run())


def test_learning_never_rejection_and_audit_rollback(scratch_database):
    async def run():
        async with connect(scratch_database) as c:
            p = await setup(c, native=True)
            clock = [p.clock()]
            p.clock = lambda: clock[0]
            service = MemoryService(p)
            source = await turn(service)
            pending = await propose(service, source)
            data = POLICY.model_dump()
            data["learning"]["accept_memory_proposals"] = "never"
            p.bundle = await PolicyBundle.validate(
                HOME, type(POLICY).model_validate(data), p.boundary
            )
            assert (
                await service.propose(
                    PRINCIPAL,
                    action_id="disabled-propose",
                    source_turn=source.record.id,
                    candidate=Candidate(value=73, confidence=1),
                )
            ).decision.decision == "deny"
            assert (
                await service.review(
                    PRINCIPAL,
                    action_id="disabled-accept",
                    proposal_id=pending.record.id,
                    accept=True,
                )
            ).decision.decision == "deny"
            rejected = await service.review(
                PRINCIPAL,
                action_id="reject",
                proposal_id=pending.record.id,
                accept=False,
            )
            assert (
                rejected.decision.decision == "execute"
                and rejected.record.status == "rejected"
            )
            await turn(service, text="Context still works with learning disabled")
            p.bundle = await PolicyBundle.validate(HOME, POLICY, p.boundary)
            pending = await propose(service, source)
            before = await p.snapshot(p.clock())
            await c.rollback()
            original = p.audit.append

            async def fail(*args, **kwargs):
                if args[3] == "MEMORY_ACCEPTED":
                    raise RuntimeError("synthetic audit failure")
                return await original(*args, **kwargs)

            p.audit.append = fail
            clock[0] += timedelta(seconds=1)
            with pytest.raises(PipelineError):
                await service.review(
                    PRINCIPAL,
                    action_id="rollback",
                    proposal_id=pending.record.id,
                    accept=True,
                )
            p.audit.append = original
            assert (await p.snapshot(p.clock())).data["preferences"] == before.data[
                "preferences"
            ]
            assert (
                await c.scalar(
                    sa.select(db.actions.c.action_id).where(
                        db.actions.c.action_id == "rollback"
                    )
                )
                is None
            )
            await c.rollback()
            assert any(
                r.id == pending.record.id for r in await service.proposals(PRINCIPAL)
            )

    asyncio.run(run())


def test_concurrent_review_and_explicit_references(scratch_database):
    async def run():
        async with connect(scratch_database) as c:
            p = await setup(c, native=True)
            service = MemoryService(p)
            source = await turn(service)
            pending = await propose(service, source)

            async def review(accept):
                async with connect(scratch_database) as other:
                    fresh = Pipeline(
                        other,
                        p.bundle,
                        p.boundary,
                        p.audit,
                        lambda: p.clock() + timedelta(seconds=1),
                    )
                    return await MemoryService(fresh).review(
                        PRINCIPAL,
                        action_id=uuid4().hex,
                        proposal_id=pending.record.id,
                        accept=accept,
                    )

            results = await asyncio.gather(review(True), review(False))
            assert sorted(r.decision.decision for r in results) == ["deny", "execute"]
            later = p.clock() + timedelta(seconds=2)
            p.clock = lambda: later
            a = action()
            assert (await p.redeem(a, PRINCIPAL)).decision == "execute"
            await turn(service, references=References(action=a.action_id))
            assert await service.resolve(PRINCIPAL, "one", "action") == a.action_id
            await turn(
                service, references=References(verification_case="case-not-built")
            )
            with pytest.raises(Clarification, match="not available"):
                await service.resolve(PRINCIPAL, "one", "verification_case")
            with pytest.raises(Clarification, match="identify"):
                await service.resolve(PRINCIPAL, "other", "action")
            bad = await service.record_turn(
                PRINCIPAL,
                action_id="missing-ref",
                turn=TurnInput(
                    session_id="one",
                    role="assistant",
                    text="missing",
                    references=References(action="missing"),
                ),
            )
            assert bad.decision.decision == "deny"

    asyncio.run(run())


def test_absent_preference_owner_cannot_review_other_member_and_household_isolation(
    scratch_database,
):
    from pathlib import Path

    from hirz.constitution.schema import load
    from hirz.graph.seeds import load_seeds, read_seed

    async def run():
        async with connect(scratch_database) as c:
            p = await setup(c, native=True)
            parents = read_seed(Path("constitutions/quinn-parents.yaml"))
            await load_seeds(c, [parents], p.clock)
            other = Pipeline(
                c,
                await PolicyBundle.validate(
                    parents.household_id,
                    load(Path("constitutions/quinn-parents.yaml")),
                    p.boundary,
                ),
                p.boundary,
                p.audit,
                p.clock,
            )
            service = MemoryService(p)
            dad = Principal(provider="demo", sub="dad", surface="app")
            source = await turn(service, dad)
            candidate = Candidate(value=71, confidence=1)
            pending = await service.propose(
                dad,
                action_id="dad-proposal",
                source_turn=source.record.id,
                candidate=candidate,
            )
            assert (
                pending.decision.decision == "execute"
                and pending.record.preference_id is None
            )
            assert (
                await service.review(
                    PRINCIPAL,
                    action_id="owner-on-behalf",
                    proposal_id=pending.record.id,
                    accept=True,
                )
            ).decision.decision == "deny"
            assert await MemoryService(other).turns(dad, "one") == ()
            assert (
                await MemoryService(other).propose(
                    dad,
                    action_id="foreign-source",
                    source_turn=source.record.id,
                    candidate=candidate,
                )
            ).decision.decision == "deny"
            assert (
                await service.review(
                    dad,
                    action_id="dad-accept",
                    proposal_id=pending.record.id,
                    accept=True,
                )
            ).decision.decision == "execute"
            prefs = (await p.snapshot(p.clock())).data["preferences"]
            assert (
                len(
                    [
                        r
                        for r in prefs
                        if r["member_id"] == str(ident("members", "dad"))
                        and r["source"] == "learned_accepted"
                    ]
                )
                == 1
            )

    asyncio.run(run())


def test_duplicate_preferences_and_database_commit_rollback(scratch_database):

    async def run():
        async with connect(scratch_database) as c:
            p = await setup(c, native=True)
            clock = [p.clock()]
            p.clock = lambda: clock[0]
            service = MemoryService(p)
            source = await turn(service)
            pending = await propose(service, source)
            before = await p.snapshot(p.clock())
            await c.rollback()

            def fail_commit(connection):
                raise RuntimeError("synthetic commit failure")

            sa.event.listen(c.sync_connection, "commit", fail_commit)
            clock[0] += timedelta(seconds=1)
            try:
                with pytest.raises(PipelineError):
                    await service.review(
                        PRINCIPAL,
                        action_id="commit-failure",
                        proposal_id=pending.record.id,
                        accept=True,
                    )
            finally:
                sa.event.remove(c.sync_connection, "commit", fail_commit)
            assert (await p.snapshot(p.clock())).data["preferences"] == before.data[
                "preferences"
            ]
            assert (
                await c.scalar(
                    sa.select(db.actions.c.action_id).where(
                        db.actions.c.action_id == "commit-failure"
                    )
                )
                is None
            )
            await c.rollback()
            # Deliberately corrupt the synthetic fixture to test duplicate-row refusal.
            original = (
                (
                    await c.execute(
                        sa.select(db.preferences).where(
                            db.preferences.c.member_id == ident("members", "malik")
                        )
                    )
                )
                .mappings()
                .one()
            )
            duplicate = dict(original) | {"id": uuid4()}
            await c.execute(db.preferences.insert().values(**duplicate))
            await c.commit()
            assert (
                await service.review(
                    PRINCIPAL,
                    action_id="duplicate-accept",
                    proposal_id=pending.record.id,
                    accept=True,
                )
            ).decision.decision == "deny"
            assert (
                await service.propose(
                    PRINCIPAL,
                    action_id="duplicate-propose",
                    source_turn=source.record.id,
                    candidate=Candidate(value=74, confidence=1),
                )
            ).decision.decision == "deny"
            assert (
                await service.review(
                    PRINCIPAL,
                    action_id="duplicate-reject",
                    proposal_id=pending.record.id,
                    accept=False,
                )
            ).decision.decision == "execute"

    asyncio.run(run())


def test_acceptance_and_refresh_hold_are_atomic(scratch_database):
    from test_refresh_database import prepared

    from hirz.executor.plans import get
    from hirz.executor.refresh import job

    async def run():
        async with connect(scratch_database) as c:
            p, world, registry, executor, plans, result, runtime = await prepared(c)
            try:
                plan_id = result.plan.plan_id
                await plans.approve(plan_id, PRINCIPAL)
                service = MemoryService(p)
                source = await turn(service)
                pending = await propose(service, source)
                async with c.begin():
                    stored = await get(p, plan_id)
                    original_job = await job(p, stored)
                    before = await p.snapshot(p.clock())
                append = p.audit.append

                async def fail_queue(*args, **kwargs):
                    if args[3] == "PLAN_REFRESH":
                        raise RuntimeError("synthetic refresh audit failure")
                    return await append(*args, **kwargs)

                p.audit.append = fail_queue
                with pytest.raises(PipelineError):
                    await service.review(
                        PRINCIPAL,
                        action_id="refresh-rollback",
                        proposal_id=pending.record.id,
                        accept=True,
                    )
                p.audit.append = append
                async with c.begin():
                    assert await job(p, stored) == original_job
                    assert (await get(p, plan_id))["document"]["status"] == "approved"
                    assert (await p.snapshot(p.clock())).data[
                        "preferences"
                    ] == before.data["preferences"]
                assert (
                    await service.review(
                        PRINCIPAL,
                        action_id="refresh-accept",
                        proposal_id=pending.record.id,
                        accept=True,
                    )
                ).decision.decision == "execute"
                async with c.begin():
                    current = await job(p, stored)
                    assert current["state"] == "queued" and not current["explicit"]
                    assert (await get(p, plan_id))["document"]["status"] == "refreshing"
                    actions = (
                        (
                            await c.execute(
                                sa.select(db.actions)
                                .join(
                                    db.plan_actions,
                                    sa.and_(
                                        db.actions.c.household_id
                                        == db.plan_actions.c.household_id,
                                        db.actions.c.action_id
                                        == db.plan_actions.c.action_id,
                                    ),
                                )
                                .where(
                                    p.scope(db.actions),
                                    db.plan_actions.c.plan_id == plan_id,
                                )
                            )
                        )
                        .mappings()
                        .all()
                    )
                    assert actions and all(
                        r["execution_status"] == "held"
                        and r["execution_attempt_seq"] is None
                        for r in actions
                    )
            finally:
                await registry.close()

    asyncio.run(run())


def test_malformed_direct_memory_actions_do_not_persist_transcripts(scratch_database):
    async def run():
        async with connect(scratch_database) as c:
            p = await setup(c, native=True)
            for params in (
                {
                    "operation": "append_turn",
                    "content_hash": "0" * 64,
                    "text": "private sentinel",
                },
                {
                    "operation": "propose",
                    "content_hash": "0" * 64,
                    "candidate": {"key": "lights", "value": 72, "confidence": 1},
                },
            ):
                with pytest.raises(PipelineError):
                    await p.redeem(
                        action("governance.memory", params=params), PRINCIPAL
                    )
                async with c.begin():
                    assert (
                        await c.scalar(
                            sa.select(sa.func.count()).select_from(db.actions)
                        )
                        == 0
                    )
                    assert (
                        await c.scalar(
                            sa.select(sa.func.count()).select_from(db.audit_log)
                        )
                        == 0
                    )

    asyncio.run(run())
