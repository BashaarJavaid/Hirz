"""Durable scheduling and restart gates, isolated from the development database."""

import asyncio
from datetime import timedelta
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from test_database import connect, migrate
from test_database import scratch_database as scratch_database

from hirz import db
from hirz.executor.contracts import ending
from hirz.executor.local import compose
from hirz.executor.observations import ingest
from hirz.executor.plans import PlanService, governance
from hirz.executor.service import Executor
from hirz.executor.storage import row
from hirz.executor.twin import restore, state
from hirz.pipeline.hashing import action_hash
from hirz.pipeline.models import Inverse, Revert
from hirz.pipeline.service import PolicyBundle
from hirz.twin.scenario import LoadedScenario
from scripts.smoke_executor import PRINCIPAL, SCENARIO, action, setup

pytestmark = pytest.mark.integration


def changed(a, **values):
    a = a.model_copy(update=values)
    return a.model_copy(update={"content_hash": action_hash(a)})


async def environment(c):
    await migrate(c)
    p, world = await setup(c)
    registry = await compose(p, world=world, config="presence:twin,energy:twin")
    await registry.start()
    _, current = world.read()
    for member, presence in current.presence.items():
        if presence.present and presence.zone_id is None:
            world.member_event(
                member, "arrive", world.entity("hvac.living_room", "devices")
            )
    await ingest(p, registry, PRINCIPAL)
    return p, world, registry, Executor(p, registry, world=world)


def bounded(world, seconds=30):
    a = action(world)
    return changed(
        a,
        revert=Revert(
            after_s=seconds,
            inverse=Inverse.model_validate(
                {"class": a.action_class, "target": a.target, "params": {"on": False}}
            ),
        ),
    )


def test_queue_worker_rollback_and_duplicate(scratch_database):
    async def run():
        async with connect(scratch_database) as c:
            p, w, r, e = await environment(c)
            try:
                a = action(w)
                boundary = p.boundary
                p.boundary = AsyncMock()
                d = await p.enqueue(a, PRINCIPAL)
                assert d.status == "executing" and d.boundary.result == "not_evaluated"
                p.boundary.authorize.assert_not_called()
                p.boundary = boundary
                assert (await e.sweep())[0].status == "verified"
                assert (await p.enqueue(a, PRINCIPAL)).status == "verified"
                assert not await e.sweep()
                rollback = await e.rollback(
                    a.action_id, PRINCIPAL, by=w.clock() + timedelta(seconds=30)
                )
                assert rollback.status == "executing"
                assert (await e.sweep())[0].status == "verified"
                assert state(w, a)["on"] is False
                async with c.begin():
                    assert (
                        await c.scalar(
                            sa.select(sa.func.count())
                            .select_from(db.actions)
                            .where(db.actions.c.execution_attempt_seq.is_not(None))
                        )
                        == 2
                    )
            finally:
                await r.close()

    asyncio.run(run())


def test_sleep_at_execution_and_revoked_identity(scratch_database):
    async def run():
        async with connect(scratch_database) as c:
            p, w, r, e = await environment(c)
            try:
                a = action(w, "energy.hvac_adjust")
                assert (await p.enqueue(a, PRINCIPAL)).status == "executing"
                w.clock.jump(w.clock() + timedelta(seconds=1))
                member = next(
                    i for i, m in w.members.items() if m.display_name == "Malik"
                )
                zone = w.entity(a.target.entity, "devices")
                w.member_event(member, "arrive", zone)
                w.member_event(member, "sleep", zone)
                result = await e.sweep()
                assert result[0].decision == "ask", result
                async with c.begin():
                    assert (await row(p, a.action_id))["execution_attempt_seq"] is None
                    assert (
                        await c.scalar(
                            sa.select(sa.func.count()).select_from(
                                db.pending_notifications
                            )
                        )
                        == 1
                    )
                b = action(w)
                assert (await p.enqueue(b, PRINCIPAL)).status == "executing"
                async with c.begin():
                    await c.execute(
                        db.member_accounts.delete().where(
                            db.member_accounts.c.sub == "malik"
                        )
                    )
                await e.sweep()
                async with c.begin():
                    assert (await row(p, b.action_id))["execution_attempt_seq"] is None
            finally:
                await r.close()

    asyncio.run(run())


