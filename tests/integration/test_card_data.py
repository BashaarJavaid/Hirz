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


@pytest.mark.parametrize("approved", [True, False])
def test_plan_read_presents_exact_pending_action_consent(
    scratch_database, approved, monkeypatch
):
    from mcp import types
    from test_executor_database import environment, proposal, runtime_for

    from hirz.executor.plans import PlanService
    from hirz.mcp.contracts import GetHouseholdPlanResult
    from hirz.mcp.runtime import register
    from hirz.mcp.server import create_server
    from hirz.mcp.transport import local_security
    from hirz.pipeline.service import PolicyBundle

    async def run():
        async with connect(scratch_database) as connection:
            p, world, registry, executor = await environment(connection)
            try:
                raw = p.bundle.policy().model_dump()
                raw["per_role"]["owner"] = {"environment.lights": {"mode": "ask"}}
                p.bundle = await PolicyBundle.validate(
                    p.household_id,
                    type(p.bundle.policy()).model_validate(raw),
                    p.boundary,
                )
                service = PlanService(p)
                plan, actions = proposal(world)
                await service.record(
                    plan, actions, PRINCIPAL, runtime=runtime_for(plan)
                )
                await service.approve(plan.plan_id, PRINCIPAL)
                pending = (await executor.sweep())[0]
                assert pending.decision == "ask" and pending.approval
                tools = HouseholdTools(p, PRINCIPAL)

                async def invoke(server, runtime, name, arguments):
                    return await runtime.call(name, arguments)

                # Exercise the actual registered MCP output boundary as well as
                # Pipeline-created consent; transport authentication has its own gate.
                monkeypatch.setattr("hirz.mcp.elicitation.call", invoke)
                server = create_server(local_security(8000), authentication=True)
                register(server, tools)
                handler = server._mcp_server.request_handlers[types.CallToolRequest]
                returned = await handler(
                    types.CallToolRequest(
                        method="tools/call",
                        params=types.CallToolRequestParams(
                            name="get_household_plan", arguments={}
                        ),
                    )
                )
                assert not returned.root.isError
                answer = GetHouseholdPlanResult.model_validate(
                    returned.root.structuredContent
                )
                data, card = answer.data, answer.data.presentation
                assert data.plan.status == "awaiting_approval"
                assert card.kind == "approval" and card.can_respond
                assert card.label == answer.speakable.details[0]
                assert not card.phone_required
                assert (card.plan_id, card.version) == (plan.plan_id, plan.version)
                assert data.decision == data.decisions[0]
                assert data.decision.action_id == actions[0].action_id
                assert (
                    data.decision.approval.approval_id == pending.approval.approval_id
                )
                consent = dict(
                    plan_id=card.plan_id,
                    version=card.version,
                    action_id=data.decision.action_id,
                    approval_id=data.decision.approval.approval_id,
                    approved=approved,
                )
                stale = await tools.call(
                    "approve_action",
                    consent | {"version": card.version + 1, "request_id": "stale-card"},
                )
                assert stale.data.code == "PLAN_CHANGED"
                voted = await tools.call(
                    "approve_action", consent | {"request_id": "pending-card"}
                )
                assert voted.data.decision.event_type.value == (
                    "APPROVED" if approved else "REJECTED"
                )
                executions = await executor.sweep()
                assert bool(executions) == approved
                if approved:
                    assert executions[0].status == "verified"
                evidence, _ = await verify_database(
                    connection, p.household_id, p.audit.key.public_key()
                )
                assert evidence["status"] == "valid"
            finally:
                await registry.close()

    asyncio.run(run())


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
                consent = dict(
                    plan_id=result.plan.plan_id,
                    version=result.plan.version,
                    approved=True,
                    request_id="card-plan",
                )
                approved = await tools.call("approve_action", consent)
                assert approved.data.status == "queued"
                assert approved.data.presentation is None
                assert approved.data.actions == ()
                assert await tools.call("approve_action", consent) == approved
                reread = await tools.call("get_household_plan", {})
                assert reread.data.presentation.kind == "plan"
                assert len(reread.data.actions) == len(result.plan.actions)
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
