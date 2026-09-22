# ruff: noqa: F811

"""Real durable refresh state, consent races and rollback in disposable PostgreSQL."""

import asyncio
from datetime import timedelta

import pytest
from test_database import connect, scratch_database  # noqa: F401
from test_executor_database import environment

from hirz.executor.plans import PlanService, get
from hirz.executor.refresh import job
from hirz.executor.refresh_worker import RefreshWorker
from hirz.executor.runtime import RuntimeInputs
from hirz.planner.models import PlannerInput, Slot, Zone, boundaries
from hirz.planner.service import plan
from scripts.smoke_executor import PRINCIPAL

pytestmark = pytest.mark.integration


async def prepared(c):
    p, w, registry, executor = await environment(c)
    async with c.begin():
        requester = await p.requester(PRINCIPAL)
    start = w.clock()
    edges = boundaries(start, start + timedelta(hours=2))
    physical = w.read()[1].zones[w.entity("hvac.living_room", "devices")]
    slots = tuple(
        Slot(start=a, end=b, price=0.1, outdoor_f=70, solar_kw=0)
        for a, b in zip(edges, edges[1:])
    )
    inputs = PlannerInput(
        household_id=p.household_id,
        requester=requester,
        slots=slots,
        ev=None,
        ev_target=0,
        ev_deadline=edges[-1],
        battery=None,
        appliance=None,
        appliance_release=start,
        appliance_deadline=edges[-1],
        base_load_kw=0.4,
        zones=(
            Zone(
                entity="hvac.living_room",
                physical=physical,
                lower=(66,) * len(slots),
                upper=(76,) * len(slots),
                targets=(70,) * len(slots),
                occupants=(0,) * len(slots),
            ),
        ),
        provenance=("Explicit test workload",),
    )
    result = plan(inputs)
    assert result.plan and result.schedule
    runtime = RuntimeInputs.from_schedule(inputs, result.schedule)
    service = PlanService(p)
    recorded = await service.record(
        result.plan, result.actions, PRINCIPAL, runtime=runtime
    )
    assert recorded.decision == "execute", recorded
    return p, w, registry, executor, service, result, runtime


def test_refresh_generation_coalescing_and_explicit_consent(scratch_database):
    async def run():
        async with connect(scratch_database) as c:
            p, w, r, e, service, result, runtime = await prepared(c)
            try:
                assert (
                    await service.approve(result.plan.plan_id, PRINCIPAL)
                ).decision == "execute"
                assert (
                    await service.request_refresh(result.plan.plan_id, PRINCIPAL)
                ).decision == "execute"
                assert (
                    await service.request_refresh(result.plan.plan_id, PRINCIPAL)
                ).decision == "execute"
                async with c.begin():
                    stored = await get(p, result.plan.plan_id)
                    current = await job(p, stored)
                    assert current["requested_generation"] == 1
                    assert current["explicit"]
                held = await service.read_current(result.plan.plan_id, PRINCIPAL)
                assert (
                    held.status == "refreshing"
                    and held.summary.estimated_savings_usd is None
                )
                with pytest.raises(ValueError, match="consent"):
                    await service.approve(result.plan.plan_id, PRINCIPAL)
                await RefreshWorker(p, r, world=w).batch()
                async with c.begin():
                    current = await job(p, stored)
                    assert current["state"] == "idle", current
                    replacement = await get(p, current["plan_id"])
                    assert replacement["document"]["status"] == "proposed"
                    assert replacement["document"]["supersedes"] == result.plan.plan_id
            finally:
                await r.close()

    asyncio.run(run())


def test_five_minute_refresh_inherits_consent(scratch_database):
    async def run():
        async with connect(scratch_database) as c:
            p, w, r, e, service, result, runtime = await prepared(c)
            try:
                assert (
                    await service.approve(result.plan.plan_id, PRINCIPAL)
                ).decision == "execute"
                w.clock.jump(w.clock() + timedelta(minutes=5))
                await RefreshWorker(p, r, world=w).batch()
                async with c.begin():
                    current = await job(p, await get(p, result.plan.plan_id))
                    assert current["state"] == "idle", current
                    replacement = await get(p, current["plan_id"])
                    assert replacement["document"]["status"] == "approved", replacement
                    assert replacement["approver"]["sub"] == "malik"
                outcomes = await e.sweep()
                async with c.begin():
                    debug_job = await job(p, replacement)
                assert outcomes[0].status == "verified", (outcomes, debug_job)
            finally:
                await r.close()

    asyncio.run(run())


