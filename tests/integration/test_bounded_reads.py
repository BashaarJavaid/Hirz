"""Latest bound-device attribution and transactional constraint history."""

import asyncio
from datetime import timedelta

import pytest
import sqlalchemy as sa
from test_database import connect
from test_database import scratch_database as scratch_database
from test_executor_database import changed, environment

from hirz.executor.local import compose
from hirz.executor.refresh import _verified_controls, owned_control
from hirz.executor.service import Executor
from hirz.pipeline.models import Principal
from hirz.twin.scenario import LoadedScenario
from scripts.smoke_executor import PRINCIPAL, SCENARIO, action
from scripts.smoke_tool_budget import Environment

pytestmark = pytest.mark.integration


def test_latest_verified_bound_control_at_observation_time_and_isolation(
    scratch_database, tmp_path
):
    async def run():
        async with connect(scratch_database) as c:
            p, world, registry, executor = await environment(c)
            mirror_registry = None
            try:
                fixture = Environment(c, tmp_path, "demo-evening")
                fixture.pipelines = [p]
                fixture.loaded = LoadedScenario(SCENARIO)
                fixture.loaded.world = world
                await fixture.prepare_mirror()
                other = fixture.pipelines[1]
                mirror_registry = await compose(
                    other,
                    world=fixture.mirror.world,
                    config="presence:twin,energy:twin",
                )
                await mirror_registry.start()
                other_executor = Executor(
                    other, mirror_registry, world=fixture.mirror.world
                )
                first_at = world.clock()
                ids = {}
                observations = {}
                for pipeline, twin, worker, principal in (
                    (p, world, executor, PRINCIPAL),
                    (
                        other,
                        fixture.mirror.world,
                        other_executor,
                        Principal(provider="demo", sub="malik-item26", surface="app"),
                    ),
                ):
                    first = action(twin)
                    await pipeline.enqueue(first, principal)
                    outcomes = await worker.sweep()
                    assert outcomes and all(d.status == "verified" for d in outcomes), (
                        outcomes
                    )
                    async with c.begin():
                        rows = await _verified_controls(pipeline, world.clock())
                        assert (
                            len(rows) == 1 and rows[0]["action_id"] == first.action_id
                        )
                        assert rows[0]["household_id"] == pipeline.household_id
                    observation = (
                        await (registry if pipeline is p else mirror_registry)
                        .instances[("devices", "twin")]
                        .get_state("light.living_room")
                    )
                    observations[pipeline.household_id] = observation
                    ids[pipeline.household_id] = first.action_id
                world.clock.jump(first_at + timedelta(seconds=1))
                for pipeline, twin, worker, principal in (
                    (p, world, executor, PRINCIPAL),
                    (
                        other,
                        fixture.mirror.world,
                        other_executor,
                        Principal(provider="demo", sub="malik-item26", surface="app"),
                    ),
                ):
                    second = action(twin)
                    second = changed(
                        second,
                        params={"on": False},
                        expected_effect=second.expected_effect.model_copy(
                            update={"value": False}
                        ),
                    )
                    await pipeline.enqueue(second, principal)
                    outcomes = await worker.sweep()
                    assert outcomes and all(d.status == "verified" for d in outcomes), (
                        outcomes
                    )
                    async with c.begin():
                        historical = await _verified_controls(
                            pipeline, observations[pipeline.household_id].observed_at
                        )
                        assert [r["action_id"] for r in historical] == [
                            ids[pipeline.household_id]
                        ]
                        latest = await _verified_controls(pipeline, world.clock())
                        assert [r["action_id"] for r in latest] == [second.action_id]
                        assert all(
                            r["household_id"] == pipeline.household_id for r in latest
                        )
                        observed = observations[pipeline.household_id]
                        assert await owned_control(pipeline, observed)
                        assert not await owned_control(
                            pipeline,
                            observed.model_copy(update={"observed_at": world.clock()}),
                        )
                        # Roll back a missing binding; the verified controls remain retained.
                        from hirz import db

                        await c.execute(
                            db.asset_bindings.delete().where(
                                pipeline.scope(db.asset_bindings),
                                db.asset_bindings.c.asset_id == observed.asset_id,
                            )
                        )
                        assert await _verified_controls(pipeline, world.clock()) == []
                        await c.rollback()
            finally:
                await registry.close()
                if mirror_registry:
                    await mirror_registry.close()

    asyncio.run(run())