def test_bounded_end_survives_pause_restart_and_tampering(scratch_database):
    async def run():
        async with connect(scratch_database) as c:
            p, w, r, e = await environment(c)
            try:
                a = bounded(w)
                assert (await p.enqueue(a, PRINCIPAL)).status == "executing"
                assert (await e.sweep())[0].status == "verified"
                assert state(w, a)["on"] is True
                pause = governance(p, "pause_automation", {}, PRINCIPAL)
                assert (await p.redeem(pause, PRINCIPAL)).decision == "execute"
                new_world = LoadedScenario(SCENARIO).world
                await restore(p, new_world)
                assert new_world.clock() < w.clock() + timedelta(seconds=1)
                assert state(new_world, a)["on"] is True
                w.clock.jump(w.clock() + timedelta(seconds=31))
                from hirz.pipeline.models import Decision

                original_end = ending(a)
                tampered = changed(
                    original_end,
                    params={"on": True},
                    expected_effect=original_end.expected_effect.model_copy(
                        update={"value": True}
                    ),
                )
                async with c.begin():
                    end_row = await row(p, original_end.action_id)
                    await c.execute(
                        db.actions.update()
                        .where(db.actions.c.action_id == original_end.action_id)
                        .values(
                            proposal=tampered.model_dump(mode="json", by_alias=True)
                        )
                    )
                with pytest.raises(Exception):
                    await p.claim_execution(
                        tampered,
                        Decision.model_validate(end_row["lifecycle"]["decision"]),
                    )
                async with c.begin():
                    assert (await row(p, original_end.action_id))[
                        "execution_attempt_seq"
                    ] is None
                    await c.execute(
                        db.actions.update()
                        .where(db.actions.c.action_id == original_end.action_id)
                        .values(
                            proposal=original_end.model_dump(mode="json", by_alias=True)
                        )
                    )
                # Policy becomes NEVER after the opening; the exact ending survives.
                raw = p.bundle.policy().model_dump()
                raw["autonomy"]["environment"]["lights"]["mode"] = "never"
                del raw["per_role"]["guest"]["environment.lights"]
                p.bundle = await PolicyBundle.validate(
                    p.household_id,
                    type(p.bundle.policy()).model_validate(raw),
                    p.boundary,
                )
                assert (await e.sweep())[0].status == "verified"
                assert state(w, a)["on"] is False
                assert not await e.sweep()
                changed_world = LoadedScenario(SCENARIO).world
                changed_world.config = changed_world.config.model_copy(
                    update={"seed": 42}
                )
                with pytest.raises(ValueError, match="configuration"):
                    await restore(p, changed_world)
            finally:
                await r.close()

    asyncio.run(run())


def test_overlap_expiry_audit_failure_and_concurrent_workers(scratch_database):
    async def run():
        async with connect(scratch_database) as c:
            p, w, r, e = await environment(c)
            try:
                a = bounded(w)
                await p.enqueue(a, PRINCIPAL)
                with pytest.raises(Exception):
                    await p.enqueue(changed(a, action_id=uuid4().hex), PRINCIPAL)
                w.clock.jump(w.clock() + timedelta(seconds=31))
                assert (await e.sweep())[0].status == "skipped"
                b = action(w)
                await p.enqueue(b, PRINCIPAL)
                append = p.audit.append
                p.audit.append = AsyncMock(
                    side_effect=RuntimeError("audit unavailable")
                )
                with pytest.raises(Exception):
                    await e.sweep()
                p.audit.append = append
                async with c.begin():
                    assert (await row(p, b.action_id))["execution_attempt_seq"] is None
                # Hold the worker lock on a different session, then release it.
                async with connect(scratch_database) as other:
                    key = int.from_bytes(p.household_id.bytes[:8], "big", signed=True)
                    async with other.begin():
                        await other.execute(
                            sa.text("SELECT pg_advisory_lock(:key)"), {"key": key}
                        )
                    assert not await e.sweep()
                    async with other.begin():
                        await other.execute(
                            sa.text("SELECT pg_advisory_unlock(:key)"), {"key": key}
                        )
                assert (await e.sweep())[0].status == "verified"
                # A late opening keeps the original end instead of extending it.
                late = bounded(w)
                await p.enqueue(late, PRINCIPAL)
                w.clock.jump(w.clock() + timedelta(seconds=15))
                assert (await e.sweep())[0].status == "verified"
                async with c.begin():
                    assert (await row(p, ending(late).action_id))["due_at"] == (
                        late.scheduled_for + timedelta(seconds=30)
                    )
                w.clock.jump(late.scheduled_for + timedelta(seconds=31))
                assert (await e.sweep())[0].status == "verified"
                assert state(w, late)["on"] is False
            finally:
                await r.close()

    asyncio.run(run())