def test_refresh_obsolescence_restart_cancel_and_audit_rollback(
    scratch_database, monkeypatch
):
    from unittest.mock import AsyncMock

    import hirz.executor.refresh_worker as module

    async def run():
        async with connect(scratch_database) as c:
            p, w, r, e, service, result, runtime = await prepared(c)
            try:
                await service.approve(result.plan.plan_id, PRINCIPAL)
                await service.request_refresh(
                    result.plan.plan_id, PRINCIPAL, explicit=False
                )
                # Persist running ownership, then reconstruct the worker as after a crash.
                scheduler = PRINCIPAL.model_copy(update={"surface": "scheduler"})
                async with p.repo.write(p.clock):
                    stored = await get(p, result.plan.plan_id)
                    current = await job(p, stored)
                    await RefreshWorker(p, r, world=w).transition(
                        stored,
                        current["requested_generation"],
                        scheduler,
                        state="running",
                        running_generation=1,
                        attempts=1,
                    )
                original = module.coordinate
                import threading

                started, finish = threading.Event(), threading.Event()

                def delayed(*args, **kwargs):
                    started.set()
                    assert finish.wait(10)
                    return original(*args, **kwargs)

                monkeypatch.setattr(module, "coordinate", delayed)
                task = asyncio.create_task(RefreshWorker(p, r, world=w).batch())
                await asyncio.to_thread(started.wait, 10)
                # Same connection is idle during solve; simulate a newly arriving explicit change.
                await service.request_refresh(
                    result.plan.plan_id, PRINCIPAL, reason="change", explicit=True
                )
                finish.set()
                await task
                async with c.begin():
                    current = await job(p, stored)
                    assert current["state"] == "queued" and current["explicit"]
                    assert current["plan_id"] == result.plan.plan_id
                monkeypatch.setattr(module, "coordinate", original)
                await service.cancel(result.plan.plan_id, PRINCIPAL)
                await RefreshWorker(p, r, world=w).batch()
                async with c.begin():
                    assert (await job(p, stored))["state"] == "cancelled"
                # Failed audit must roll back both mutation and generation.
                append = p.audit.append
                p.audit.append = AsyncMock(
                    side_effect=RuntimeError("audit unavailable")
                )
                with pytest.raises(Exception):
                    await service.request_refresh(result.plan.plan_id, PRINCIPAL)
                p.audit.append = append
            finally:
                await r.close()

    asyncio.run(run())


def test_transient_retry_schedule_and_honest_block(scratch_database, monkeypatch):
    import hirz.executor.refresh_worker as module

    async def run():
        async with connect(scratch_database) as c:
            p, w, r, e, service, result, runtime = await prepared(c)
            try:
                await service.request_refresh(result.plan.plan_id, PRINCIPAL)

                def fail(*args, **kwargs):
                    raise RuntimeError("temporary solver failure")

                monkeypatch.setattr(module, "coordinate", fail)
                for delay in (5, 30, 60, 300, 300):
                    at = w.clock()
                    await RefreshWorker(p, r, world=w).batch()
                    async with c.begin():
                        current = await job(p, await get(p, result.plan.plan_id))
                        assert current["state"] == "queued"
                        assert current["next_retry"] == at + timedelta(seconds=delay)
                    # --once semantics: future retries are not awaited or attempted.
                    await RefreshWorker(p, r, world=w).batch()
                    w.clock.jump(current["next_retry"])
                reference = await service.read_current(result.plan.plan_id, PRINCIPAL)
                assert not reference.comparison_validity.valid
                assert reference.summary.estimated_savings_usd is None
                assert "temporarily failed" in reference.speakable["details"][1]
                await service.request_refresh(result.plan.plan_id, PRINCIPAL)
                await RefreshWorker(p, r, world=w).batch()
                import sqlalchemy as sa

                from hirz import db

                async with c.begin():
                    assert (
                        await c.scalar(
                            sa.select(sa.func.count()).select_from(
                                db.pending_notifications
                            )
                        )
                        == 1
                    )
            finally:
                await r.close()

    asyncio.run(run())


