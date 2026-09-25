"""First-plan requests run in the worker, never in a tool call."""

import asyncio
from typing import Any

import sqlalchemy as sa

from hirz import db
from hirz.executor.plans import governance
from hirz.executor.runtime import RuntimeInputs
from hirz.mcp.persistence import command
from hirz.pipeline.hashing import digest
from hirz.pipeline.models import Principal
from hirz.pipeline.service import Pipeline
from hirz.planner.coordinator import coordinate
from hirz.planner.scenario import workload_input
from hirz.twin.scenario import LoadedScenario, PlanningSnapshot


async def prepare_plans(p: Pipeline, loaded: LoadedScenario | None) -> None:
    async with p.connection.begin():
        pending = (
            (
                await p.connection.execute(
                    sa.select(db.plan_requests)
                    .where(
                        p.scope(db.plan_requests),
                        db.plan_requests.c.status == "pending",
                    )
                    .order_by(db.plan_requests.c.created_at)
                )
            )
            .mappings()
            .all()
        )
    for row in pending:
        principal = Principal.model_validate(row["principal"])
        scheduler = principal.model_copy(update={"surface": "scheduler"})
        result = None
        fingerprint = None
        try:
            if (
                loaded is None
                or loaded.world.household.id != p.household_id
                or loaded.spec.execution is None
            ):
                raise ValueError("Explicit twin planning inputs are unavailable")
            if row["horizon_end"] > loaded.world.config.end:
                raise ValueError(
                    "Configured scenario inputs do not cover the requested horizon"
                )
            spec = loaded.spec.execution
            if p.clock() >= row["horizon_end"]:
                raise ValueError("Planning horizon expired")
            inputs = workload_input(
                loaded,
                PlanningSnapshot(
                    at=spec.plan_at or "00:00",
                    member=spec.member,
                    ev_target=spec.ev_target,
                ),
                end=row["horizon_end"],
            )
            async with p.repo.write(p.clock):
                snapshot = await p.snapshot(p.clock())
                requester = await p.requester(principal)
                fingerprint = digest(snapshot.data)
            inputs = inputs.model_copy(
                update={
                    "requester": requester,
                    "actuator_precision": True,
                    "objective": row["objective"],
                }
            )
            result = await asyncio.to_thread(
                coordinate, inputs, snapshot, p.bundle.policy()
            )
            if (
                result.result.plan is None
                or result.result.schedule is None
                or result.inputs is None
            ):
                raise ValueError("No feasible plan")
            runtime = RuntimeInputs.from_schedule(result.inputs, result.result.schedule)
        except Exception:
            # Failed preparation records no Plan; cancellation still propagates.
            result = None
        async with p.repo.write(p.clock):
            current = (
                (
                    await p.connection.execute(
                        sa.select(db.plan_requests).where(
                            p.scope(db.plan_requests),
                            db.plan_requests.c.id == row["id"],
                        )
                    )
                )
                .mappings()
                .one()
            )
            if (
                current["status"] != "pending"
                or current["objective"] != row["objective"]
            ):
                continue
            values: dict[str, Any] = dict(
                operation="finish", id=row["id"], status="failed", plan_id=None
            )
            if result and result.result.plan and result.inputs:
                if fingerprint != digest((await p.snapshot(p.clock())).data):
                    continue  # A concurrent constraint or observation needs a fresh solve.
                plan = result.result.plan
                decision = await p.mutate_locked(
                    governance(
                        p,
                        "record_plan",
                        {
                            "plan": plan.model_dump(mode="json"),
                            "actions": [
                                a.model_dump(mode="json", by_alias=True)
                                for a in result.result.actions
                            ],
                            "runtime": runtime.model_dump(mode="json"),
                        },
                        principal,
                    ),
                    principal,
                )
                if decision.decision == "execute":
                    values.update(status="ready", plan_id=plan.plan_id)
            await command(p, "request_plan", values, scheduler)
