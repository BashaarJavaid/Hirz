"""Disposable internal scripted host over the ordinary local services."""

import math
import os
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import sqlalchemy as sa

from hirz import db
from hirz.audit import (
    export_document,
    fingerprint,
    public_pem,
    verify_database,
    verify_file,
    write_export,
)
from hirz.constitution.boundary import Dogwood
from hirz.executor.local import compose
from hirz.executor.observations import ingest
from hirz.executor.observations import readings as registry_readings
from hirz.executor.plans import PlanService
from hirz.executor.refresh_worker import RefreshWorker
from hirz.executor.runtime import RuntimeInputs
from hirz.executor.service import Executor
from hirz.graph.models import AssetBinding, AssetPolicy, now
from hirz.graph.repository import row_model
from hirz.graph.seeds import load_seeds, read_seed
from hirz.local import read_env, signing_key
from hirz.pipeline.audit import AuditWriter
from hirz.pipeline.hashing import action_hash
from hirz.pipeline.models import (
    Action,
    EventType,
    ExpectedEffect,
    Inverse,
    Plan,
    Principal,
    Requester,
    Revert,
    Target,
)
from hirz.pipeline.service import Pipeline, PolicyBundle
from hirz.planner.coordinator import Coordinator
from hirz.planner.scenario import workload_input
from hirz.twin.disposable import disposable
from hirz.twin.scenario import LoadedScenario, PlanningSnapshot
from hirz.twin.script import ScriptCall, selector


