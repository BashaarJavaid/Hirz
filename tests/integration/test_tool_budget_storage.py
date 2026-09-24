"""Batching preserves grants, signatures, rollback and fresh graph reads."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from test_database import connect, migrate
from test_database import scratch_database as scratch_database
from test_executor_database import bounded, changed, environment, proposal, runtime_for
from test_pipeline_database import setup

from hirz import db
from hirz.audit import verify_database
from hirz.executor.plans import PlanService, governance
from hirz.explainer.core import decision_context, prepared
from hirz.pipeline.models import Action, Decision
from scripts.smoke_executor import PRINCIPAL

pytestmark = pytest.mark.integration


def test_batch_scheduling_rolls_back_and_keeps_each_signed_transition(
    scratch_database, monkeypatch
):
    async def run():
        async with connect(scratch_database) as c:
            p, world, registry, _ = await environment(c)
            try:
                plan, (first,) = proposal(world)
                actions = (
                    first,
                    changed(first, action_id=first.action_id + "_second"),
                    changed(first, action_id=first.action_id + "_different_context"),
                )

                async def narration_context(pipeline, action):
                    ctx = await decision_context(pipeline, action)
                    return (
                        replace(ctx, locale="es-US")
                        if action.action_id.endswith("_different_context")
                        else ctx
                    )

                monkeypatch.setattr(
                    "hirz.executor.plans.decision_context", narration_context
                )
                plan = plan.model_copy(
                    update={"actions": tuple(a.action_id for a in actions)}
                )
                service = PlanService(p)
                assert (
                    await service.record(
                        plan, actions, PRINCIPAL, runtime=runtime_for(plan)
                    )
                ).decision == "execute"
                original = p.audit.append_many
                before, _ = await verify_database(
                    c, p.household_id, p.audit.key.public_key()
                )
                async with c.begin():
                    originals = {
                        r["action_id"]: dict(r)
                        for r in (
                            await c.execute(
                                sa.select(db.actions).where(
                                    p.scope(db.actions),
                                    db.actions.c.action_id.in_(plan.actions),
                                )
                            )
                        ).mappings()
                    }

                async def fail_after_batch(*args):
                    sequences = await original(*args)
                    if len(sequences) > 1:
                        raise RuntimeError("Injected batch persistence failure")
                    return sequences

                with monkeypatch.context() as patch:
                    patch.setattr(p.audit, "append_many", fail_after_batch)
                    with pytest.raises(RuntimeError, match="Injected batch"):
                        await service.approve(plan.plan_id, PRINCIPAL)
                rolled_back, _ = await verify_database(
                    c, p.household_id, p.audit.key.public_key()
                )
                assert rolled_back == before
                approved = await service.approve(plan.plan_id, PRINCIPAL)
                assert approved.decision == "execute"
                summary, rows = await verify_database(
                    c, p.household_id, p.audit.key.public_key(), collect=True
                )
                assert summary["status"] == "valid"
                date = (
                    world.clock().astimezone(ZoneInfo(world.household.timezone)).date()
                )

                async def usage():
                    async with c.begin():
                        return tuple(
                            [
                                await p.usage(name, day.isoformat())
                                for name in (
                                    "energy.optimize_cost",
                                    "environment.lights",
                                )
                                for day in (date, date + timedelta(days=1))
                            ]
                        )

                indexed = await usage()
                assert indexed[0] > 0
                await migrate(c, "downgrade", "0011_planning_objective")
                assert await usage() == indexed
                await migrate(c)
                assert await usage() == indexed
                after_migration, _ = await verify_database(
                    c, p.household_id, p.audit.key.public_key()
                )
                assert after_migration == summary
                scheduled = {
                    r.payload["action_id"]: r
                    for r in rows
                    if r.event_type == "SCHEDULED"
                }
                assert set(scheduled) == {a.action_id for a in actions}
                async with c.begin():
                    scheduler = PRINCIPAL.model_copy(update={"surface": "scheduler"})
                    member = await p.requester(scheduler)
                    records = (
                        (
                            await c.execute(
                                sa.select(db.actions).where(
                                    p.scope(db.actions),
                                    db.actions.c.action_id.in_(scheduled),
                                )
                            )
                        )
                        .mappings()
                        .all()
                    )
                    for row in records:
                        stored = Decision.model_validate(row["lifecycle"]["decision"])
                        independent = prepared(
                            stored.model_copy(
                                update={
                                    "narration": None,
                                    "speakable": {
                                        "headline": "Your request is queued."
                                    },
                                }
                            ),
                            await narration_context(
                                p, Action.model_validate(row["proposal"])
                            ),
                        )
                        assert stored == independent
                        assert scheduled[row["action_id"]].payload[
                            "decision"
                        ] == independent.model_dump(mode="json", by_alias=True)
                        assert row["lifecycle_seq"] == scheduled[row["action_id"]].seq
                        assert row["execution_status"] == "scheduled"
                        assert row["principal"]["sub"] == "malik"
                        assert row["principal"]["surface"] == "scheduler"
                        assert (
                            row["grant_seq"] is None
                        )  # Scheduling is never device authority.
                        original = originals[row["action_id"]]
                        expected_action = Action.model_validate(
                            original["proposal"]
                        ).model_copy(update={"requested_by": member})
                        assert dict(row) == original | {
                            "proposal": expected_action.model_dump(
                                mode="json", by_alias=True
                            ),
                            "principal": original["principal"]
                            | {"surface": "scheduler"},
                            "due_at": expected_action.scheduled_for or world.clock(),
                            "execution_status": "scheduled",
                            "lifecycle_seq": scheduled[row["action_id"]].seq,
                            "lifecycle": {
                                "decision": independent.model_dump(
                                    mode="json", by_alias=True
                                ),
                                "approval_id": None,
                                "member_id": member.member_id,
                                "retry": 0,
                            },
                        }
                world.clock.jump(world.clock() + timedelta(microseconds=1))
                assert (
                    await service.cancel(plan.plan_id, PRINCIPAL)
                ).decision == "execute"
                summary, rows = await verify_database(
                    c, p.household_id, p.audit.key.public_key(), collect=True
                )
                assert summary["status"] == "valid"
                cancelled = {
                    r.payload["action_id"]
                    for r in rows
                    if r.event_type == "EXECUTION_CANCELLED"
                }
                assert set(scheduled) <= cancelled
                plan, (first,) = proposal(world)
                first = changed(first, revert=bounded(world).revert)
                actions = (
                    first,
                    changed(first, action_id=first.action_id + "_overlap"),
                )
                plan = plan.model_copy(
                    update={"actions": tuple(a.action_id for a in actions)}
                )
                assert (
                    await service.record(
                        plan, actions, PRINCIPAL, runtime=runtime_for(plan)
                    )
                ).decision == "execute"
                before, _ = await verify_database(
                    c, p.household_id, p.audit.key.public_key()
                )
                with pytest.raises(ValueError, match="Overlapping bounded operations"):
                    await service.approve(plan.plan_id, PRINCIPAL)
                after, _ = await verify_database(
                    c, p.household_id, p.audit.key.public_key()
                )
                assert before == after
            finally:
                await registry.close()

    asyncio.run(run())


def test_refresh_reads_only_active_plans_and_preserves_terminal_evidence(
    scratch_database,
):
    from uuid import uuid4

    from hirz.executor.refresh_worker import RefreshWorker
    from hirz.planner.coordinator import Coordinator

    async def run():
        async with connect(scratch_database) as c:
            p, world, registry, _ = await environment(c)
            try:
                service = PlanService(p)
                old, actions = proposal(world)
                await service.record(old, actions, PRINCIPAL, runtime=runtime_for(old))
                await service.cancel(old.plan_id, PRINCIPAL)
                current, actions = proposal(world)
                await service.record(
                    current, actions, PRINCIPAL, runtime=runtime_for(current)
                )
                async with c.begin():
                    terminal = dict(
                        (
                            await c.execute(
                                sa.select(db.plans).where(
                                    p.scope(db.plans), db.plans.c.plan_id == old.plan_id
                                )
                            )
                        )
                        .mappings()
                        .one()
                    )
                fetched = []

                def observe(connection, cursor, statement, parameters, context, many):
                    if (
                        statement.startswith("SELECT plans.")
                        and "FROM plans" in statement
                    ):
                        fetched.append(cursor.rowcount)

                sa.event.listen(c.engine.sync_engine, "after_cursor_execute", observe)
                try:
                    world.clock.jump(world.clock() + timedelta(seconds=1))
                    outcome = await Coordinator(p).intake(
                        PRINCIPAL,
                        action_id=uuid4().hex,
                        text="prefer living room at 72 F",
                        horizon_end=current.horizon.end,
                    )
                    assert outcome.decision.decision == "execute"
                    await RefreshWorker(p, registry, world=world).poll()
                finally:
                    sa.event.remove(
                        c.engine.sync_engine, "after_cursor_execute", observe
                    )
                assert fetched and max(fetched) == 1
                async with c.begin():
                    assert (
                        dict(
                            (
                                await c.execute(
                                    sa.select(db.plans).where(
                                        p.scope(db.plans),
                                        db.plans.c.plan_id == old.plan_id,
                                    )
                                )
                            )
                            .mappings()
                            .one()
                        )
                        == terminal
                    )
                summary, rows = await verify_database(
                    c, p.household_id, p.audit.key.public_key(), collect=True
                )
                assert summary["status"] == "valid"
                assert any(
                    r.event_type == "PLAN_REFRESH"
                    and r.payload["plan_id"] == current.plan_id
                    for r in rows
                )
            finally:
                await registry.close()

    asyncio.run(run())


def test_snapshot_reuse_is_private_and_invalidated_by_write_and_transaction(
    scratch_database,
):
    async def run():
        async with connect(scratch_database) as c:
            p = await setup(c)
            reads = []
            member_reads = []

            def observe(connection, cursor, statement, parameters, context, many):
                if "jsonb_build_object" in statement:
                    reads.append(statement)
                if "JOIN member_accounts" in statement:
                    member_reads.append(statement)

            sa.event.listen(c.engine.sync_engine, "before_cursor_execute", observe)
            try:
                async with p.repo.write(p.clock):
                    member = await p.requester(PRINCIPAL)
                    assert await p.requester(PRINCIPAL) == member
                    assert await p.requester(PRINCIPAL) is not member
                    assert len(member_reads) == 1
                    other = PRINCIPAL.model_copy(update={"sub": "unlinked-fixture"})
                    assert (await p.requester(other)).role == "unknown"
                    alexa = PRINCIPAL.model_copy(update={"surface": "alexa"})
                    assert (await p.requester(alexa)).surface == "alexa"
                    assert len(member_reads) == 3
                    first = await p.snapshot(p.clock())
                    first.data["households"].clear()
                    second = await p.snapshot(p.clock())
                    assert second.data["households"] and len(reads) == 1
                    action = governance(p, "pause_automation", {}, PRINCIPAL)
                    assert (
                        await p.mutate_locked(action, PRINCIPAL)
                    ).decision == "execute"
                    refreshed = await p.snapshot(p.clock())
                    assert refreshed.data["households"][0]["autonomy_paused"] is True
                    assert len(reads) >= 2
                    before = len(member_reads)
                    assert await p.requester(PRINCIPAL) == member
                    assert len(member_reads) == before + 1
                count = len(reads)
                count_members = len(member_reads)
                async with p.repo.write(p.clock):
                    assert await p.requester(PRINCIPAL) == member
                    assert len(member_reads) == count_members + 1
                    assert (await p.snapshot(p.clock())).data["households"][0][
                        "autonomy_paused"
                    ] is True
                assert len(reads) == count + 1
            finally:
                sa.event.remove(c.engine.sync_engine, "before_cursor_execute", observe)

    asyncio.run(run())
