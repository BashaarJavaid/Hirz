"""Narration publication, restart reuse and races on the real local backend."""

import asyncio
from unittest.mock import Mock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from test_database import connect, migrate
from test_database import scratch_database as scratch_database
from test_refresh_database import prepared as setup

from hirz import db
from hirz.audit import verify_database
from hirz.executor.plans import PlanService, get
from hirz.executor.refresh import job
from hirz.executor.refresh_worker import RefreshWorker
from hirz.explainer.bedrock import BedrockExplainer
from hirz.explainer.core import TemplateExplainer, context, enriched, prepared
from hirz.explainer.models import Details
from hirz.pipeline.models import Plan
from hirz.pipeline.service import Pipeline
from hirz.planner.coordinator import Coordinator
from scripts.smoke_executor import PRINCIPAL, action

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("outcome", ["success", "outage", "changed", "cancelled"])
def test_first_plan_narration_preserves_publication_boundaries(
    scratch_database, monkeypatch, outcome
):
    from hirz.aws.fixture import load
    from hirz.executor.local import compose
    from hirz.executor.observations import ingest
    from hirz.mcp.household import HouseholdTools
    from hirz.mcp.worker import prepare_plans
    from hirz.twin.execution import bootstrap

    monkeypatch.setenv("HIRZ_FIXTURE_START", "2026-10-13T22:30:00+00:00")

    async def run():
        loaded = load()
        async with connect(scratch_database) as c:
            await migrate(c)
            p = await bootstrap(loaded, c)
            registry = await compose(
                p, world=loaded.world, config="presence:twin,energy:twin"
            )
            await registry.start()
            try:
                await ingest(p, registry, PRINCIPAL)
                tools = HouseholdTools(p, PRINCIPAL)
                queued = await tools.call("get_household_plan", {"request_id": "first"})
                assert queued.data.status == "preparing", queued
                calls = []
                changes = []

                class Provider(BedrockExplainer):
                    async def narrate(self, obj, ctx):
                        assert not c.in_transaction()
                        calls.append(obj)
                        if outcome == "cancelled":
                            raise asyncio.CancelledError
                        if outcome == "changed":
                            changed = await tools.call(
                                "revise_household_plan",
                                {
                                    "text": "The car stops at fifty",
                                    "applies_to": "car",
                                    "kind": "one_time",
                                    "operation": "add",
                                    "change": "car_limit",
                                    "percent": 50,
                                    "request_id": "changed-during-narration",
                                },
                            )
                            changes.append(changed)
                        return await super().narrate(obj, ctx)

                provider = Provider()
                provider.converse = Mock(
                    side_effect=RuntimeError("synthetic outage")
                    if outcome == "outage"
                    else None,
                    return_value={
                        "stopReason": "end_turn",
                        "output": {
                            "message": {
                                "role": "assistant",
                                "content": [
                                    {
                                        "text": '{"details":[],"screen_summary":"Energy timing follows household requirements."}'
                                    }
                                ],
                            }
                        },
                    },
                )
                if outcome == "cancelled":
                    with pytest.raises(asyncio.CancelledError):
                        await prepare_plans(p, loaded, explainer=provider)
                else:
                    await prepare_plans(p, loaded, explainer=provider)
                assert len(calls) == 1
                if outcome == "changed":
                    assert len(changes) == 1 and changes[0].data.status == "recorded", (
                        changes
                    )
                async with c.begin():
                    request = (
                        (await c.execute(sa.select(db.plan_requests))).mappings().one()
                    )
                    documents = (
                        (await c.execute(sa.select(db.plans.c.document)))
                        .scalars()
                        .all()
                    )
                if outcome in {"changed", "cancelled"}:
                    assert request["status"] == "pending" and not documents
                else:
                    assert request["status"] == "ready" and len(documents) == 1
                    stored = Plan.model_validate(documents[0])
                    assert stored.narration.provider == (
                        "template" if outcome == "outage" else "bedrock"
                    )
                    assert stored.narration.fallback_reason == (
                        "provider_error" if outcome == "outage" else None
                    )
                    assert stored.model_dump(
                        exclude={"speakable", "narration"}
                    ) == calls[0].model_dump(exclude={"speakable", "narration"})
                    await tools.call("get_household_plan", {})
                    await tools.call("explain_plan", {})
                    assert provider.converse.call_count == 1
                summary, _ = await verify_database(
                    c, p.household_id, p.audit.key.public_key()
                )
                assert summary["status"] == "valid"
            finally:
                await registry.close()

    asyncio.run(run())