def test_manual_hold_first_sample_renewal_release_and_expiry(scratch_database):
    from uuid import uuid4

    from hirz.executor.observations import ingest
    from hirz.planner.coordinator import Coordinator
    from hirz.twin.physics import changed

    async def run():
        async with connect(scratch_database) as c:
            p, w, r, e, service, result, runtime = await prepared(c)
            try:
                async with c.begin():
                    assert not (await p.snapshot(w.clock())).data["constraints"]
                asset = w.entity("hvac.living_room", "devices")
                for target in (72, 73):
                    w.clock.jump(w.clock() + timedelta(seconds=1))
                    current = w.read()[1]
                    w._state = changed(
                        current,
                        zones=current.zones
                        | {asset: changed(current.zones[asset], target_f=target)},
                    )
                    await ingest(p, r, PRINCIPAL)
                async with c.begin():
                    rows = (await p.snapshot(w.clock())).data["constraints"]
                    active = [x for x in rows if x.get("withdrawn_at") is None]
                    assert len(active) == 1
                    assert active[0]["provenance"]["source"] == "manual:device"
                    assert active[0]["provenance"]["encoded"]["value"] == 73
                    from datetime import datetime

                    from hirz.graph.models import ConstraintRecord
                    from hirz.planner.coordinator import active as is_active
                    from hirz.planner.coordinator import clean

                    record = ConstraintRecord.model_validate(clean(active[0]))
                    end = datetime.fromisoformat(
                        active[0]["provenance"]["encoded"]["ends_at"]
                    )
                    assert end - record.spec.starts_at == timedelta(hours=2)
                    assert is_active(record, end - timedelta(microseconds=1), end)
                    assert not is_active(record, end, end + timedelta(minutes=1))
                w.clock.jump(w.clock() + timedelta(seconds=1))
                release = await Coordinator(p).intake(
                    PRINCIPAL,
                    action_id=uuid4().hex,
                    text="release living room hold",
                    horizon_end=result.plan.horizon.end,
                )
                assert release.decision.decision == "execute"
                async with c.begin():
                    assert all(
                        x.get("withdrawn_at") is not None
                        for x in (await p.snapshot(w.clock())).data["constraints"]
                    )
            finally:
                await r.close()

    asyncio.run(run())


def test_concurrent_refresh_does_not_delay_authorized_ending(
    scratch_database, monkeypatch
):
    import threading

    from test_executor_database import bounded

    import hirz.executor.refresh_worker as module
    from hirz.executor.contracts import ending
    from hirz.executor.service import Executor
    from hirz.executor.storage import row
    from hirz.pipeline.service import Pipeline

    async def run():
        async with connect(scratch_database) as c, connect(scratch_database) as c2:
            p, w, r, e, service, result, runtime = await prepared(c)
            finish = threading.Event()
            task = None
            try:
                opening = bounded(w)
                await p.enqueue(opening, PRINCIPAL)
                assert (await e.sweep())[0].status == "verified"
                await service.approve(result.plan.plan_id, PRINCIPAL)
                await service.request_refresh(
                    result.plan.plan_id, PRINCIPAL, explicit=False
                )
                original = module.coordinate
                started = threading.Event()

                def delayed(*args, **kwargs):
                    started.set()
                    assert finish.wait(20)
                    return original(*args, **kwargs)

                monkeypatch.setattr(module, "coordinate", delayed)
                task = asyncio.create_task(RefreshWorker(p, r, world=w).batch())
                assert await asyncio.to_thread(started.wait, 10)
                second = Pipeline(c2, p.bundle, p.boundary, p.audit, w.clock)
                # Another session cannot start a second solver for this household.
                await asyncio.wait_for(RefreshWorker(second, r, world=w).batch(), 1)
                w.clock.jump(w.clock() + timedelta(seconds=30))
                outcomes = await Executor(second, r, world=w).sweep(endings_only=True)
                assert outcomes[0].status == "verified"
                async with c2.begin():
                    assert (await row(second, ending(opening).action_id))[
                        "execution_status"
                    ] == "verified"
                finish.set()
                await task
                async with c.begin():
                    assert (await row(p, opening.action_id))[
                        "execution_attempt_seq"
                    ] is not None
            finally:
                finish.set()
                if task:
                    await asyncio.gather(task, return_exceptions=True)
                await r.close()

    asyncio.run(run())


