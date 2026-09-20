"""Durable HA attempts on disposable PostgreSQL; no physical devices."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from alembic.util.exc import CommandError
from test_database import connect, migrate
from test_database import scratch_database as scratch_database
from test_pipeline_database import NOW, setup

from hirz import db
from hirz.graph.repository import GraphRepository, row_model
from hirz.pipeline.audit import PipelineError
from hirz.pipeline.hashing import action_hash
from hirz.pipeline.service import Pipeline
from tests.unit.test_ha import BINDINGS, Recorded, adapter, ha_action
from tests.unit.test_pipeline import AT, HOME, PRINCIPAL

pytestmark = pytest.mark.integration


async def prepare(connection):
    p = await setup(connection, native=True)
    repo = GraphRepository(connection, HOME)
    async with repo.write(lambda: AT + timedelta(microseconds=1)):
        for binding in BINDINGS:
            old = (
                (
                    await connection.execute(
                        sa.select(db.asset_bindings).where(
                            db.asset_bindings.c.asset_id == binding.asset_id
                        )
                    )
                )
                .mappings()
                .one()
            )
            binding = binding.model_copy(update={"id": old["id"]})
            await repo.put(
                "asset_bindings", binding, expected_version=old["valid_from"]
            )
        row = await repo.get("assets", {"id": BINDINGS[1].asset_id})
        asset = row_model("assets", row).model_copy(update={"room_kind": "other"})
        await repo.put("assets", asset, expected_version=row["valid_from"])
    return p


def test_concurrent_claims_restart_and_migration_evidence(scratch_database, tmp_path):
    async def run():
        async with connect(scratch_database) as c:
            p = await prepare(c)
            x = ha_action()
            d = await p.redeem(x, PRINCIPAL)
            assert d.decision == "execute", d
            r = Recorded()

            async def execute():
                async with connect(scratch_database) as other:
                    q = Pipeline(other, p.bundle, p.boundary, p.audit, lambda: NOW)
                    a = adapter(tmp_path, r, pipeline=q)
                    await a.start()
                    try:
                        await a.set_light(x, d)
                        return "executed"
                    except PipelineError:
                        return "refused"
                    finally:
                        await a.close()

            results = await asyncio.gather(*(execute() for _ in range(8)))
            assert results.count("executed") == 1 and results.count("refused") == 7
            assert len([q for q in r.calls if q.method == "POST"]) == 1
            assert await execute() == "refused"
            assert len([q for q in r.calls if q.method == "POST"]) == 1
            types = list(
                await c.scalars(
                    sa.select(db.audit_log.c.event_type).order_by(db.audit_log.c.seq)
                )
            )
            assert types == ["EXECUTE", "EXECUTION_ATTEMPTED", "EXECUTED", "VERIFIED"]
            await c.rollback()
            with pytest.raises(CommandError, match="Migration failed"):
                await migrate(c, "downgrade", "0004_observation_domains")
            await c.rollback()
            assert (
                await c.scalar(sa.select(db.actions.c.execution_attempt_seq))
                is not None
            )
            await c.rollback()
            # Even an orphaned audit attempt prevents downgrade.
            await c.execute(db.actions.update().values(execution_attempt_seq=None))
            await c.commit()
            with pytest.raises(CommandError, match="Migration failed"):
                await migrate(c, "downgrade", "0004_observation_domains")
            await c.rollback()

    asyncio.run(run())


def test_authorization_mutations_no_dispatch(scratch_database, tmp_path):
    async def run():
        async with connect(scratch_database) as c:
            p = await prepare(c)
            x = ha_action()
            proposal = await p.propose(x, PRINCIPAL)
            r = Recorded()
            a = adapter(tmp_path, r, pipeline=p)
            await a.start()
            try:
                with pytest.raises(PipelineError):
                    await a.set_light(x, proposal)
                d = await p.redeem(x, PRINCIPAL)
                assert d.decision == "execute", d
                changes = [
                    {"reason": "changed"},
                    {"content_hash": "sha256:bad"},
                    {"params": {"on": False}},
                    {"scheduled_for": NOW},
                ]
                for change in changes:
                    altered = x.model_copy(update=change)
                    if "content_hash" not in change:
                        altered = altered.model_copy(
                            update={"content_hash": action_hash(altered)}
                        )
                    with pytest.raises((PipelineError, ValueError)):
                        await a.set_light(altered, d)
                with pytest.raises(PipelineError):
                    await a.set_light(x, d.model_copy(update={"audit_id": None}))
                with pytest.raises(PipelineError):
                    await a.set_light(
                        x,
                        d.model_copy(
                            update={
                                "explain": d.explain.model_copy(
                                    update={"facts": ("forged",)}
                                )
                            }
                        ),
                    )
                p.clock = lambda: NOW + timedelta(seconds=11)
                with pytest.raises(PipelineError):
                    await a.set_light(x, d)
                assert not any(q.method == "POST" for q in r.calls)
            finally:
                await a.close()

    asyncio.run(run())


def test_pre_dispatch_failures_and_uncertain_dispatch_never_resend(
    scratch_database, tmp_path
):
    async def run():
        async with connect(scratch_database) as c:
            p = await prepare(c)
            x = ha_action()
            d = await p.redeem(x, PRINCIPAL)
            r = Recorded()
            a = adapter(tmp_path, r, pipeline=p)
            await a.start()
            append = p.audit.append
            p.audit.append = AsyncMock(side_effect=RuntimeError("private upstream"))
            try:
                with pytest.raises(PipelineError):
                    await a.set_light(x, d)
                assert not any(q.method == "POST" for q in r.calls)
                p.audit.append = append
                # Failed claim rolls back; a later valid claim may dispatch once.
                import httpx

                r.error = httpx.ReadTimeout("private upstream")
                with pytest.raises(ValueError):
                    await a.set_light(x, d)
                assert len([q for q in r.calls if q.method == "POST"]) == 1
                r.error = None
                with pytest.raises(PipelineError):
                    await a.set_light(x, d)
                assert len([q for q in r.calls if q.method == "POST"]) == 1
                assert list(
                    await c.scalars(
                        sa.select(db.audit_log.c.event_type).order_by(
                            db.audit_log.c.seq
                        )
                    )
                ) == ["EXECUTE", "EXECUTION_ATTEMPTED"]
            finally:
                await a.close()

    asyncio.run(run())


def test_migration_empty_roundtrip(scratch_database):
    async def run():
        async with connect(scratch_database) as c:
            await migrate(c)
            await migrate(c, "downgrade", "0004_observation_domains")
            await migrate(c)

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["commit", "database", "signature"])
def test_claim_failures_do_not_send(scratch_database, tmp_path, failure):
    async def run():
        async with connect(scratch_database) as c:
            p = await prepare(c)
            x = ha_action()
            d = await p.redeem(x, PRINCIPAL)
            r = Recorded()
            a = adapter(tmp_path, r, pipeline=p)
            await a.start()
            if failure == "signature":
                await c.execute(db.audit_log.update().values(signature=b"bad"))
                await c.commit()

            def fail_commit(conn):
                raise RuntimeError("injected commit failure")

            def fail_database(
                conn, cursor, statement, parameters, context, executemany
            ):
                if statement.startswith("INSERT INTO audit_log"):
                    raise RuntimeError("injected audit storage failure")

            target = c.sync_connection
            if failure == "commit":
                sa.event.listen(target, "commit", fail_commit)
            if failure == "database":
                sa.event.listen(target, "before_cursor_execute", fail_database)
            try:
                with pytest.raises(PipelineError):
                    await a.set_light(x, d)
                assert not any(q.method == "POST" for q in r.calls)
            finally:
                if failure == "commit":
                    sa.event.remove(target, "commit", fail_commit)
                if failure == "database":
                    sa.event.remove(target, "before_cursor_execute", fail_database)
                await a.close()
            assert await c.scalar(sa.select(db.actions.c.execution_attempt_seq)) is None

    asyncio.run(run())


def test_household_binding_change_and_scheduled_claim_refused(
    scratch_database, tmp_path
):
    async def run():
        from dataclasses import replace
        from uuid import uuid4

        async with connect(scratch_database) as c:
            p = await prepare(c)
            x = ha_action()
            d = await p.redeem(x, PRINCIPAL)
            r = Recorded()
            foreign = Pipeline(
                c,
                replace(p.bundle, household_id=uuid4()),
                p.boundary,
                p.audit,
                lambda: NOW,
            )
            with pytest.raises(PipelineError):
                await foreign.claim_execution(x, d)
            scheduled = x.model_copy(update={"scheduled_for": NOW})
            scheduled = scheduled.model_copy(
                update={"content_hash": action_hash(scheduled)}
            )
            with pytest.raises(PipelineError):
                await p.claim_execution(scheduled, d)
            a = adapter(tmp_path, r, pipeline=p)
            await a.start()
            try:
                await c.execute(
                    db.asset_bindings.update()
                    .where(db.asset_bindings.c.asset_id == BINDINGS[1].asset_id)
                    .values(attributes={"adapter": "twin", "entity_id": "light.demo"})
                )
                await c.commit()
                with pytest.raises(PipelineError):
                    await a.set_light(x, d)
                assert not any(q.method == "POST" for q in r.calls)
            finally:
                await a.close()

    asyncio.run(run())