def test_audited_publication_restart_reuse_status_and_scope(scratch_database):
    async def run():
        async with connect(scratch_database) as c:
            p, w, registry, executor, service, result, runtime = await setup(c)
            try:
                async with c.begin():
                    ctx = context(await p.snapshot(p.clock()))
                    stored = await get(p, result.plan.plan_id)
                first = Plan.model_validate(stored["document"])
                assert first.narration
                restart = Pipeline(c, p.bundle, p.boundary, p.audit, p.clock)
                async with c.begin():
                    reloaded = Plan.model_validate(
                        (await get(restart, first.plan_id))["document"]
                    )
                assert prepared(reloaded, ctx) == first
                forged = first.model_copy(update={"household_id": uuid4()})
                with pytest.raises(ValueError):
                    prepared(forged, ctx)
                # Configured model failure is cached through an audited refresh and a restart.
                provider = BedrockExplainer()
                provider.converse = Mock(side_effect=RuntimeError("offline"))
                await service.request_refresh(first.plan_id, PRINCIPAL)
                await RefreshWorker(p, registry, world=w, explainer=provider).batch()
                async with c.begin():
                    current = await job(p, stored)
                    replacement = Plan.model_validate(
                        (await get(p, current["plan_id"]))["document"]
                    )
                    ctx = context(await p.snapshot(p.clock()))
                assert replacement.narration.fallback_reason == "provider_error"
                provider.converse.assert_called_once()
                reloaded = Plan.model_validate_json(replacement.model_dump_json())
                fresh_provider = BedrockExplainer()
                fresh_provider.converse = Mock(
                    side_effect=AssertionError("must not call")
                )
                assert await fresh_provider.narrate(
                    reloaded, ctx
                ) == await provider.narrate(reloaded, ctx)
                read = await PlanService(restart).read_current(
                    reloaded.plan_id, PRINCIPAL
                )
                assert read.narration == reloaded.narration
                # Immediate pipeline templates distinguish permission, queue and verified outcome.
                a = action(w)
                preview = await p.evaluate(a, PRINCIPAL)
                queued = await p.enqueue(a, PRINCIPAL)
                assert preview.narration and queued.narration
                assert preview.speakable != queued.speakable
                await executor.sweep()
                verified = await p.enqueue(a, PRINCIPAL)
                assert verified.status == "verified"
                assert "simulated" in verified.speakable["headline"]
                assert verified.narration.input_hash != queued.narration.input_hash
                await service.request_refresh(
                    reloaded.plan_id, PRINCIPAL, reason="Changed requirement"
                )
                held = await service.read_current(reloaded.plan_id, PRINCIPAL)
                assert held.narration.provider == "template"
                assert "Historical" in str(held.speakable)
                assert "$" not in str(held.speakable)
                summary, rows = await verify_database(
                    c, p.household_id, p.audit.key.public_key(), collect=True
                )
                assert summary["status"] == "valid"
                publications = [
                    r
                    for r in rows
                    if r.event_type in {"PLAN_CREATED", "PLAN_REVISED"}
                    and "mutation" in r.payload
                ]
                assert publications and all(
                    r.payload["mutation"]["plan"]["narration"] for r in publications
                )
            finally:
                await registry.close()

    asyncio.run(run())


def test_enrichment_outside_transactions_obsolete_result_discarded(scratch_database):
    async def run():
        async with connect(scratch_database) as c:
            p, w, registry, executor, service, result, runtime = await setup(c)
            try:

                class Delayed:
                    def __init__(self):
                        self.calls = 0

                    async def narrate(self, obj, ctx):
                        assert not c.in_transaction()
                        self.calls += 1
                        await service.request_refresh(
                            result.plan.plan_id,
                            PRINCIPAL,
                            reason="new facts during narration",
                        )
                        return enriched(
                            obj,
                            ctx,
                            Details(
                                details=(),
                                screen_summary="Energy timing follows household requirements.",
                            ),
                        )

                await service.request_refresh(result.plan.plan_id, PRINCIPAL)
                delayed = Delayed()
                await RefreshWorker(p, registry, world=w, explainer=delayed).batch()
                assert delayed.calls == 1
                async with c.begin():
                    current = await job(p, await get(p, result.plan.plan_id))
                    assert current["state"] == "queued"
                    assert current["plan_id"] == result.plan.plan_id
                    assert (
                        await c.scalar(sa.select(sa.func.count()).select_from(db.plans))
                        == 1
                    )

                # Coordinator also finishes its snapshot transaction before enrichment.
                class Check(TemplateExplainer):
                    async def narrate(self, obj, ctx):
                        assert not c.in_transaction()
                        return await super().narrate(obj, ctx)

                coordinated = await Coordinator(p, Check()).plan(
                    PRINCIPAL, runtime.workload
                )
                assert coordinated.result.plan and coordinated.result.plan.narration
                await RefreshWorker(p, registry, world=w).batch()
                async with c.begin():
                    current = await job(p, await get(p, result.plan.plan_id))
                    assert current["state"] == "idle"
                    assert current["plan_id"] != result.plan.plan_id
            finally:
                await registry.close()

    asyncio.run(run())