class Host:
    def __init__(self, loaded: LoadedScenario, pipeline: Pipeline):
        self.loaded, self.p = loaded, pipeline
        self.plans = PlanService(pipeline)
        self.coordinator = Coordinator(pipeline)
        self.saved: dict[str, str] = {}
        self.plan_id: str | None = None
        self.responded: set[str] = set()
        self.turns: list[dict[str, Any]] = []
        self.initial_summary: dict[str, Any] | None = None

    def principal(
        self, member: str, surface: Literal["alexa", "app", "scheduler"] = "alexa"
    ) -> Principal:
        # Seeded demo account mapping is explicit, not a speaker inference.
        self.loaded.ref("members", member)
        return Principal(provider="demo", sub=member, surface=surface)

    async def current(self, principal: Principal) -> Plan:
        if self.plan_id is None:
            raise ValueError("No plan has been computed")
        result = await self.plans.read_current(self.plan_id, principal)
        self.plan_id = result.plan_id
        return result

    async def create_plan(self) -> None:
        spec = self.loaded.spec.execution
        assert spec and spec.plan_at and spec.ev_needed_by
        target = await self.coordinator.intake(
            self.principal(spec.member),
            action_id=uuid4().hex,
            text=f"Set the car to {spec.ev_target:.0%} by "
            + self.loaded.time(spec.ev_needed_by)
            .astimezone(ZoneInfo(self.loaded.timezone))
            .strftime("%H:%M"),
            horizon_end=self.loaded.spec.clock.end,
        )
        if target.constraint_id is None:
            raise ValueError("Initial EV target intake failed")
        self.saved["initial_target"] = str(target.constraint_id)
        inputs = workload_input(
            self.loaded,
            PlanningSnapshot(
                at=spec.plan_at, member=spec.member, ev_target=spec.ev_target
            ),
            end=self.loaded.spec.clock.end,
        )
        inputs = inputs.model_copy(
            update=dict(
                ev_deadline=self.loaded.time(spec.ev_needed_by),
                constraints=(),
                actuator_precision=True,
            )
        )
        result = await self.coordinator.plan(self.principal(spec.member), inputs)
        if (
            result.result.plan is None
            or result.inputs is None
            or result.result.schedule is None
        ):
            raise ValueError("Initial plan is infeasible: " + result.model_dump_json())
        plan = result.result.plan
        runtime = RuntimeInputs.from_schedule(result.inputs, result.result.schedule)
        recorded = await self.plans.record(
            plan, result.result.actions, self.principal(spec.member), runtime=runtime
        )
        if recorded.decision != "execute":
            raise ValueError("Plan publication refused")
        self.plan_id = plan.plan_id
        self.initial_summary = plan.summary.model_dump(mode="json")

    async def call(self, call: ScriptCall, member: str) -> dict[str, Any]:
        principal = self.principal(member)
        args = dict(call.arguments)
        for key, reference in args.items():
            if isinstance(reference, str) and reference.startswith("$"):
                if reference[1:] not in self.saved:
                    raise ValueError("Unknown result reference in this run")
                args[key] = self.saved[reference[1:]]
        value: str | None = None
        result: Any
        if call.tool == "get_household_plan":
            result = (await self.current(principal)).model_dump(mode="json")
            value = result["plan_id"]
        elif call.tool == "get_household_context":
            async with self.p.connection.begin():
                result = (await self.p.snapshot(self.p.clock())).model_dump(mode="json")
        elif call.tool == "revise_household_plan":
            intake = await self.coordinator.intake(
                principal,
                action_id=uuid4().hex,
                text=args["text"],
                horizon_end=self.loaded.spec.clock.end,
                replaces=UUID(args["replaces"]) if args.get("replaces") else None,
            )
            if (
                intake.decision is None
                or intake.decision.decision != "execute"
                or intake.constraint_id is None
            ):
                raise ValueError(
                    "Constraint intake failed: " + str(intake.clarification)
                )
            result = intake.model_dump(mode="json")
            value = str(intake.constraint_id)
        elif call.tool == "approve_action":
            plan = await self.current(principal)
            if args.get("plan", "current") not in {"current", plan.plan_id}:
                raise ValueError("Consent names a superseded plan")
            decision = (
                await self.plans.approve(plan.plan_id, principal)
                if args.get("approved", True)
                else await self.plans.cancel(plan.plan_id, principal)
            )
            if decision.decision != "execute":
                raise ValueError("Plan consent refused")
            result = decision.model_dump(mode="json")
        else:
            ident = self.loaded.ref("assets", args["asset"])
            async with self.p.connection.begin():
                binding = await self.p.repo.get(
                    "asset_bindings", {"id": self.loaded.world.bindings[ident].id}
                )
            if binding is None or self.loaded.world.assets[ident].kind != "light":
                raise ValueError("Scripted execution supports an explicitly bound lamp")
            binding_model = AssetBinding.model_validate(
                row_model("asset_bindings", binding).model_dump()
            )
            target = Target(
                adapter=binding_model.adapter, entity=binding_model.entity_id
            )
            action = Action.model_validate(
                dict(
                    action_id=uuid4().hex,
                    **{"class": "environment.lights"},
                    target=target,
                    params={"on": args["on"]},
                    requested_by=Requester(
                        member_id=None, role="unknown", surface="alexa"
                    ),
                    reason="Explicit scenario lamp request",
                    scheduled_for=self.p.clock(),
                    expected_effect=ExpectedEffect(
                        entity=target.entity,
                        attr="on",
                        value=args["on"],
                        by=self.p.clock() + timedelta(seconds=60),
                    ),
                    content_hash="",
                )
            )
            if args.get("duration_s"):
                action = action.model_copy(
                    update={
                        "revert": Revert(
                            after_s=args["duration_s"],
                            inverse=Inverse.model_validate(
                                {
                                    "class": action.action_class,
                                    "target": target,
                                    "params": {"on": not args["on"]},
                                }
                            ),
                        )
                    }
                )
            action = action.model_copy(update={"content_hash": action_hash(action)})
            decision = await self.p.enqueue(action, principal)
            if decision.status != "executing" and not (
                decision.decision == "ask" and decision.approval
            ):
                raise ValueError(
                    f"Lamp request was not queued: decision={decision.decision}, "
                    f"risk={decision.risk.band if decision.risk else None}, "
                    f"factors={[f.factor for f in decision.risk.factors] if decision.risk else []}"
                )
            result = decision.model_dump(mode="json")
            value = action.action_id
        if call.save_as:
            if call.save_as in self.saved or value is None:
                raise ValueError(
                    "Result name must be unique and identify a saved object"
                )
            self.saved[call.save_as] = value
        return {"tool": call.tool, "status": "executed", "result": result}

    async def responses(self) -> int:
        spec = self.loaded.spec.execution
        assert spec
        p = self.p
        async with p.connection.begin():
            pending = (
                (
                    await p.connection.execute(
                        sa.select(
                            db.approvals,
                            db.actions.c.proposal,
                            db.actions.c.principal,
                        )
                        .join(
                            db.actions,
                            sa.and_(
                                db.actions.c.household_id
                                == db.approvals.c.household_id,
                                db.actions.c.action_id == db.approvals.c.action_id,
                            ),
                        )
                        .where(
                            p.scope(db.approvals), db.approvals.c.status == "pending"
                        )
                    )
                )
                .mappings()
                .all()
            )
        count = 0
        for row in pending:
            if row["approval_id"] in self.responded:
                continue
            action = Action.model_validate(row["proposal"])
            for rule in spec.responses:
                binding = self.loaded.spec.bindings.get(rule.asset)
                entity = binding.entity if binding else rule.asset
                if (
                    self.loaded.time(rule.start)
                    <= p.clock()
                    < self.loaded.time(rule.end)
                    and action.action_class == rule.action_class
                    and action.target.entity == entity
                ):
                    self.responded.add(row["approval_id"])
                    principal = self.principal(rule.member, rule.surface)
                    if action.plan_id:
                        vote = await self.plans.respond_to_action(
                            action.plan_id,
                            row["approval_id"],
                            principal,
                            approved=rule.approved,
                        )
                    else:
                        vote = await p.vote(
                            row["approval_id"], principal, approved=rule.approved
                        )
                        if vote.event_type == EventType.APPROVED:
                            await p.enqueue(
                                action,
                                Principal.model_validate(row["principal"]),
                                approval_id=row["approval_id"],
                            )
                    self.turns.append(
                        dict(
                            at=p.clock().isoformat(),
                            member=rule.member,
                            surface=rule.surface,
                            text="Yes." if rule.approved else "No.",
                            action_id=action.action_id,
                            approval_id=row["approval_id"],
                            decision=vote.model_dump(mode="json"),
                        )
                    )
                    count += 1
                    break
        return count