def proposal(w, *, supersedes=None, version=1, cost=1):
    from hirz.pipeline.models import Plan

    a = action(w)
    plan_id = uuid4().hex
    a = changed(a, plan_id=plan_id)
    plan = Plan.model_validate(
        dict(
            plan_id=plan_id,
            household_id=w.household.id,
            version=version,
            supersedes=supersedes,
            horizon={"start": w.clock(), "end": w.clock() + timedelta(minutes=5)},
            goals=["Synthetic consent fixture"],
            constraints=[],
            actions=[a.action_id],
            summary=dict(
                estimated_savings_usd=None,
                peak_kwh_avoided=None,
                grid_kwh=0,
                solar_kwh=0,
                exported_kwh=0,
                electricity_usd=cost,
                wear_usd=0,
                comfort_violations_minutes=0,
            ),
            alternatives=[],
            explain={},
            speakable={"headline": "Synthetic test plan"},
            method="greedy",
            comparison_validity={"valid": False, "reasons": ["Synthetic test fixture"]},
        )
    )
    return plan, (a,)


def test_plan_consent_revision_budget_cancel_and_attribution(scratch_database):
    async def run():
        async with connect(scratch_database) as c:
            p, w, r, e = await environment(c)
            try:
                service = PlanService(p)
                plan, actions = proposal(w)
                assert (
                    await service.record(plan, actions, PRINCIPAL)
                ).decision == "execute"
                assert (
                    await p.redeem(actions[0], PRINCIPAL, cost=Decimal(0))
                ).decision == "deny"
                approved = await service.approve(plan.plan_id, PRINCIPAL)
                assert approved.decision == "execute", approved.model_dump_json()
                async with c.begin():
                    stored = await row(p, actions[0].action_id)
                    assert stored["principal"]["sub"] == "malik"
                    assert stored["principal"]["surface"] == "scheduler"
                revision, revised = proposal(
                    w, supersedes=plan.plan_id, version=2, cost=2
                )
                assert (
                    await service.revise(revision, revised, PRINCIPAL)
                ).decision == "execute"
                async with c.begin():
                    assert (await row(p, actions[0].action_id))[
                        "execution_status"
                    ] == "cancelled"
                    assert (await row(p, revised[0].action_id))[
                        "execution_status"
                    ] is None
                assert not await e.sweep()
                assert (
                    await service.approve(revision.plan_id, PRINCIPAL)
                ).decision == "execute"
                async with c.begin():
                    budget = await p.usage(
                        "energy.optimize_cost",
                        w.clock()
                        .astimezone(__import__("zoneinfo").ZoneInfo("America/Chicago"))
                        .date()
                        .isoformat(),
                    )
                    assert budget == Decimal(3)
                assert (await e.sweep())[0].status == "verified"
                assert (
                    await service.cancel(revision.plan_id, PRINCIPAL)
                ).decision == "execute"
            finally:
                await r.close()

    asyncio.run(run())