def test_poll_failure_recovers_without_new_consent_and_revocation_blocks(
    scratch_database, monkeypatch
):
    from unittest.mock import AsyncMock

    from hirz import db
    from hirz.executor import observations

    async def run():
        async with connect(scratch_database) as c:
            p, w, r, e, service, result, runtime = await prepared(c)
            try:
                await service.approve(result.plan.plan_id, PRINCIPAL)
                worker = RefreshWorker(p, r, world=w)
                original = observations.ingest
                monkeypatch.setattr(
                    observations, "ingest", AsyncMock(side_effect=TimeoutError())
                )
                for delay in (5, 30):
                    await worker.batch()
                    async with c.begin():
                        current = await job(p, await get(p, result.plan.plan_id))
                        assert current["state"] == "queued"
                        assert current["next_retry"] == w.clock() + timedelta(
                            seconds=delay
                        )
                    assert not await e.sweep(endings_only=True)
                    w.clock.jump(current["next_retry"])
                monkeypatch.setattr(observations, "ingest", original)
                await worker.batch()
                async with c.begin():
                    current = await job(p, await get(p, result.plan.plan_id))
                    assert current["state"] == "idle", current
                    replacement = await get(p, current["plan_id"])
                    assert replacement["approver"]["sub"] == "malik"
                await service.request_refresh(
                    replacement["plan_id"], PRINCIPAL, explicit=False
                )
                # Simulated external account revocation, as in the existing identity gate tests.
                async with c.begin():
                    await c.execute(
                        db.member_accounts.delete().where(
                            db.member_accounts.c.sub == "malik"
                        )
                    )
                await worker.batch()
                async with c.begin():
                    current = await job(p, replacement)
                    assert current["state"] == "blocked"
                    assert "authority" in current["blocking_reason"]
                with pytest.raises(ValueError, match="linked"):
                    await service.read_current(replacement["plan_id"], PRINCIPAL)
                assert not await e.sweep()
            finally:
                await r.close()

    asyncio.run(run())


def test_refused_budget_increase_rolls_back_reservation_and_publication(
    scratch_database,
):
    from decimal import Decimal

    import sqlalchemy as sa

    from hirz import db
    from hirz.executor.budget import transfer
    from hirz.twin.physics import changed

    async def run():
        async with connect(scratch_database) as c:
            p, w, r, e, service, result, runtime = await prepared(c)
            try:
                await service.approve(result.plan.plan_id, PRINCIPAL)
                expensive = changed(runtime.workload, base_load_kw=1000)
                updated = changed(
                    runtime, workload=expensive, prediction_workload=runtime.workload
                )
                await service.update_inputs(
                    result.plan.plan_id, updated, PRINCIPAL, explicit=False
                )
                async with c.begin():
                    before = await get(p, result.plan.plan_id)
                    allocations = before["reservation"]
                await RefreshWorker(p, r, world=w).batch()
                async with c.begin():
                    old = await get(p, result.plan.plan_id)
                    current = await job(p, old)
                    assert current["state"] == "blocked", current
                    assert "budget" in current["blocking_reason"], current
                    assert current["plan_id"] == result.plan.plan_id
                    assert old["reservation"] == allocations
                    assert not await c.scalar(
                        sa.select(sa.func.count())
                        .select_from(db.audit_log)
                        .where(db.audit_log.c.event_type == "RESERVATION_ADJUSTED")
                    )
                # A transaction failure after a release cannot change the grant ledger either.
                with pytest.raises(RuntimeError):
                    async with p.repo.write(p.clock):
                        await transfer(p, old, updated, ())
                        raise RuntimeError("publication transaction failed")
                async with c.begin():
                    assert not await c.scalar(
                        sa.select(sa.func.count())
                        .select_from(db.audit_log)
                        .where(db.audit_log.c.event_type == "RESERVATION_ADJUSTED")
                    )
                    assert (
                        sum(Decimal(a["amount"]) for a in allocations["allocations"])
                        > 0
                    )
            finally:
                await r.close()

    asyncio.run(run())


def test_same_instant_consent_race_legacy_inputs_and_household_isolation(
    scratch_database,
):
    from dataclasses import replace
    from uuid import uuid4

    from hirz.pipeline.service import Pipeline

    async def run():
        async with connect(scratch_database) as c, connect(scratch_database) as c2:
            p, w, r, e, service, result, runtime = await prepared(c)
            try:
                second = Pipeline(c2, p.bundle, p.boundary, p.audit, w.clock)
                outcomes = await asyncio.gather(
                    service.approve(result.plan.plan_id, PRINCIPAL),
                    PlanService(second).request_refresh(result.plan.plan_id, PRINCIPAL),
                    return_exceptions=True,
                )
                assert any(getattr(d, "decision", None) == "execute" for d in outcomes)
                async with c.begin():
                    stored = await get(p, result.plan.plan_id)
                    assert stored["document"]["status"] == "refreshing"
                    assert (await job(p, stored))["explicit"]
                assert not await e.sweep()
                await service.cancel(result.plan.plan_id, PRINCIPAL)
                # An old proposal survives, but cannot consent without full runtime inputs.
                from hirz.twin.physics import changed

                legacy_inputs = changed(runtime.workload, base_load_kw=0.41)
                legacy = plan(legacy_inputs)
                assert legacy.plan and legacy.schedule
                legacy_runtime = RuntimeInputs.from_schedule(
                    legacy_inputs, legacy.schedule
                )
                assert (
                    await service.record(legacy.plan, legacy.actions, PRINCIPAL)
                ).decision == "execute"
                historical = await service.read_current(legacy.plan.plan_id, PRINCIPAL)
                assert not historical.comparison_validity.valid
                assert "Complete runtime" in historical.speakable["details"][1]
                with pytest.raises(ValueError, match="consent"):
                    await service.approve(legacy.plan.plan_id, PRINCIPAL)
                await service.update_inputs(
                    legacy.plan.plan_id, legacy_runtime, PRINCIPAL
                )
                await RefreshWorker(p, r, world=w).batch()
                async with c.begin():
                    current = await job(p, await get(p, legacy.plan.plan_id))
                    assert current["state"] == "idle", current
                    assert (await get(p, current["plan_id"]))["approver"] is None
                outsider = Pipeline(
                    c2,
                    replace(p.bundle, household_id=uuid4()),
                    p.boundary,
                    p.audit,
                    w.clock,
                )
                with pytest.raises(ValueError, match="linked"):
                    await PlanService(outsider).read_current(
                        legacy.plan.plan_id, PRINCIPAL
                    )
            finally:
                await r.close()

    asyncio.run(run())