def test_close_invalidates_snapshot_and_preserves_as_of_and_rollback(scratch_database):
    from uuid import uuid4

    from test_pipeline_database import setup

    from hirz import db
    from hirz.audit import verify_database
    from hirz.executor.plans import governance
    from hirz.graph.context import ContextService
    from hirz.planner.coordinator import Coordinator, Intake
    from tests.unit.test_pipeline import PRINCIPAL

    async def run():
        async with connect(scratch_database) as c:
            p = await setup(c, native=True)
            clock = [p.clock()]
            p.clock = lambda: clock[0]
            end = clock[0] + timedelta(hours=2)
            recorded = await Coordinator(p).intake(
                PRINCIPAL,
                action_id=uuid4().hex,
                text="car target to 50",
                horizon_end=end,
            )
            before = clock[0]
            clock[0] += timedelta(seconds=1)
            request = governance(
                p,
                "withdraw_constraint",
                Intake(
                    text="withdraw", horizon_end=end, replaces=recorded.constraint_id
                ).model_dump(mode="json"),
                PRINCIPAL,
            )
            revision = p.repo._revision
            with pytest.raises(RuntimeError, match="rollback close"):
                async with p.repo.write(p.clock):
                    assert len((await p.snapshot(p.clock())).data["constraints"]) == 1
                    result = await p.mutate_locked(request, PRINCIPAL)
                    assert result.decision == "execute"
                    assert p.repo._revision > revision
                    assert not (await p.snapshot(p.clock())).data["constraints"]
                    assert not (await p.snapshot(p.clock())).data["constraints"]
                    raise RuntimeError("rollback close")
            async with p.repo.write(p.clock):
                assert len((await p.snapshot(p.clock())).data["constraints"]) == 1
                result = await p.mutate_locked(request, PRINCIPAL)
                assert result.decision == "execute"
                assert not (await p.snapshot(p.clock())).data["constraints"]
                assert not (await p.snapshot(p.clock())).data["constraints"]
            context = ContextService(c, p.clock)
            assert not (
                await context.get_household_context(p.household_id, "constraints")
            ).data["constraints"]
            old = await context.get_household_context(
                p.household_id, "constraints", as_of=before
            )
            assert [r["id"] for r in old.data["constraints"]] == [
                str(recorded.constraint_id)
            ]
            assert not (
                await context.get_household_context(
                    p.household_id, "constraints", as_of=clock[0]
                )
            ).data["constraints"]
            archived = (
                (await c.execute(sa.select(db.HISTORY_TABLES["constraints"])))
                .mappings()
                .one()
            )
            assert archived["valid_to"] == clock[0]
            assert archived["withdrawal_decision_seq"] == result.audit_id
            await c.rollback()
            summary, rows = await verify_database(
                c, p.household_id, p.audit.key.public_key(), collect=True
            )
            assert summary["status"] == "valid"
            assert sum(r.event_type == "CONSTRAINT_WITHDRAWN" for r in rows) == 1
            assert all(
                r.payload["expired_constraint_ids"] == []
                for r in rows
                if r.event_type in {"CONSTRAINT_RECORDED", "CONSTRAINT_WITHDRAWN"}
            )

    asyncio.run(run())


@pytest.mark.parametrize("withdraw", [False, True])
def test_expired_constraints_close_in_next_granted_commit(
    scratch_database, withdraw, tmp_path
):
    from uuid import uuid4

    from test_pipeline_database import setup

    from hirz import db
    from hirz.audit import (
        export_document,
        fingerprint,
        verify_database,
        verify_file,
        write_export,
    )
    from hirz.planner.coordinator import Coordinator
    from tests.unit.test_pipeline import PRINCIPAL

    async def run():
        async with connect(scratch_database) as c:
            p = await setup(c, native=True)
            clock = [p.clock()]
            p.clock = lambda: clock[0]
            end = clock[0] + timedelta(hours=2)
            coordinator = Coordinator(p)
            expired = await coordinator.intake(
                PRINCIPAL,
                action_id=uuid4().hex,
                text="car target to 50",
                horizon_end=clock[0] + timedelta(minutes=1),
            )
            clock[0] += timedelta(seconds=1)
            live = await coordinator.intake(
                PRINCIPAL,
                action_id=uuid4().hex,
                text="car target to 60",
                horizon_end=end,
            )
            clock[0] += timedelta(minutes=1)
            outcome = await coordinator.intake(
                PRINCIPAL,
                action_id=uuid4().hex,
                text="withdraw" if withdraw else "prefer living room at 72 F",
                horizon_end=end,
                replaces=live.constraint_id if withdraw else None,
                withdraw=withdraw,
            )
            assert outcome.decision.decision == "execute"
            async with p.repo.write(p.clock):
                rows = (await p.snapshot(p.clock())).data["constraints"]
                assert str(expired.constraint_id) not in {r["id"] for r in rows}
                assert len(rows) == (0 if withdraw else 2)
                history = await p.repo.get(
                    "constraints",
                    {"id": expired.constraint_id},
                    as_of=clock[0] - timedelta(seconds=1),
                    clock=p.clock,
                )
                assert history is not None
                assert (
                    await p.repo.get(
                        "constraints",
                        {"id": expired.constraint_id},
                        as_of=clock[0],
                        clock=p.clock,
                    )
                    is None
                )
                assert (
                    await c.scalar(
                        sa.select(db.HISTORY_TABLES["constraints"].c.valid_to).where(
                            db.HISTORY_TABLES["constraints"].c.id
                            == expired.constraint_id
                        )
                    )
                    == clock[0]
                )
            summary, rows = await verify_database(
                c, p.household_id, p.audit.key.public_key(), collect=True
            )
            assert summary["status"] == "valid"
            events = [
                r
                for r in rows
                if r.event_type in {"CONSTRAINT_RECORDED", "CONSTRAINT_WITHDRAWN"}
                and r.payload["decision_seq"] == outcome.decision.audit_id
            ]
            assert len(events) == 1
            assert events[0].payload["expired_constraint_ids"] == [
                str(expired.constraint_id)
            ]
            output = tmp_path / "expiry-audit.json"
            write_export(
                output, export_document(p.household_id, p.audit.key.public_key(), rows)
            )
            verified = verify_file(
                output,
                p.household_id,
                trusted_fingerprint=fingerprint(p.audit.key.public_key()),
            )
            assert verified["status"] == "valid"

    asyncio.run(run())
