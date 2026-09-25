"""Deferred consent keeps the pre-change rows and survives worker gaps."""

import asyncio
import json
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
import sqlalchemy as sa
from test_database import connect
from test_database import scratch_database as scratch_database
from test_executor_database import bounded, changed, environment, proposal, runtime_for

from hirz import db
from hirz.audit import verify_database
from hirz.executor.plans import PlanService, get
from hirz.executor.service import Executor
from hirz.executor.twin import state
from hirz.pipeline.hashing import wire
from hirz.pipeline.models import Action, Plan
from hirz.pipeline.service import Pipeline
from scripts.smoke_executor import PRINCIPAL

pytestmark = pytest.mark.integration


def test_worker_matches_complete_prechange_rows(scratch_database, monkeypatch):
    fixture = json.loads(Path("tests/fixtures/scheduling-inline.json").read_text())

    async def run():
        async with connect(scratch_database) as c:
            p, world, registry, executor = await environment(c)
            try:
                world.clock.set_speed(0)
                plan = Plan.model_validate(fixture["plan"])
                actions = tuple(Action.model_validate(a) for a in fixture["actions"])
                service = PlanService(p)
                monkeypatch.setattr("hirz.executor.plans.uuid4", lambda: UUID(int=426))
                await service.record(
                    plan, actions, PRINCIPAL, runtime=runtime_for(plan)
                )
                monkeypatch.setattr("hirz.executor.plans.uuid4", lambda: UUID(int=427))
                await service.approve(plan.plan_id, PRINCIPAL)
                executor.refresh_polls = True
                await executor.sweep()
                summary, events = await verify_database(
                    c, p.household_id, p.audit.key.public_key(), collect=True
                )
                assert summary["status"] == "valid"
                async with c.begin():
                    rows = [
                        wire(dict(row))
                        for row in (
                            await c.execute(
                                sa.select(db.actions)
                                .where(
                                    p.scope(db.actions),
                                    db.actions.c.action_id.in_(plan.actions),
                                )
                                .order_by(db.actions.c.action_id)
                            )
                        ).mappings()
                    ]
                assert json.loads(json.dumps(rows, default=str)) == fixture["rows"]
                assert [
                    wire(
                        dict(
                            seq=event.seq,
                            created_at=event.created_at,
                            event_type=event.event_type,
                            payload=event.payload,
                        )
                    )
                    for event in events
                    if event.event_type in {"SCHEDULED", "EXECUTION_CANCELLED"}
                ] == fixture["events"]
            finally:
                await registry.close()

    asyncio.run(run())


def test_late_consent_refreshes_in_same_worker_tick(scratch_database):
    from test_refresh_database import prepared

    from hirz.executor.refresh import job
    from hirz.executor.refresh_worker import RefreshWorker

    async def run():
        async with connect(scratch_database) as c:
            p, world, registry, _, service, result, _ = await prepared(
                c, opening_window=timedelta(minutes=1)
            )
            try:
                world.clock.jump(world.clock() + timedelta(minutes=1))
                await service.approve(result.plan.plan_id, PRINCIPAL)
                await RefreshWorker(p, registry, world=world).batch()
                async with c.begin():
                    previous = await get(p, result.plan.plan_id)
                    current = await job(p, previous)
                    assert previous["document"]["status"] == "superseded"
                    assert current["state"] == "idle"
                    replacement = await get(p, current["plan_id"])
                    assert replacement["document"]["status"] == "approved"
                    assert replacement["approver"] == previous["approver"]
            finally:
                await registry.close()

    asyncio.run(run())


def test_due_ending_precedes_scheduling_failure(scratch_database, monkeypatch):
    async def run():
        async with connect(scratch_database) as c:
            p, world, registry, executor = await environment(c)
            try:
                action = bounded(world, 30)
                await p.enqueue(action, PRINCIPAL)
                assert (await executor.sweep())[0].status == "verified"
                world.clock.jump(world.clock() + timedelta(seconds=30))

                async def failed_schedule(pipeline):
                    raise RuntimeError("Injected scheduling failure")

                monkeypatch.setattr(
                    "hirz.executor.service.schedule_approved", failed_schedule
                )
                with pytest.raises(RuntimeError, match="Injected scheduling failure"):
                    await executor.sweep()
                assert state(world, action)["on"] is False
                summary, _ = await verify_database(
                    c, p.household_id, p.audit.key.public_key()
                )
                assert summary["status"] == "valid"
            finally:
                await registry.close()

    asyncio.run(run())


@pytest.mark.parametrize("gap", ["second_approval", "cancel", "revision", "restart"])
def test_approved_plan_before_worker_tick(scratch_database, gap):
    async def run():
        async with connect(scratch_database) as c:
            p, world, registry, executor = await environment(c)
            try:
                plan, (action,) = proposal(world)
                action = changed(
                    action, scheduled_for=world.clock() + timedelta(seconds=30)
                )
                service = PlanService(p)
                await service.record(
                    plan, (action,), PRINCIPAL, runtime=runtime_for(plan)
                )
                await service.approve(plan.plan_id, PRINCIPAL)
                async with c.begin():
                    assert (await get(p, plan.plan_id))["document"][
                        "status"
                    ] == "approved"
                    assert (
                        await c.scalar(
                            sa.select(db.actions.c.execution_status).where(
                                p.scope(db.actions),
                                db.actions.c.action_id == action.action_id,
                            )
                        )
                        is None
                    )
                if gap == "second_approval":
                    with pytest.raises(ValueError, match="fresh consent"):
                        await service.approve(plan.plan_id, PRINCIPAL)
                elif gap == "cancel":
                    await service.cancel(plan.plan_id, PRINCIPAL)
                elif gap == "revision":
                    revision, actions = proposal(
                        world, supersedes=plan.plan_id, version=2
                    )
                    await service.revise(
                        revision, actions, PRINCIPAL, runtime=runtime_for(revision)
                    )
                elif gap == "restart":
                    async with connect(scratch_database) as fresh:
                        restarted = Pipeline(
                            fresh, p.bundle, p.boundary, p.audit, p.clock
                        )
                        await Executor(
                            restarted, registry, world=world, refresh_polls=True
                        ).sweep()
                executor.refresh_polls = True
                await executor.sweep()
                await executor.sweep()
                summary, events = await verify_database(
                    c, p.household_id, p.audit.key.public_key(), collect=True
                )
                assert summary["status"] == "valid"
                scheduled = [
                    event
                    for event in events
                    if event.event_type == "SCHEDULED"
                    and event.payload["action_id"] == action.action_id
                ]
                assert len(scheduled) == (0 if gap in {"cancel", "revision"} else 1)
                async with c.begin():
                    assert (await get(p, plan.plan_id))["document"]["status"] == {
                        "cancel": "abandoned",
                        "revision": "superseded",
                    }.get(gap, "approved")
            finally:
                await registry.close()

    asyncio.run(run())