async def bootstrap(loaded: LoadedScenario, connection: Any) -> Pipeline:
    spec = loaded.spec.execution
    assert spec
    world = loaded.world
    await load_seeds(
        connection,
        [read_seed(loaded.seed_path)],
        lambda: world.clock() - timedelta(seconds=2),
    )
    dogwood = Dogwood()
    p = Pipeline(
        connection,
        await PolicyBundle.validate(
            world.household.id, loaded.execution_policy, dogwood
        ),
        dogwood,
        AuditWriter(signing_key(read_env(Path(".env")))),
        world.clock,
    )
    async with p.repo.write(lambda: world.clock() - timedelta(seconds=1)):
        home = await p.repo.get("households", {})
        assert home
        await p.repo.put(
            "households",
            row_model("households", home).model_copy(
                update={"rate_plan": loaded.spec.rate_plan}
            ),
            expected_version=home["valid_from"],
        )
        for slug, room in spec.rooms.items():
            old = await p.repo.get("assets", {"id": loaded.ref("assets", slug)})
            assert old
            await p.repo.put(
                "assets",
                row_model("assets", old).model_copy(update={"room_kind": room}),
                expected_version=old["valid_from"],
            )
        for slug, binding in loaded.spec.bindings.items():
            old = await p.repo.get(
                "asset_bindings", {"id": world.bindings[loaded.ref("assets", slug)].id}
            )
            assert old
            await p.repo.put(
                "asset_bindings",
                row_model("asset_bindings", old).model_copy(
                    update={"adapter": binding.adapter, "entity_id": binding.entity}
                ),
                expected_version=old["valid_from"],
            )
        if spec.ev_needed_by:
            await p.repo.put(
                "asset_policies",
                AssetPolicy(
                    id=uuid4(),
                    household_id=p.household_id,
                    asset_id=loaded.ref("assets", "ev"),
                    needed_by=loaded.time(spec.ev_needed_by),
                ),
            )
    return p