def test_plan_role_restrictions_refreshing_and_cross_household(scratch_database):
    async def run():
        async with connect(scratch_database) as c:
            p, w, r, e = await environment(c)
            try:
                service = PlanService(p)
                plan, actions = proposal(w)
                unknown = PRINCIPAL.model_copy(update={"sub": "unlinked"})
                lowered = PRINCIPAL.model_copy(update={"claimed_role": "child"})
                assert (await service.record(plan, actions, unknown)).decision == "deny"
                assert (await service.record(plan, actions, lowered)).decision == "deny"
                foreign = plan.model_copy(update={"household_id": uuid4()})
                assert (
                    await service.record(foreign, actions, PRINCIPAL)
                ).decision == "deny"
                assert (
                    await service.record(plan, actions, PRINCIPAL)
                ).decision == "execute"
                assert (
                    await service.approve(plan.plan_id, PRINCIPAL)
                ).decision == "execute"
                pause = governance(p, "pause_automation", {}, PRINCIPAL)
                await p.redeem(pause, PRINCIPAL)
                assert (await e.sweep())[0].decision == "ask"
                with pytest.raises(ValueError, match="consent"):
                    await service.approve(plan.plan_id, PRINCIPAL)
                async with c.begin():
                    document = await c.scalar(sa.select(db.plans.c.document))
                    assert document["status"] == "refreshing"
                    assert (await row(p, actions[0].action_id))[
                        "execution_attempt_seq"
                    ] is None
            finally:
                await r.close()

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["mismatch", "hard", "crash"])
def test_ha_fresh_retry_never_resends_original(scratch_database, tmp_path, failure):
    async def run():
        import httpx
        from test_ha_database import prepare

        from hirz.adapters.registry import Registry
        from hirz.pipeline.models import ExpectedEffect
        from tests.unit.test_ha import (
            ASSETS,
            BINDINGS,
            CONFIG,
            HOUSEHOLD,
            Recorded,
            adapter,
            ha_action,
        )

        async with connect(scratch_database) as c:
            p = await prepare(c)
            clock = [p.clock()]

            def tick():
                clock[0] += timedelta(microseconds=10)
                return clock[0]

            p.clock = tick
            recorded = Recorded()
            for v in recorded.states.values():
                v["last_updated"] = (tick() - timedelta(milliseconds=1)).isoformat()

            def transport(request):
                if request.method == "POST":
                    for v in recorded.states.values():
                        v["last_updated"] = tick().isoformat()
                    if failure == "hard" and not any(
                        q.method == "POST" for q in recorded.calls
                    ):
                        recorded.calls.append(request)
                        return httpx.Response(500, json={})
                return recorded(request)

            a = adapter(
                tmp_path, recorded, pipeline=p, transport=httpx.MockTransport(transport)
            )
            registry = Registry(
                HOUSEHOLD,
                assets=ASSETS,
                bindings=BINDINGS,
                factories={("devices", "ha"): lambda h: a},
                sources={
                    ("devices", "ha", b.asset_id): CONFIG.entities[b.entity_id].source
                    for b in BINDINGS
                },
                config="devices:ha",
                clock=p.clock,
            )
            # Registry needs household members to validate readings, although this
            # recorded integration supplies only device streams.
            await registry.start()
            try:
                x = ha_action(
                    scheduled_for=tick(),
                    expected_effect=ExpectedEffect(
                        entity="light.demo",
                        attr="on",
                        value=True,
                        by=tick() + timedelta(seconds=120),
                    ),
                )
                assert (await p.enqueue(x, PRINCIPAL)).status == "executing"
                executor = Executor(p, registry)
                if failure == "mismatch":
                    recorded.apply = False
                if failure == "crash":
                    d = await p.redeem(x, PRINCIPAL)
                    await p.claim_execution(x, d)
                first = await executor.sweep()
                assert first[0].status == "failed", first
                async with c.begin():
                    originals = await row(p, x.action_id)
                    assert originals["execution_attempt_seq"] is not None
                    retry_id = await c.scalar(
                        sa.select(db.actions.c.action_id).where(
                            db.actions.c.lifecycle["retry_of"].astext == x.action_id
                        )
                    )
                    assert retry_id and retry_id != x.action_id
                recorded.apply = True
                assert (await executor.sweep())[0].status == "verified"
                assert not await executor.sweep()
                posts = [q for q in recorded.calls if q.method == "POST"]
                assert len(posts) == (1 if failure == "crash" else 2)
                async with c.begin():
                    assert (await row(p, x.action_id))[
                        "execution_attempt_seq"
                    ] == originals["execution_attempt_seq"]
            finally:
                await registry.close()

    asyncio.run(run())


