"""New card reads over real Pipeline-created records in disposable databases."""

import asyncio

import pytest
from test_database import connect
from test_database import scratch_database as scratch_database
from test_refresh_database import prepared

from hirz.audit import verify_database
from hirz.mcp.household import HouseholdTools
from scripts.smoke_executor import PRINCIPAL

pytestmark = pytest.mark.integration


def test_plan_details_scorecard_pagination_and_foreign_action(scratch_database):
    async def run():
        async with connect(scratch_database) as connection:
            p, world, registry, executor, service, result, runtime = await prepared(
                connection
            )
            try:
                tools = HouseholdTools(p, PRINCIPAL)
                plan = await tools.call("get_household_plan", {})
                assert plan.data.plan.plan_id == result.plan.plan_id
                assert len(plan.data.actions) == len(result.plan.actions)
                assert len(plan.data.presentation.rows) <= 3
                assert plan.data.presentation.can_approve
                await tools.call(
                    "approve_action",
                    dict(
                        plan_id=result.plan.plan_id,
                        version=result.plan.version,
                        approved=True,
                        request_id="card-plan",
                    ),
                )
                await executor.sweep()
                score = await tools.call("get_action_audit", {"limit": 1})
                assert score.data.presentation.kind == "scorecard"
                assert score.data.plan.plan_id == result.plan.plan_id
                assert score.data.presentation.counts.verified > 0
                assert score.data.presentation.counts.autonomous > 0
                assert score.data.cursor
                following = await tools.call(
                    "get_action_audit", {"limit": 1, "cursor": score.data.cursor}
                )
                assert (
                    score.data.presentation.counts == following.data.presentation.counts
                )
                foreign = await tools.call(
                    "get_action_audit", {"action_id": "foreign-action"}
                )
                assert foreign.data.plan is None
                assert not any(foreign.data.presentation.counts.model_dump().values())
                evidence, _ = await verify_database(
                    connection, p.household_id, p.audit.key.public_key()
                )
                assert evidence["status"] == "valid"
            finally:
                await registry.close()

    asyncio.run(run())


def test_newest_estimate_action_specific_and_cancelled_exclusion(scratch_database):
    from datetime import timedelta

    from test_executor_database import changed

    async def run():
        async with connect(scratch_database) as connection:
            p, world, registry, _, service, result, _ = await prepared(connection)
            try:
                tools = HouseholdTools(p, PRINCIPAL)
                world.clock.jump(world.clock() + timedelta(seconds=1))
                newer_id = result.plan.plan_id + "_newer"
                actions = tuple(
                    changed(a, action_id=a.action_id + "_newer", plan_id=newer_id)
                    for a in result.actions
                )
                newer = result.plan.model_copy(
                    update={
                        "plan_id": newer_id,
                        "actions": tuple(a.action_id for a in actions),
                    }
                )
                assert (
                    await service.record(newer, actions, PRINCIPAL)
                ).decision == "execute"
                score = await tools.call("get_action_audit", {})
                assert score.data.plan.plan_id == newer_id
                original = await tools.call(
                    "get_action_audit", {"action_id": result.actions[0].action_id}
                )
                assert original.data.plan.plan_id == result.plan.plan_id
                assert not any(score.data.presentation.counts.model_dump().values())
                assert (await service.cancel(newer_id, PRINCIPAL)).decision == "execute"
                score = await tools.call("get_action_audit", {})
                assert score.data.plan.plan_id == result.plan.plan_id
                cancelled = await tools.call(
                    "get_action_audit", {"action_id": actions[0].action_id}
                )
                assert cancelled.data.plan is None
                evidence, _ = await verify_database(
                    connection, p.household_id, p.audit.key.public_key()
                )
                assert evidence["status"] == "valid"
            finally:
                await registry.close()

    asyncio.run(run())
