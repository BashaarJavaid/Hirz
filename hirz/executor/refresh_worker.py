"""One durable refresh batch per household, with computation outside transactions."""

import asyncio
from datetime import timedelta
from typing import Any

import sqlalchemy as sa

from hirz import db
from hirz.adapters.devices.ha import HomeAssistant, fahrenheit
from hirz.adapters.registry import Registry
from hirz.executor import observations
from hirz.executor.contracts import expired
from hirz.executor.plans import PlanService, get, governance
from hirz.executor.refresh import RefreshService, fingerprint, job
from hirz.executor.replanning import bind_result, outstanding
from hirz.executor.runtime import RuntimeInputs
from hirz.executor.storage import notice
from hirz.explainer.core import Explainer, TemplateExplainer, attach, context
from hirz.pipeline.models import Plan, Principal
from hirz.pipeline.service import Pipeline
from hirz.planner.coordinator import coordinate
from hirz.twin.world import TwinWorld


class RefreshWorker:
    def __init__(
        self,
        pipeline: Pipeline,
        registry: Registry,
        *,
        world: TwinWorld | None = None,
        explainer: Explainer | None = None,
    ):
        self.pipeline, self.registry, self.world = pipeline, registry, world
        self.service = RefreshService(pipeline)
        self.explainer = explainer or TemplateExplainer()

    async def transition(
        self,
        stored: dict[str, Any],
        generation: int,
        principal: Principal,
        **values: Any,
    ) -> None:
        result = await self.service.command(
            principal,
            dict(
                plan_id=stored["plan_id"],
                operation="transition",
                generation=generation,
                values=values,
            ),
            locked=True,
        )
        if result.decision != "execute":
            raise ValueError("Refresh transition lacks current authority")

    async def poll(self) -> None:
        p = self.pipeline
        async with p.connection.begin():
            rows = (
                (
                    await p.connection.execute(
                        sa.select(db.plans).where(
                            p.scope(db.plans),
                            db.plans.c.document["status"].astext.notin_(
                                ["superseded", "abandoned", "completed"]
                            ),
                        )
                    )
                )
                .mappings()
                .all()
            )
        for row in rows:
            principal = (
                Principal.model_validate(row["approver"] or row["requester"])
                if row["approver"] or row["requester"]
                else None
            )
            if principal is None:
                continue
            async with p.connection.begin():
                linked = await p.requester(principal)
            if linked.member_id is None:
                # A revoked account cannot grant a job transition or device action.
                continue
            try:
                async with asyncio.timeout(10):
                    await observations.ingest(p, self.registry, principal)
                await self.poll_inputs(dict(row), principal)
            except Exception as exc:
                await self.poll_failure(
                    dict(row), principal, transient=not isinstance(exc, ValueError)
                )
                continue
            async with p.connection.begin():
                current = await job(p, dict(row))
            if (
                current
                and current["blocking_reason"]
                == "Configured inputs could not be read; the plan remains held."
            ):
                await self.service.request(
                    row["plan_id"],
                    principal,
                    reason="Configured reads recovered",
                    explicit=False,
                )
            await self.service.command(
                principal, dict(plan_id=row["plan_id"], operation="detect")
            )

    async def poll_failure(
        self, stored: dict[str, Any], principal: Principal, *, transient: bool
    ) -> None:
        p = self.pipeline
        reason = "Configured inputs could not be read; the plan remains held."
        if p.connection.in_transaction():
            await p.connection.rollback()
        async with p.connection.begin():
            current = await job(p, stored)
        if current and current["blocking_reason"] == reason:
            if current["state"] == "blocked" or (
                current["next_retry"] and current["next_retry"] > p.clock()
            ):
                return
        await self.service.request(
            stored["plan_id"], principal, reason=reason, explicit=False
        )
        async with p.repo.write(p.clock):
            current = await job(p, stored)
            assert current is not None
            await self.transition(
                stored,
                current["requested_generation"],
                principal,
                attempts=current["attempts"] + 1,
            )
        await self.block(
            stored,
            current["requested_generation"],
            principal,
            reason,
            transient=transient,
        )

    async def poll_inputs(self, stored: dict[str, Any], principal: Principal) -> None:
        if not stored["runtime"] or self.world is None:
            return
        from hirz.pipeline.hashing import digest
        from hirz.twin.physics import changed

        runtime = RuntimeInputs.model_validate(stored["runtime"])
        workload = runtime.workload
        origin, end = (
            runtime.feed_origin or workload.slots[0].start,
            workload.slots[-1].end,
        )
        if self.pipeline.clock() >= end:
            return
        energy: Any = self.registry.instances.get(
            ("energy", self.registry.defaults.get("energy", "twin"))
        )
        calendar: Any = self.registry.instances.get(("calendar", "twin"))
        prices = weather = events = None
        async with asyncio.timeout(10):
            if energy is not None:
                prices = await energy.get_prices(origin, end, "day_ahead")
                weather = await energy.get_weather(origin, end)
                if not prices.complete or not weather.complete:
                    raise ValueError(
                        "Supplied forecasts do not cover the approved horizon."
                    )
            if calendar is not None:
                events = await calendar.list_events(origin, end)
        content = dict(
            prices=[s.model_dump(mode="json") for s in prices.slots]
            if prices
            else None,
            weather=[s.model_dump(mode="json") for s in weather.samples]
            if weather
            else None,
            calendar=[e.model_dump(mode="json") for e in events]
            if events is not None
            else None,
        )
        fingerprint = digest(content)
        if fingerprint == runtime.feed_hash:
            return
        baseline = runtime.feed_hash is None
        updates: dict[str, Any] = dict(feed_hash=fingerprint, feed_origin=origin)
        if not baseline:
            from hirz.planner.models import split_at

            workload = split_at(
                workload, tuple(s.end for s in prices.slots) if prices else ()
            )
            slots = []
            for slot in workload.slots:
                values: dict[str, Any] = {}
                if prices:
                    price = next(
                        (
                            s
                            for s in prices.slots
                            if s.start <= slot.start and s.end >= slot.end
                        ),
                        None,
                    )
                    if price is None:
                        raise ValueError(
                            "A price interval does not cover the supplied workload."
                        )
                    values["price"] = float(price.import_cents_per_kwh) / 100
                if weather:
                    sample = next(
                        (s for s in reversed(weather.samples) if s.at <= slot.start),
                        None,
                    )
                    if sample is None:
                        raise ValueError(
                            "A weather interval does not cover the supplied workload."
                        )
                    values["outdoor_f"] = sample.temp_f
                    if any(z.physical.solar_gain_area_m2 for z in workload.zones):
                        from hirz.twin.environment import Solar

                        location = self.world.household.location
                        if location is None:
                            raise ValueError(
                                "Solar heat gain requires an explicit location."
                            )
                        values["irradiance"] = Solar(
                            tilt_degrees=0, orientation_degrees=0
                        ).irradiance(
                            slot.start,
                            location.latitude,
                            location.longitude,
                            float(sample.cloud_cover_percent),
                        )
                    if any(s.solar_kw for s in workload.slots):
                        values["solar_kw"] = sum(
                            self.world.solar_power(ident, slot.start)
                            for ident in self.world.solar
                        )
                slots.append(changed(slot, **values))
            updates["workload"] = changed(workload, slots=tuple(slots))
            updates["prediction_workload"] = (
                runtime.prediction_workload or runtime.workload
            )
            updates["calendar"] = events
        candidate = runtime.model_copy(update=updates)
        await self.service.command(
            principal,
            dict(
                plan_id=stored["plan_id"],
                operation="feeds",
                runtime=candidate.model_dump(mode="json"),
                baseline=baseline,
            ),
        )

    async def batch(self) -> None:
        p = self.pipeline
        key = ~int.from_bytes(p.household_id.bytes[:8], "big", signed=True)
        async with p.connection.begin():
            locked = await p.connection.scalar(
                sa.text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
            )
        if not locked:
            return
        try:
            await self.poll()
            # A restart reclaims running generations only after obtaining the session lock.
            async with p.connection.begin():
                ready = (
                    (
                        await p.connection.execute(
                            sa.select(db.plan_refresh_jobs).where(
                                p.scope(db.plan_refresh_jobs),
                                db.plan_refresh_jobs.c.state.in_(["queued", "running"]),
                                sa.or_(
                                    db.plan_refresh_jobs.c.next_retry.is_(None),
                                    db.plan_refresh_jobs.c.next_retry <= p.clock(),
                                ),
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
            for row in ready:
                await self.run(dict(row))
        finally:
            if p.connection.in_transaction():
                await p.connection.rollback()
            async with p.connection.begin():
                await p.connection.execute(
                    sa.text("SELECT pg_advisory_unlock(:key)"), {"key": key}
                )

    async def ha_facts(
        self, entities: set[str] | None = None
    ) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        adapter = self.registry.instances.get(("devices", "ha"))
        if not isinstance(adapter, HomeAssistant):
            return result
        async with asyncio.timeout(10):
            unit = await adapter.temperature_unit()
            for binding in self.registry.bindings.values():
                if entities is not None and binding.entity_id not in entities:
                    continue
                if binding.adapter != "ha" or not binding.entity_id.startswith(
                    "climate."
                ):
                    continue
                raw = await adapter.raw_state(binding.entity_id)
                attrs = raw["attributes"]
                if (
                    raw["state"] not in {"heat", "cool"}
                    or not int(attrs["supported_features"]) & 1
                ):
                    raise ValueError(
                        "HA thermostat mode or setpoint control is unsupported."
                    )
                step = attrs.get("target_temp_step")
                # HA documents target_temperature_step as optional (default None).
                # Apply advertised increments; the adapter still verifies the actual setpoint.
                # https://developers.home-assistant.io/docs/core/entity/climate/
                if step is not None and float(step) <= 0:
                    raise ValueError("HA thermostat setpoint increment is invalid.")
                result[binding.entity_id] = dict(
                    mode=raw["state"],
                    low=fahrenheit(attrs["min_temp"], unit),
                    high=fahrenheit(attrs["max_temp"], unit),
                    step=float(step) * (1.8 if unit == "°C" else 1)
                    if step is not None
                    else None,
                    origin=32 if unit == "°C" else 0,
                )
        return result

    async def run(self, queued: dict[str, Any]) -> None:
        p = self.pipeline
        async with p.connection.begin():
            stored = await get(p, queued["plan_id"])
        principal = Principal.model_validate(stored["approver"] or stored["requester"])
        generation = queued["requested_generation"]
        try:
            async with p.repo.write(p.clock):
                current = await job(p, stored)
                if (
                    current is None
                    or current["state"] not in {"queued", "running"}
                    or current["requested_generation"] != generation
                ):
                    return
                await self.transition(
                    stored,
                    generation,
                    principal,
                    state="running",
                    running_generation=generation,
                    attempts=current["attempts"] + 1,
                )
                if not stored["runtime"]:
                    raise ValueError(
                        "Complete runtime inputs are required from an eligible member."
                    )
                runtime = RuntimeInputs.model_validate(stored["runtime"])
                snapshot = await p.snapshot(p.clock())
                if runtime.calendar is not None:
                    snapshot = snapshot.model_copy(
                        update={
                            "data": snapshot.data
                            | {
                                "schedule_events": [
                                    e.model_dump(mode="json") for e in runtime.calendar
                                ]
                            }
                        }
                    )
                snapshot = snapshot.model_copy(
                    update={
                        "data": snapshot.data
                        | {
                            "asset_bindings": [
                                b
                                for b in snapshot.data["asset_bindings"]
                                if str(b["asset_id"])
                                in {str(i) for i in self.registry.bindings}
                            ]
                        }
                    }
                )
                requester = await p.requester(principal)
                before = await fingerprint(p, stored)
                actions = tuple(
                    dict(r)
                    for r in (
                        await p.connection.execute(
                            sa.select(db.actions).where(
                                p.scope(db.actions), db.actions.c.lifecycle.is_not(None)
                            )
                        )
                    ).mappings()
                )
                previous = Plan.model_validate(stored["document"])
                policy = p.bundle.policy()
            ha = await self.ha_facts({z.entity for z in runtime.workload.zones})
            state = self.world.read()[1] if self.world else None
            inputs, bindings, exhausted = outstanding(
                runtime, snapshot, requester, actions, state, ha
            )
            computation = asyncio.create_task(
                asyncio.to_thread(
                    coordinate, inputs, snapshot, policy, previous=previous
                )
            )
            try:
                coordinated = await asyncio.shield(computation)
            except asyncio.CancelledError:
                # Keep the session lock until the native solver thread actually exits.
                await computation
                raise
            if coordinated.inputs is None:
                raise ValueError(
                    "; ".join(c.reason for c in coordinated.conflicts)
                    or "; ".join(
                        coordinated.result.replay.reasons
                        if coordinated.result.replay
                        else ()
                    )
                    or "The coordinated workload is unavailable."
                )
            result = bind_result(
                coordinated.result, coordinated.inputs, previous, bindings, exhausted
            )
            if result.plan is None or result.schedule is None:
                raise ValueError(
                    "; ".join(c.reason for c in coordinated.conflicts)
                    or "The remaining workload is infeasible."
                )
            if not result.plan.comparison_validity.valid:
                raise ValueError(
                    "Valid comparisons could not be established for every approved requirement."
                    + " "
                    + "; ".join(result.plan.comparison_validity.reasons)
                )
            replacement = (
                await asyncio.to_thread(
                    RuntimeInputs.from_schedule,
                    coordinated.inputs,
                    result.schedule,
                    prior=runtime,
                )
            ).model_copy(
                update={
                    "exhausted": exhausted,
                    # A replaced delivery target remains the accepted obligation
                    # after its deadline; expiry cannot resurrect an older goal.
                    "workload": inputs.model_copy(
                        update={
                            "ev_target": coordinated.inputs.ev_target,
                            "ev_deadline": coordinated.inputs.ev_deadline,
                        }
                    ),
                    "prediction_workload": coordinated.inputs,
                }
            )
            narration = await self.explainer.narrate(result.plan, context(snapshot))
            result = result.model_copy(update={"plan": attach(result.plan, narration)})
            assert result.plan is not None
            # Network reads may finish after new inputs arrive; publication compares the generation again.
            await self.poll()
            async with p.repo.write(p.clock):
                current = await job(p, stored)
                latest = await get(p, stored["plan_id"])
                if (
                    current is None
                    or current["state"] != "running"
                    or current["requested_generation"] != generation
                    or current["plan_id"] != previous.plan_id
                    or latest["document"]["status"] != "refreshing"
                    or before != await fingerprint(p, latest)
                ):
                    return
                if p.clock() >= previous.horizon.end:
                    raise ValueError("The approved horizon has ended.")
                if any(expired(a, p.clock()) for a in result.actions):
                    reason = "Replacement opening expired before publication; recomputing from current inputs."
                    await self.transition(
                        stored,
                        generation,
                        principal,
                        state="queued",
                        running_generation=None,
                        requested_generation=generation + 1,
                        reasons=list(dict.fromkeys([*current["reasons"], reason])),
                        next_retry=None,
                        blocking_reason=None,
                    )
                    return
                from hirz.executor.budget import transfer

                reservation = await transfer(p, latest, replacement, actions)
                decision = await p.mutate_locked(
                    governance(
                        p,
                        "revise_plan",
                        dict(
                            plan=result.plan.model_dump(mode="json"),
                            actions=[
                                a.model_dump(mode="json", by_alias=True)
                                for a in result.actions
                            ],
                            runtime=replacement.model_dump(mode="json"),
                            autonomous=True,
                        ),
                        principal,
                    ),
                    principal,
                )
                if decision.decision != "execute":
                    raise ValueError(
                        "Current household authority or policy refused the replacement."
                    )
                await p.connection.execute(
                    db.plans.update()
                    .where(p.scope(db.plans), db.plans.c.plan_id == result.plan.plan_id)
                    .values(reservation=reservation)
                )
                if latest["approver"] and not current["explicit"]:
                    approved = await PlanService(p).approve_locked(
                        result.plan.plan_id, principal
                    )
                    if approved.decision != "execute":
                        raise ValueError(
                            "Current budget or consent rules require member approval."
                        )
        except ValueError as exc:
            await self.block(stored, generation, principal, str(exc), transient=False)
        except Exception:
            if p.connection.in_transaction():
                await p.connection.rollback()
            await self.block(
                stored,
                generation,
                principal,
                "Planning temporarily failed; the plan remains held.",
                transient=True,
            )

    async def block(
        self,
        stored: dict[str, Any],
        generation: int,
        principal: Principal,
        reason: str,
        *,
        transient: bool,
    ) -> None:
        p = self.pipeline
        async with p.repo.write(p.clock):
            current = await job(p, stored)
            if (
                not current
                or current["requested_generation"] != generation
                or current["state"] == "cancelled"
            ):
                return
            horizon = Plan.model_validate(stored["document"]).horizon.end
            attempt = max(1, current["attempts"])
            delay = (5, 30, 60, 300)[min(attempt - 1, 3)]
            retry = p.clock() + timedelta(seconds=delay)
            retryable = transient and retry < horizon
            values = dict(
                state="queued" if retryable else "blocked",
                blocking_reason=reason,
                next_retry=retry.isoformat() if retryable else None,
            )
            outcome = await self.service.command(
                principal,
                dict(
                    plan_id=stored["plan_id"],
                    operation="transition",
                    generation=generation,
                    values=values,
                ),
                locked=True,
            )
            if outcome.decision != "execute":
                from hirz.executor.refresh import save

                # A refused current authority may only reduce authority through the failure lifecycle.
                reason = "The initiating account no longer has authority to refresh this plan."
                await save(
                    p,
                    stored,
                    dict(state="blocked", blocking_reason=reason, next_retry=None),
                    decision=outcome.audit_id,
                )
            if current["blocking_reason"] != reason:
                member = await p.requester(principal)
                if member.member_id:
                    await notice(p, member.member_id, stored["plan_id"], reason)