def test_queued_approval_ttl_and_boundary_failure(scratch_database):
    async def run():
        async with connect(scratch_database) as c:
            p, w, r, e = await environment(c)
            try:
                raw = p.bundle.policy().model_dump()
                raw["per_role"]["owner"] = {"environment.lights": {"mode": "ask"}}
                p.bundle = await PolicyBundle.validate(
                    p.household_id,
                    type(p.bundle.policy()).model_validate(raw),
                    p.boundary,
                )
                a = action(w, seconds=3600)
                ask = await p.enqueue(a, PRINCIPAL)
                assert ask.approval
                await p.vote(ask.approval.approval_id, PRINCIPAL, approved=True)
                assert (
                    await p.enqueue(a, PRINCIPAL, approval_id=ask.approval.approval_id)
                ).status == "executing"
                w.clock.jump(ask.approval.expires_at + timedelta(seconds=1))
                assert (await e.sweep())[0].event_type == "DENY_APPROVAL_EXPIRED"
                async with c.begin():
                    assert (await row(p, a.action_id))["execution_attempt_seq"] is None
            finally:
                await r.close()

    asyncio.run(run())


def test_autonomous_revision_inherits_and_cancellation_retains_ending(scratch_database):
    async def run():
        async with connect(scratch_database) as c:
            p, w, r, e = await environment(c)
            try:
                service = PlanService(p)
                plan, actions = proposal(w)
                a = changed(bounded(w, 60), plan_id=plan.plan_id)
                plan = plan.model_copy(update={"actions": (a.action_id,)})
                assert (
                    await service.record(plan, (a,), PRINCIPAL)
                ).decision == "execute"
                assert (
                    await service.approve(plan.plan_id, PRINCIPAL)
                ).decision == "execute"
                assert (await e.sweep())[0].status == "verified"
                await service.cancel(plan.plan_id, PRINCIPAL)
                async with c.begin():
                    assert (await row(p, ending(a).action_id))[
                        "execution_status"
                    ] == "scheduled"
                w.clock.jump(w.clock() + timedelta(seconds=61))
                assert (await e.sweep())[0].status == "verified"
                assert state(w, a)["on"] is False
                plan2, actions2 = proposal(w)
                await service.record(plan2, actions2, PRINCIPAL)
                assert (
                    await service.approve(plan2.plan_id, PRINCIPAL)
                ).decision == "execute"
                newer, newest = proposal(w, supersedes=plan2.plan_id, version=2)
                scheduler = PRINCIPAL.model_copy(update={"surface": "scheduler"})
                result = await service.revise(newer, newest, scheduler, autonomous=True)
                assert result.decision == "execute", result.model_dump_json()
                async with c.begin():
                    stored = await row(p, newest[0].action_id)
                    assert stored["principal"]["sub"] == "malik"
                    assert stored["principal"]["surface"] == "scheduler"
            finally:
                await r.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "name,entity,params,stop,attr,value",
    [
        (
            "energy.ev_charge",
            "ev",
            {"charging": True, "charge_limit": 0.5},
            {"charging": False},
            "charging",
            True,
        ),
        (
            "energy.battery_dispatch",
            "home_battery",
            {"dispatch_kw": 2},
            {"dispatch_kw": 0},
            "dispatch_kw",
            2,
        ),
        ("energy.appliance_start", "dishwasher", {}, None, "on", True),
    ],
)
def test_twin_controls_and_bounded_stop(
    scratch_database, name, entity, params, stop, attr, value
):
    async def run():
        from hirz.pipeline.models import ExpectedEffect, Target

        async with connect(scratch_database) as c:
            p, w, r, e = await environment(c)
            try:
                target = Target(adapter="twin", entity=entity)
                a = changed(
                    action(w),
                    action_class=name,
                    target=target,
                    params=params,
                    expected_effect=ExpectedEffect(
                        entity=entity,
                        attr=attr,
                        value=value,
                        by=w.clock() + timedelta(seconds=20),
                    ),
                    revert=Revert(
                        after_s=20,
                        inverse=Inverse.model_validate(
                            {"class": name, "target": target, "params": stop}
                        ),
                    )
                    if stop
                    else None,
                )
                queued = await p.enqueue(a, PRINCIPAL)
                assert queued.status == "executing", queued.model_dump_json()
                result = await e.sweep()
                assert result[0].status == "verified", result
                assert state(w, a)[attr] == value
                if stop:
                    w.clock.jump(w.clock() + timedelta(seconds=21))
                    ended = await e.sweep()
                    assert ended[0].status == "verified", ended
                    assert state(w, a)[attr] == stop[attr]
            finally:
                await r.close()

    asyncio.run(run())
