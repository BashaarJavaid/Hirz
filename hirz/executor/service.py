"""One local household sweep; the database owns scheduling and dispatch claims."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import sqlalchemy as sa

from hirz import db
from hirz.adapters.devices.ha import HomeAssistant, fahrenheit
from hirz.adapters.registry import Registry
from hirz.audit import Verification
from hirz.executor import observations, twin
from hirz.executor.contracts import inverse, validate
from hirz.executor.plans import get, hold
from hirz.executor.storage import notice, repeated, row, transition
from hirz.pipeline.audit import PipelineError
from hirz.pipeline.hashing import action_hash, digest
from hirz.pipeline.models import (
    Action,
    Decision,
    EventType,
    ExpectedEffect,
    Inverse,
    Principal,
    Revert,
)
from hirz.pipeline.service import Pipeline, PolicyBundle
from hirz.twin.world import TwinWorld


class Executor:
    def __init__(
        self,
        pipeline: Pipeline,
        registry: Registry,
        *,
        world: TwinWorld | None = None,
        reload_policy: Callable[[], Awaitable[PolicyBundle]] | None = None,
        refresh_polls: bool = False,
    ):
        self.pipeline, self.registry, self.world = pipeline, registry, world
        self.reload_policy = reload_policy
        self.refresh_polls = refresh_polls

    async def read(self, action: Action) -> dict[str, Any]:
        if action.target.adapter == "twin":
            if self.world is None:
                raise ValueError("Twin world is unavailable")
            actual = twin.state(self.world, action)
            if actual.get("available") is False or actual.get("plugged_in") is False:
                raise ValueError("Device unavailable; actual state unknown")
            return actual
        adapter = self.registry.instances[("devices", "ha")]
        assert isinstance(adapter, HomeAssistant)
        data = await adapter.raw_state(action.target.entity)
        if action.action_class == "energy.hvac_adjust":
            return {
                "mode": data["state"],
                "target_f": fahrenheit(
                    data["attributes"]["temperature"], await adapter.temperature_unit()
                ),
            }
        return {"on": data["state"] == "on"}

    async def sweep(self, *, endings_only: bool = False) -> tuple[Decision, ...]:
        p = self.pipeline
        if p.connection.in_transaction():
            raise ValueError("Worker requires an idle database connection")
        key = int.from_bytes(p.household_id.bytes[:8], "big", signed=True)
        async with p.connection.begin():
            locked = await p.connection.scalar(
                sa.text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
            )
        if not locked:
            return ()
        speed = self.world.clock._speed if self.world else None
        try:
            if self.world is not None:
                self.world.clock.set_speed(0)
            async with p.connection.begin():
                rows = (
                    (
                        await p.connection.execute(
                            sa.select(db.actions)
                            .where(
                                p.scope(db.actions),
                                db.actions.c.lifecycle.is_not(None),
                                db.actions.c.execution_status.in_(
                                    ["scheduled", "executing", "dispatched"]
                                ),
                                db.actions.c.due_at <= p.clock(),
                            )
                            .order_by(db.actions.c.due_at, db.actions.c.action_id)
                        )
                    )
                    .mappings()
                    .all()
                )
            ordered = sorted(
                rows, key=lambda r: not bool(r["lifecycle"].get("ending_of"))
            )
            results = []
            for stored in ordered:
                if endings_only and not stored["lifecycle"].get("ending_of"):
                    continue
                if not stored["lifecycle"].get("ending_of"):
                    async with p.connection.begin():
                        endings = (
                            (
                                await p.connection.execute(
                                    sa.select(db.actions)
                                    .where(
                                        p.scope(db.actions),
                                        db.actions.c.lifecycle[
                                            "ending_of"
                                        ].astext.is_not(None),
                                        db.actions.c.execution_status == "scheduled",
                                        db.actions.c.due_at <= p.clock(),
                                    )
                                    .order_by(db.actions.c.due_at)
                                )
                            )
                            .mappings()
                            .all()
                        )
                    for due in endings:
                        results.append(await self.run(dict(due)))
                # A prior failure in this sweep may already have held the plan.
                async with p.connection.begin():
                    current = await row(p, stored["action_id"])
                if current["execution_status"] not in {
                    "scheduled",
                    "executing",
                    "dispatched",
                }:
                    continue
                results.append(await self.run(current))
            if (
                self.world is not None
                and not ordered
                and not endings_only
                and not self.refresh_polls
            ):
                async with p.connection.begin():
                    owner = await p.connection.scalar(
                        sa.select(db.actions.c.principal)
                        .where(p.scope(db.actions), db.actions.c.lifecycle.is_not(None))
                        .order_by(db.actions.c.due_at.desc())
                        .limit(1)
                    )
                    principal = Principal.model_validate(owner) if owner else None
                    linked = await p.requester(principal) if principal else None
                if principal and linked and linked.member_id:
                    await observations.ingest(p, self.registry, principal)
            return tuple(results)
        finally:
            if self.world is not None and speed is not None:
                self.world.clock.set_speed(speed)
            if p.connection.in_transaction():
                await p.connection.rollback()
            # Session locks survive transactions; always release on the same session.
            async with p.connection.begin():
                await p.connection.execute(
                    sa.text("SELECT pg_advisory_unlock(:key)"), {"key": key}
                )

    async def run(self, stored: dict[str, Any]) -> Decision:
        p = self.pipeline
        action = validate(Action.model_validate(stored["proposal"]))
        principal = Principal.model_validate(stored["principal"])
        lifecycle = stored["lifecycle"]
        is_ending = bool(lifecycle.get("ending_of"))
        if stored["execution_attempt_seq"] is not None:
            await self.failure(action, stored, "dispatch_uncertain")
        elif not is_ending and (
            action.expected_effect is None
            or p.clock() >= action.expected_effect.by
            or action.revert
            and action.scheduled_for is not None
            and p.clock()
            >= action.scheduled_for + timedelta(seconds=action.revert.after_s)
        ):
            async with p.repo.write(p.clock):
                await transition(
                    p,
                    action.action_id,
                    "skipped",
                    EventType.EXECUTION_CANCELLED,
                    reason="execution_window_expired",
                )
                if action.plan_id:
                    await hold(
                        p,
                        action,
                        lifecycle["member_id"],
                        "The execution window expired.",
                    )
        else:
            try:
                if is_ending:
                    decision = Decision.model_validate(lifecycle["decision"])
                else:
                    if self.reload_policy:
                        p.bundle = await self.reload_policy()
                    if not self.refresh_polls or not action.plan_id:
                        await observations.ingest(p, self.registry, principal)
                    actual = await self.read(action)
                    if action.plan_id and self.refresh_polls:
                        async with p.connection.begin():
                            snapshot = await p.snapshot(p.clock())
                        data: Any = snapshot.data
                        asset = next(
                            b["asset_id"]
                            for b in data["asset_bindings"]
                            if b["adapter"] == action.target.adapter
                            and b["entity_id"] == action.target.entity
                        )
                        sample: dict[str, Any] = next(
                            (
                                o["state"]
                                for o in data["observations"]
                                if o.get("asset_id") == asset
                            ),
                            {},
                        )
                        controls = (
                            ("target_f", "mode")
                            if action.action_class == "energy.hvac_adjust"
                            else tuple(action.params)
                        )
                        if any(actual.get(k) != sample.get(k) for k in controls):
                            await observations.ingest(p, self.registry, principal)
                        if (
                            action.target.adapter == "ha"
                            and action.action_class == "energy.hvac_adjust"
                            and actual.get("mode") not in {"heat", "cool"}
                        ):
                            raise ValueError(
                                "The observed thermostat mode is unsupported"
                            )
                    previous = inverse(action, actual)
                    async with p.repo.write(p.clock):
                        current = await row(p, action.action_id)
                        captured = (
                            previous.model_dump(mode="json", by_alias=True)
                            if previous
                            else None
                        )
                        seq = await p.audit.append(
                            p.connection,
                            p.household_id,
                            p.clock(),
                            EventType.SCHEDULED,
                            {"action_id": action.action_id, "inverse": captured},
                        )
                        await p.connection.execute(
                            db.actions.update()
                            .where(
                                p.scope(db.actions),
                                db.actions.c.action_id == action.action_id,
                            )
                            .values(
                                lifecycle=current["lifecycle"]
                                | {"inverse": captured, "inverse_seq": seq}
                            )
                        )
                    decision = await p.redeem(
                        action,
                        principal,
                        cost=Decimal(stored["cost"])
                        if stored["cost"] is not None
                        else None,
                        approval_id=lifecycle.get("approval_id"),
                    )
                    if decision.decision != "execute":
                        async with p.repo.write(p.clock):
                            await transition(
                                p,
                                action.action_id,
                                "held",
                                EventType.EXECUTION_HELD,
                                reason=decision.event_type.value,
                                decision_seq=decision.audit_id,
                            )
                            await hold(
                                p,
                                action,
                                lifecycle["member_id"],
                                "Current household rules require a new decision.",
                            )
                        return decision
                if action.target.adapter == "twin":
                    assert self.world is not None
                    async with asyncio.timeout(
                        30 if action.action_class == "energy.ev_charge" else 10
                    ):
                        await twin.execute(p, self.world, action, decision)
                    # A simulated write is a new event instant for versioned observations.
                    self.world.clock.jump(
                        self.world.clock() + timedelta(microseconds=1)
                    )
                else:
                    adapter = self.registry.instances[("devices", "ha")]
                    assert isinstance(adapter, HomeAssistant)
                    await adapter.execute(action, decision)
                if not is_ending and not self.refresh_polls:
                    await observations.ingest(p, self.registry, principal)
            except PipelineError:
                raise
            except Exception:
                if p.connection.in_transaction():
                    await p.connection.rollback()
                async with p.connection.begin():
                    current = await row(p, action.action_id)
                reason = (
                    "dispatch_uncertain"
                    if current["execution_attempt_seq"] is not None
                    and current["execution_status"] != "failed"
                    else "verification_failed"
                )
                if current["execution_status"] == "verified":
                    async with p.repo.write(p.clock):
                        await hold(
                            p,
                            action,
                            lifecycle["member_id"],
                            "The setting was verified, but its household observation could not be updated.",
                        )
                else:
                    await self.failure(action, current, reason)
        async with p.connection.begin():
            current = await row(p, action.action_id)
            answer = await repeated(p, current)
        await self.complete_plan(action)
        return answer

    async def failure(
        self, action: Action, stored: dict[str, Any], reason: str
    ) -> None:
        p = self.pipeline
        lifecycle = stored["lifecycle"]
        async with p.repo.write(p.clock):
            if stored["execution_status"] != "failed":
                await transition(
                    p,
                    action.action_id,
                    "failed",
                    EventType.VERIFY_FAILED,
                    reason=reason,
                    execution_attempt_seq=stored["execution_attempt_seq"],
                )
        # Read actual controls; accepting a command is not verification of its effect.
        try:
            async with asyncio.timeout(10):
                actual = await self.read(action)
            unmet = any(actual.get(k) != v for k, v in action.params.items())
            if action.action_class == "energy.appliance_start":
                unmet = actual.get("on") is not True
        except Exception:
            unmet = None
        if (
            unmet is True
            and lifecycle.get("retry", 0) == 0
            and action.action_class != "energy.appliance_start"
            and not lifecycle.get("ending_of")
            and action.expected_effect
            and p.clock() < action.expected_effect.by
        ):
            from hirz.executor.storage import retry

            result = await retry(p, action)
            if result is not None and result.status == "executing":
                async with p.repo.write(p.clock):
                    await notice(
                        p,
                        lifecycle["member_id"],
                        action.action_id,
                        "The setting could not be verified. One retry is queued.",
                    )
                return
        async with p.repo.write(p.clock):
            await hold(
                p,
                action,
                lifecycle["member_id"],
                "The requested setting could not be verified.",
            )

    async def complete_plan(self, action: Action) -> None:
        if not action.plan_id:
            return
        p = self.pipeline
        async with p.repo.write(p.clock):
            stored = await get(p, action.plan_id)
            if stored["document"]["status"] not in {"approved", "active"}:
                return
            retry = db.actions.alias("successful_retry")
            pending = await p.connection.scalar(
                sa.select(sa.func.count())
                .select_from(db.actions)
                .where(
                    p.scope(db.actions),
                    db.actions.c.proposal["plan_id"].astext == action.plan_id,
                    db.actions.c.execution_status != "verified",
                    ~sa.exists(
                        sa.select(retry.c.action_id).where(
                            retry.c.household_id == db.actions.c.household_id,
                            retry.c.lifecycle["retry_of"].astext
                            == db.actions.c.action_id,
                            retry.c.execution_status == "verified",
                        )
                    ),
                )
            )
            if not pending:
                status = (
                    "completed"
                    if p.clock()
                    >= datetime.fromisoformat(
                        stored["document"]["horizon"]["end"].replace("Z", "+00:00")
                    )
                    else "active"
                )
                if stored["document"]["status"] == status:
                    return
                seq = await p.audit.append(
                    p.connection,
                    p.household_id,
                    p.clock(),
                    EventType.PLAN_REVISED,
                    {"plan_id": action.plan_id, "status": status},
                )
                await p.connection.execute(
                    db.plans.update()
                    .where(p.scope(db.plans), db.plans.c.plan_id == action.plan_id)
                    .values(
                        document=stored["document"] | {"status": status},
                        audit_seq=seq,
                    )
                )

    async def rollback(
        self,
        action_id: str,
        principal: Principal,
        *,
        by: datetime,
        cost: Decimal | None = None,
        revert: Revert | None = None,
    ) -> Decision:
        p = self.pipeline
        async with p.connection.begin():
            original = await row(p, action_id)
            evidence = dict(
                (
                    await p.connection.execute(
                        sa.select(db.audit_log).where(
                            p.scope(db.audit_log),
                            db.audit_log.c.seq == original["lifecycle"]["inverse_seq"],
                        )
                    )
                )
                .mappings()
                .one()
            )
        Verification(p.household_id, p.audit.key.public_key()).feed(evidence)
        if evidence["payload"].get("action_id") != action_id or digest(
            evidence["payload"].get("inverse")
        ) != digest(original["lifecycle"]["inverse"]):
            raise ValueError("Rollback inverse does not match signed evidence")
        saved = Inverse.model_validate(original["lifecycle"]["inverse"])
        action = Action.model_validate(original["proposal"])
        assert action.expected_effect is not None
        fresh = action.model_copy(
            update={
                "action_id": uuid4().hex,
                "plan_id": None,
                "params": saved.params,
                "revert": revert,
                "scheduled_for": p.clock(),
                "expected_effect": ExpectedEffect(
                    entity=saved.target.entity,
                    attr=action.expected_effect.attr,
                    value=saved.params[action.expected_effect.attr],
                    by=by,
                ),
                "reason": "Explicit rollback of " + action_id,
            }
        )
        fresh = fresh.model_copy(update={"content_hash": action_hash(fresh)})
        result = await p.enqueue(fresh, principal, cost=cost)
        if result.status == "executing":
            async with p.repo.write(p.clock):
                await p.audit.append(
                    p.connection,
                    p.household_id,
                    p.clock(),
                    EventType.ROLLED_BACK,
                    {
                        "original": action_id,
                        "inverse_action": fresh.action_id,
                        "status": "queued",
                    },
                )
        return result