def test_all_eight_triggers_queue_durable_coalesced_work(scratch_database):
    from uuid import uuid4

    from hirz.adapters.calendar.twin import TwinCalendar
    from hirz.pipeline.service import PolicyBundle
    from hirz.planner.coordinator import Coordinator
    from hirz.twin.physics import changed

    async def run():
        async with connect(scratch_database) as c:
            p, w, r, e, service, result, runtime = await prepared(c)
            try:
                r.instances[("calendar", "twin")] = TwinCalendar(w)
                await r.instances[("calendar", "twin")].start()
                worker = RefreshWorker(p, r, world=w)
                await worker.poll()

                async def generation():
                    async with c.begin():
                        return (await job(p, await get(p, result.plan.plan_id)))[
                            "requested_generation"
                        ]

                prior = await generation()
                for trigger in (
                    "price",
                    "weather",
                    "calendar",
                    "presence",
                    "prediction",
                    "constraint",
                    "constitution",
                    "change",
                ):
                    w.clock.jump(w.clock() + timedelta(seconds=1))
                    if trigger == "price":
                        w.config = changed(
                            w.config,
                            tariff=changed(
                                w.config.tariff,
                                periods=tuple(
                                    changed(
                                        period,
                                        import_cents_per_kwh=period.import_cents_per_kwh
                                        + 1,
                                    )
                                    for period in w.config.tariff.periods
                                ),
                            ),
                        )
                    elif trigger == "weather":
                        w.config = changed(
                            w.config,
                            weather=changed(
                                w.config.weather,
                                samples=tuple(
                                    changed(sample, temp_f=sample.temp_f + 1)
                                    for sample in w.config.weather.samples
                                ),
                            ),
                        )
                    elif trigger == "calendar":
                        w.calendar = tuple(
                            changed(
                                event, starts_at=event.starts_at - timedelta(minutes=1)
                            )
                            for event in w.calendar
                        )
                    elif trigger == "presence":
                        member = next(
                            i for i, m in w.members.items() if m.display_name == "Malik"
                        )
                        w.member_event(member, "leave")
                    elif trigger == "prediction":
                        state = w.read()[1]
                        asset = w.entity("hvac.living_room", "devices")
                        w._state = changed(
                            state,
                            zones=state.zones
                            | {
                                asset: changed(
                                    state.zones[asset],
                                    temp_f=state.zones[asset].temp_f + 2,
                                )
                            },
                        )
                    elif trigger == "constraint":
                        outcome = await Coordinator(p).intake(
                            PRINCIPAL,
                            action_id=uuid4().hex,
                            text="prefer living room at 72 F",
                            horizon_end=result.plan.horizon.end,
                        )
                        assert outcome.decision.decision == "execute"
                    elif trigger == "constitution":
                        policy = p.bundle.policy()
                        p.bundle = await PolicyBundle.validate(
                            p.household_id,
                            changed(policy, version=policy.version + 1),
                            p.boundary,
                        )
                    else:
                        await service.request_refresh(
                            result.plan.plan_id, PRINCIPAL, reason="change"
                        )
                    await worker.poll()
                    current = await generation()
                    assert current > prior, trigger
                    await worker.poll()
                    assert await generation() == current, trigger
                    prior = current
                async with c.begin():
                    stored = await get(p, result.plan.plan_id)
                    current = await job(p, stored)
                    assert current["state"] == "queued" and current["explicit"]
                    assert stored["document"]["status"] == "refreshing"
            finally:
                await r.close()

    asyncio.run(run())