def audit_checks(
    expected: tuple[str, ...],
    rows: list[Any],
    actions: dict[str, Action],
    *,
    ordered: bool,
) -> list[dict[str, Any]]:
    cursor = 0
    result = []
    for expectation in expected:
        event, name = selector(expectation)
        found = None
        for i in range(cursor if ordered else 0, len(rows)):
            row = rows[i]
            action = actions.get(str(row.payload.get("action_id", "")))
            if row.event_type == event and (
                name is None
                or action
                and (
                    action.action_class.startswith(name[:-1])
                    if name.endswith("*")
                    else action.action_class == name
                )
            ):
                found = i
                break
        if found is not None and ordered:
            cursor = found + 1
        result.append(
            dict(
                kind="audit_sequence_includes" if ordered else "never",
                expectation=expectation,
                status="passed" if (found is not None) == ordered else "failed",
                audit_seq=rows[found].seq if found is not None else None,
            )
        )
    return result


async def overnight_checks(
    host: Host, snapshots: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    from hirz.planner.models import ENERGY_TOL, TEMP_TOL
    from hirz.planner.workload import comfort

    p, loaded = host.p, host.loaded
    _, state = loaded.world.read()
    async with p.connection.begin():
        rows = [
            dict(r)
            for r in (
                await p.connection.execute(
                    sa.select(
                        db.actions,
                        db.audit_log.c.payload.label("lifecycle_evidence"),
                    )
                    .outerjoin(
                        db.audit_log,
                        sa.and_(
                            db.audit_log.c.household_id == db.actions.c.household_id,
                            db.audit_log.c.seq == db.actions.c.lifecycle_seq,
                        ),
                    )
                    .where(p.scope(db.actions))
                )
            ).mappings()
        ]
        plans = [
            dict(r)
            for r in (
                await p.connection.execute(sa.select(db.plans).where(p.scope(db.plans)))
            ).mappings()
        ]
        approvals = [
            dict(r)
            for r in (
                await p.connection.execute(
                    sa.select(db.approvals).where(p.scope(db.approvals))
                )
            ).mappings()
        ]
        constraints: Any = (await p.snapshot(p.clock())).data["constraints"]
    verified = {
        r["proposal"]["class"]
        for r in rows
        if r["execution_status"] == "verified"
        and not (r["lifecycle"] or {}).get("ending_of")
    }
    required = {
        "energy.battery_dispatch",
        "energy.hvac_adjust",
        "energy.ev_charge",
        "energy.appliance_start",
        "environment.lights",
    }
    terminal = [
        RuntimeInputs.model_validate(r["runtime"]).battery_terminal_kwh
        for r in plans
        if r["runtime"]
    ]
    battery = state.batteries[loaded.ref("assets", "home_battery")]
    ev = state.evs[loaded.ref("assets", "ev")]
    comfortable = True
    ceiling = True
    zones = {
        str(loaded.ref("assets", name)): name
        for name in ("hvac.living_room", "hvac.guest_room")
    }
    for snapshot in snapshots:
        at = datetime.fromisoformat(snapshot["at"])
        for observation in snapshot["observations"]:
            asset, sample = observation.get("asset_id"), observation["state"]
            if asset in zones and sample.get("temp_f") is not None:
                lower, upper, _ = comfort(at, zones[asset])
                comfortable &= lower - TEMP_TOL <= sample["temp_f"] <= upper + TEMP_TOL
            if asset == str(loaded.ref("assets", "ev")) and at >= loaded.time("17:35"):
                ceiling &= sample["soc"] <= 0.5 + ENERGY_TOL
    statuses = {
        "verified_device_classes": required <= verified,
        "separate_nighttime_votes": {
            r["decision"]["constitution"]["rule"] for r in host.turns
        }
        >= {"energy.hvac_adjust", "energy.appliance_start"},
        "no_unresolved_approvals": all(
            r["status"] not in {"pending", "approved"} for r in approvals
        ),
        "ev_delivery_and_ceiling": abs(ev.soc - 0.5) <= 1e-6,
        "ev_ceiling_throughout": ceiling,
        "comfort_at_replay_boundaries": comfortable,
        "completed_current_plan": any(
            q["document"]["status"] == "completed" for q in plans
        ),
        "every_device_request_answered": all(
            r["approval_id"] in host.responded
            for r in approvals
            if any(
                a["action_id"] == r["action_id"]
                and a["proposal"].get("plan_id")
                and a["proposal"]["class"] in required
                for a in rows
            )
        ),
        "appliance_completed": state.appliances[
            loaded.ref("assets", "dishwasher")
        ].completions
        == 1,
        "battery_terminal_preserved": bool(terminal)
        and all(v is not None and abs(v - (terminal[0] or 0)) <= 1e-6 for v in terminal)
        and abs(battery.soc * battery.capacity_kwh - (terminal[0] or 0)) <= 1e-6,
        "superseded_work_cancelled": all(
            r["execution_status"] == "cancelled"
            or (
                r["execution_status"] == "skipped"
                and (r.get("lifecycle_evidence") or {}).get("action_id")
                == r["action_id"]
                and (r.get("lifecycle_evidence") or {}).get("status") == "skipped"
                and (r.get("lifecycle_evidence") or {}).get("reason")
                == "expired before consent"
            )
            for r in rows
            if r["proposal"].get("plan_id")
            in {q["plan_id"] for q in plans if q["document"]["status"] == "superseded"}
            and r["execution_attempt_seq"] is None
        ),
        "dad_attribution": any(
            c["provenance"]["source"] == "member:" + str(loaded.ref("members", "dad"))
            and c["provenance"]["surface"] == "alexa"
            and c["provenance"].get("claimed_author") is None
            and c["provenance"]["encoded"].get("kind") == "appliance_not_before"
            and datetime.fromisoformat(c["provenance"]["encoded"]["at"])
            == loaded.time("23:00")
            for c in constraints
        ),
        "dad_kitchen_constraint_enforced": all(
            datetime.fromisoformat(r["proposal"]["scheduled_for"])
            >= loaded.time("23:00")
            for r in rows
            if r["proposal"]["class"] == "energy.appliance_start"
            and r["execution_status"] == "verified"
        ),
    }
    return [
        dict(kind="overnight", expectation=k, status="passed" if v else "failed")
        for k, v in statuses.items()
    ]


async def retain_audit(p: Pipeline, folder: Path) -> tuple[dict[str, Any], list[Any]]:
    summary, rows = await verify_database(
        p.connection, p.household_id, p.audit.key.public_key(), collect=True
    )
    write_export(
        folder / "audit.json",
        export_document(p.household_id, p.audit.key.public_key(), rows),
    )
    fd = os.open(folder / "public-key.pem", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as keyfile:
        keyfile.write(public_pem(p.audit.key.public_key()))
    verified = verify_file(
        folder / "audit.json",
        p.household_id,
        trusted_fingerprint=fingerprint(p.audit.key.public_key()),
    )
    if summary["status"] != verified["status"] or verified["status"] not in {
        "valid",
        "empty",
    }:
        raise ValueError("Signed audit verification failed")
    return verified, rows


async def run_execution(
    loaded: LoadedScenario,
    *,
    headless: bool,
    assertions: bool,
    speed: float | None,
    to: str | None,
    sleep: Callable[[float], Awaitable[None]],
    progress: Callable[[str], None] | None,
    artifacts_dir: Path | None,
    ha_config: Path | None,
) -> dict[str, Any]:
    spec, world = loaded.spec, loaded.world
    assert spec.execution
    pace = spec.clock.speed if speed is None else speed
    if not math.isfinite(pace) or pace <= 0:
        raise ValueError("Invalid scenario speed")
    live = any(b.adapter == "ha" for b in spec.bindings.values())
    if live and (
        headless or pace != 1 or abs((now() - spec.clock.start).total_seconds()) > 60
    ):
        raise ValueError(
            "HA scenarios require current time and normal wall-clock pacing"
        )
    stop = loaded.time(to) if to else spec.clock.end
    folder = artifacts_dir or Path("secrets/scenario-runs") / f"{spec.id}-{uuid4().hex}"
    folder.parent.mkdir(parents=True, exist_ok=True)
    folder.mkdir(mode=0o700)
    report: dict[str, Any] = dict(
        scenario=spec.id,
        status="failed",
        source="mixed (see observation sources)" if live else "twin",
        host="internal scripted host",
        input_hashes=loaded.hashes,
        artifacts_dir=str(folder),
        execution_policy_version=loaded.execution_policy.version,
        events=[],
        checks=[],
        snapshots=[],
        responses=[],
        deferred=[c.model_dump() for c in spec.assertions.deferred],
        limitations=[
            "No MCP or authentication; policy preview is simulated, execution uses seeded validated policy.",
            "No live feeds or Bedrock. Device sources are explicit; published rates are not live.",
        ],
    )
    try:
        async with disposable(read_env(Path(".env"))) as connection:
            report["database"] = str(connection.engine.url.database)
            p = await bootstrap(loaded, connection)
            if live:
                p.clock = now
            host = Host(loaded, p)
            config = ",".join(
                f"{d}:{'scenario' if d == 'energy' and spec.rate_plan == 'comed_time_of_day' else 'twin'}"
                for d in spec.adapters
            )
            registry = None
            try:
                registry = await compose(
                    p, world=world, config=config, ha_path=ha_config, scenario=True
                )
                await registry.start()
                await loaded.registry.start()
            except BaseException:
                try:
                    if connection.in_transaction():
                        await connection.rollback()
                    report["audit"], _ = await retain_audit(p, folder)
                finally:
                    if registry is not None:
                        await registry.close()
                    await loaded.registry.close()
                raise
            executor = Executor(p, registry, world=world, refresh_polls=True)
            refresh = RefreshWorker(p, registry, world=world)
            try:
                fixed = {
                    spec.clock.start,
                    stop,
                    *[t for t in loaded.times if t <= stop],
                    *[t for t in loaded.check_times if t <= stop],
                    *[
                        loaded.time(t)
                        for t in spec.assertions.ev_soc_at
                        if loaded.time(t) <= stop
                    ],
                    *(
                        [loaded.time(spec.execution.plan_at)]
                        if spec.execution.plan_at
                        else []
                    ),
                }
                fixed = {t for t in fixed if t <= stop}
                proposals: set[UUID] = set()
                at = spec.clock.start
                reached: set[int] = set()
                while True:
                    if not headless and to is None:
                        remaining = max(
                            0,
                            (at - (now() if live else world.clock())).total_seconds()
                            / pace,
                        )
                        while remaining:
                            delay = min(30, remaining)
                            await sleep(delay)
                            remaining -= delay
                    world.clock.jump(max(at, world.clock()))
                    world.read()
                    if to is not None and at >= stop:
                        break
                    await executor.sweep(endings_only=True)
                    if at >= stop and to is None and spec.execution.plan_at:
                        async with connection.begin():
                            completed_candidates = (
                                (
                                    await connection.execute(
                                        sa.select(db.actions.c.proposal).where(
                                            p.scope(db.actions),
                                            db.actions.c.proposal[
                                                "plan_id"
                                            ].astext.is_not(None),
                                        )
                                    )
                                )
                                .scalars()
                                .all()
                            )
                        seen_plans = set()
                        for proposal in completed_candidates:
                            action = Action.model_validate(proposal)
                            if action.plan_id not in seen_plans:
                                await executor.complete_plan(action)
                                seen_plans.add(action.plan_id)
                    # Timeline file order is preserved; scripts only record/read work.
                    if spec.execution.plan_at and at == loaded.time(
                        spec.execution.plan_at
                    ):
                        await ingest(p, registry, host.principal(spec.execution.member))
                        await host.create_plan()
                    for index, when in enumerate(loaded.times):
                        if when != at:
                            continue
                        event = spec.timeline[index]
                        event_result = await loaded.apply(index, proposals, p.boundary)
                        if event.event == "voice":
                            for call in event.script:
                                if isinstance(call, ScriptCall):
                                    event_result["tools"].append(
                                        await host.call(call, event.member or "")
                                    )
                            if any(isinstance(c, ScriptCall) for c in event.script):
                                event_result["status"] = "executed"
                        report["events"].append(event_result)
                        if progress:
                            progress(
                                f"{at.isoformat()} {event.event}: {event_result['status']}"
                            )
                    # Presence changes are ingested before planning and device evaluation.
                    await ingest(p, registry, host.principal(spec.execution.member))
                    if at < stop:
                        await refresh.batch()
                        await executor.sweep()
                        while await host.responses():
                            await executor.sweep()
                    readings = await loaded.observations()
                    sources = {}
                    if live:
                        actual_readings = await registry_readings(registry)
                        subjects = {r.asset_id for r in actual_readings if r.asset_id}
                        readings = (
                            tuple(r for r in readings if r.asset_id not in subjects)
                            + actual_readings
                        )
                        sources = {
                            r.asset_id: r.source for r in actual_readings if r.asset_id
                        }
                    report["snapshots"].append(
                        dict(
                            at=at.isoformat(),
                            observations=[r.model_dump(mode="json") for r in readings],
                        )
                    )
                    for i, when in enumerate(loaded.check_times):
                        if when == at:
                            reached.add(i)
                            report["checks"].append(
                                dict(
                                    index=i,
                                    kind=spec.assertions.checks[i].kind,
                                    at=at.isoformat(),
                                    status="unchecked"
                                    if not assertions
                                    else "passed"
                                    if loaded.check(
                                        spec.assertions.checks[i],
                                        readings,
                                        sources=sources,
                                    )
                                    else "failed",
                                )
                            )
                    for check_time, bounds in spec.assertions.ev_soc_at.items():
                        if loaded.time(check_time) == at:
                            soc = world.read()[1].evs[loaded.ref("assets", "ev")].soc
                            report["checks"].append(
                                dict(
                                    kind="ev_soc_at",
                                    at=at.isoformat(),
                                    actual=soc,
                                    status="unchecked"
                                    if not assertions
                                    else "passed"
                                    if bounds.matches(soc)
                                    else "failed",
                                )
                            )
                    if at >= stop:
                        break
                    async with connection.begin():
                        due = (
                            (
                                await connection.execute(
                                    sa.select(db.actions.c.due_at).where(
                                        p.scope(db.actions),
                                        db.actions.c.execution_status == "scheduled",
                                    )
                                )
                            )
                            .scalars()
                            .all()
                        )
                        retries = (
                            (
                                await connection.execute(
                                    sa.select(db.plan_refresh_jobs.c.next_retry).where(
                                        p.scope(db.plan_refresh_jobs),
                                        db.plan_refresh_jobs.c.state == "queued",
                                    )
                                )
                            )
                            .scalars()
                            .all()
                        )
                        expiry = (
                            (
                                await connection.execute(
                                    sa.select(db.approvals.c.expires_at).where(
                                        p.scope(db.approvals),
                                        db.approvals.c.status == "pending",
                                    )
                                )
                            )
                            .scalars()
                            .all()
                        )
                    # A five-minute poll covers observation freshness;
                    # exact action, retry and approval deadlines take precedence.
                    candidates = [
                        *fixed,
                        *due,
                        *retries,
                        *expiry,
                        *(
                            [world.clock() + timedelta(microseconds=1)]
                            if world.clock() > at
                            else []
                        ),
                        at + timedelta(minutes=5),
                        stop,
                    ]
                    at = min(
                        t
                        for t in candidates
                        if t is not None and t > world.clock() and t <= stop
                    )
                report["checks"].extend(
                    dict(index=i, kind=c.kind, status="not_reached")
                    for i, c in enumerate(spec.assertions.checks)
                    if i not in reached
                )
                report["checks"].extend(
                    dict(
                        kind="ev_soc_at",
                        at=loaded.time(t).isoformat(),
                        status="not_reached",
                    )
                    for t in spec.assertions.ev_soc_at
                    if loaded.time(t) > stop
                    or to is not None
                    and loaded.time(t) == stop
                )
                report["responses"] = host.turns
                report["preview_policy_version"] = loaded.policy.version
                report["initial_summary"] = host.initial_summary
                async with connection.begin():
                    actions = {
                        r["action_id"]: Action.model_validate(r["proposal"])
                        for r in (
                            await connection.execute(
                                sa.select(db.actions).where(p.scope(db.actions))
                            )
                        ).mappings()
                    }
                    report["plans"] = [
                        r
                        for r in (
                            await connection.execute(
                                sa.select(db.plans.c.document).where(p.scope(db.plans))
                            )
                        ).scalars()
                    ]
                report["audit"], rows = await retain_audit(p, folder)
                checks = audit_checks(
                    spec.assertions.audit_sequence_includes, rows, actions, ordered=True
                ) + audit_checks(spec.assertions.never, rows, actions, ordered=False)
                for field, bounds in spec.assertions.plan_summary.items():
                    actual = (host.initial_summary or {}).get(field)
                    checks.append(
                        dict(
                            kind="plan_summary",
                            field=field,
                            actual=actual,
                            status="passed" if bounds.matches(actual) else "failed",
                        )
                    )
                for check in checks:
                    if to:
                        check["status"] = "not_reached"
                    elif not assertions:
                        check["status"] = "unchecked"
                if spec.execution.plan_at and not to:
                    outcomes = await overnight_checks(host, report["snapshots"])
                    for action_class in (
                        "energy.battery_dispatch",
                        "energy.hvac_adjust",
                        "energy.ev_charge",
                        "energy.appliance_start",
                        "environment.lights",
                    ):
                        verified = audit_checks(
                            (f"VERIFIED:{action_class}",), rows, actions, ordered=True
                        )[0]
                        outcomes.append(verified | {"kind": "verified_action"})
                    for consent_time in ("17:36", "23:31"):
                        consent_at = loaded.time(consent_time)
                        found = any(
                            r.event_type == "PLAN_APPROVED"
                            and consent_at
                            <= r.created_at
                            < consent_at + timedelta(seconds=1)
                            and r.payload.get("surface") == "alexa"
                            for r in rows
                        )
                        outcomes.append(
                            dict(
                                kind="explicit_plan_consent",
                                at=consent_at.isoformat(),
                                status="passed" if found else "failed",
                            )
                        )
                    if not assertions:
                        for outcome in outcomes:
                            outcome["status"] = "unchecked"
                    report["checks"].extend(outcomes)
                report["checks"].extend(checks)
                report["status"] = (
                    "failed"
                    if any(c["status"] == "failed" for c in report["checks"])
                    else "stopped"
                    if to
                    else (
                        "item22_execution_passed"
                        if spec.execution.plan_at
                        else "execution_checks_passed"
                    )
                    if assertions
                    else "completed_unchecked"
                )
                if report["status"] == "failed":
                    raise ValueError("Scenario assertions failed")
            finally:
                report["responses"] = host.turns
                report["initial_summary"] = host.initial_summary
                report["preview_policy_version"] = loaded.policy.version
                if not (folder / "audit.json").exists():
                    if connection.in_transaction():
                        await connection.rollback()
                    try:
                        report["audit"], _ = await retain_audit(p, folder)
                    except Exception as audit_error:
                        report["audit_error"] = type(audit_error).__name__
                await registry.close()
                await loaded.registry.close()
    except BaseException as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    # A runtime failure must retain the checks it prevented, rather than silently
    # omitting the overnight obligations from the report.
    reached_indices = {c.get("index") for c in report["checks"]}
    report["checks"].extend(
        dict(index=i, kind=c.kind, status="not_reached")
        for i, c in enumerate(spec.assertions.checks)
        if i not in reached_indices
    )
    for time in spec.assertions.ev_soc_at:
        at_text = loaded.time(time).isoformat()
        if not any(
            c["kind"] == "ev_soc_at" and c.get("at") == at_text
            for c in report["checks"]
        ):
            report["checks"].append(
                dict(kind="ev_soc_at", at=at_text, status="not_reached")
            )
    for kind, expectations in (
        ("audit_sequence_includes", spec.assertions.audit_sequence_includes),
        ("never", spec.assertions.never),
        ("plan_summary", spec.assertions.plan_summary),
    ):
        if not any(c["kind"] == kind for c in report["checks"]):
            report["checks"].extend(
                dict(kind=kind, expectation=value, status="not_reached")
                for value in expectations
            )
    write_export(folder / "report.json", report)
    return report
