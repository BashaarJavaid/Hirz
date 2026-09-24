"""Durable refresh requests and generation-checked lifecycle in Pipeline transactions."""

from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from hirz import db
from hirz.executor.runtime import RuntimeInputs, Thresholds, deviates, predicted
from hirz.explainer.core import context, prepared
from hirz.pipeline.hashing import digest
from hirz.pipeline.models import Action, Decision, EventType, Plan, Principal

if TYPE_CHECKING:
    from hirz.pipeline.service import Pipeline

TERMINAL = {"superseded", "completed", "abandoned"}


async def job(p: "Pipeline", stored: dict[str, Any]) -> dict[str, Any] | None:
    value = (
        (
            await p.connection.execute(
                sa.select(db.plan_refresh_jobs)
                .where(
                    p.scope(db.plan_refresh_jobs),
                    db.plan_refresh_jobs.c.lineage_id
                    == (stored["lineage_id"] or stored["plan_id"]),
                )
                .with_for_update()
            )
        )
        .mappings()
        .one_or_none()
    )
    return dict(value) if value else None


async def save(
    p: "Pipeline",
    stored: dict[str, Any],
    values: dict[str, Any],
    *,
    decision: int | None = None,
) -> None:
    lineage = stored["lineage_id"] or stored["plan_id"]
    old = await job(p, stored)
    seq = await p.audit.append(
        p.connection,
        p.household_id,
        p.clock(),
        EventType.PLAN_REFRESH,
        {
            "lineage_id": lineage,
            "plan_id": stored["plan_id"],
            "transition": values,
            "decision_seq": decision,
        },
    )
    if old:
        await p.connection.execute(
            db.plan_refresh_jobs.update()
            .where(
                p.scope(db.plan_refresh_jobs),
                db.plan_refresh_jobs.c.lineage_id == lineage,
            )
            .values(**values, audit_seq=seq)
        )
    else:
        initial = dict(
            plan_id=stored["plan_id"],
            state="idle",
            requested_generation=0,
            running_generation=None,
            reasons=[],
            explicit=False,
            attempts=0,
            next_retry=None,
            blocking_reason=None,
            fingerprint={},
        )
        await p.connection.execute(
            db.plan_refresh_jobs.insert().values(
                household_id=p.household_id,
                lineage_id=lineage,
                **(initial | values),
                audit_seq=seq,
            )
        )


async def queue(
    p: "Pipeline",
    stored: dict[str, Any],
    reason: str,
    *,
    explicit: bool = False,
    fingerprint: dict[str, Any] | None = None,
    decision: int | None = None,
) -> None:
    from hirz.executor.plans import stop_unstarted

    if stored["document"]["status"] in TERMINAL:
        return
    old = await job(p, stored)
    if (
        old
        and old["state"] in {"queued", "running"}
        and reason in old["reasons"]
        and (not explicit or old["explicit"])
        and (fingerprint is None or fingerprint == old["fingerprint"])
    ):
        return
    reasons = list(dict.fromkeys([*(old["reasons"] if old else []), reason]))
    await save(
        p,
        stored,
        dict(
            state="queued",
            requested_generation=(old["requested_generation"] if old else 0) + 1,
            reasons=reasons,
            explicit=explicit or bool(old and old["explicit"]),
            attempts=0,
            next_retry=None,
            blocking_reason=None,
            fingerprint=fingerprint
            if fingerprint is not None
            else old["fingerprint"]
            if old
            else {},
        ),
        decision=decision,
    )
    await stop_unstarted(p, stored["plan_id"], EventType.PLAN_REFRESH, "held")
    await p.connection.execute(
        db.plans.update()
        .where(p.scope(db.plans), db.plans.c.plan_id == stored["plan_id"])
        .values(document=stored["document"] | {"status": "refreshing"})
    )


async def owned_control(
    p: "Pipeline",
    observation: Any,
    *,
    since: datetime | None = None,
    previous_mode: str | None = None,
) -> bool:
    binding = (
        (
            await p.connection.execute(
                sa.select(db.asset_bindings).where(
                    p.scope(db.asset_bindings),
                    db.asset_bindings.c.asset_id == observation.asset_id,
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if not binding:
        return False
    return await _matches_control(
        p,
        observation,
        binding["attributes"],
        await _verified_controls(p, observation.observed_at),
        since=since,
        previous_mode=previous_mode,
    )


async def _verified_controls(p: "Pipeline", at: datetime) -> list[dict[str, Any]]:
    rows = (
        (
            await p.connection.execute(
                sa.select(db.actions, db.audit_log.c.created_at)
                .join(
                    db.audit_log,
                    sa.and_(
                        db.audit_log.c.household_id == db.actions.c.household_id,
                        db.audit_log.c.seq == db.actions.c.execution_attempt_seq,
                    ),
                )
                .where(
                    p.scope(db.actions),
                    db.actions.c.execution_status == "verified",
                    db.audit_log.c.created_at <= at,
                )
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


async def _matches_control(
    p: "Pipeline",
    observation: Any,
    binding: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    since: datetime | None = None,
    previous_mode: str | None = None,
) -> bool:
    controls = observation.state.model_dump()
    for row in rows:
        target = row["proposal"]["target"]
        if (
            target["adapter"] != binding["adapter"]
            or target["entity"] != binding["entity_id"]
        ):
            continue
        if row["created_at"] > observation.observed_at or (
            since is not None and row["created_at"] < since
        ):
            continue
        params = row["proposal"]["params"]
        if row["proposal"]["class"] == "energy.appliance_start":
            params = {"on": True}
            if controls.get("on") is False and row["proposal"].get("plan_id"):
                from hirz.executor.plans import get

                owner = await get(p, row["proposal"]["plan_id"])
                if owner["runtime"]:
                    runtime = RuntimeInputs.model_validate(owner["runtime"])
                    appliance = (
                        runtime.prediction_workload or runtime.workload
                    ).appliance
                    if appliance and observation.observed_at >= row[
                        "created_at"
                    ] + timedelta(minutes=appliance.cycle_minutes):
                        params = {"on": False}
        from hirz.graph.models import ObservationState

        if params and params.keys() <= ObservationState.model_fields.keys():
            params = ObservationState.model_validate(params).model_dump(
                exclude_unset=True
            )
        if params and all(controls.get(k) == v for k, v in params.items()):
            # HA only changes setpoint; an unexplained mode change is never attributed to it.
            if (
                previous_mode is not None
                and "mode" not in params
                and controls.get("mode") != previous_mode
            ):
                return False
            return True
    return False


async def applied_controls(
    p: "Pipeline", stored: dict[str, Any]
) -> tuple[tuple[datetime, Action], ...]:
    verified = db.audit_log.alias("verified")
    rows = (
        await p.connection.execute(
            sa.select(db.actions.c.proposal, verified.c.created_at)
            .join(
                verified,
                sa.and_(
                    verified.c.household_id == db.actions.c.household_id,
                    verified.c.seq == db.actions.c.lifecycle_seq,
                ),
            )
            .join(
                db.plans,
                sa.and_(
                    db.plans.c.household_id == db.actions.c.household_id,
                    db.plans.c.plan_id == db.actions.c.proposal["plan_id"].astext,
                ),
            )
            .where(
                p.scope(db.actions),
                db.plans.c.lineage_id == (stored["lineage_id"] or stored["plan_id"]),
                db.actions.c.execution_status == "verified",
                verified.c.event_type == EventType.VERIFIED,
                verified.c.payload["action_id"].astext == db.actions.c.action_id,
                verified.c.payload["execution_attempt_seq"].as_integer()
                == db.actions.c.execution_attempt_seq,
                verified.c.created_at <= p.clock(),
            )
            .order_by(verified.c.created_at, verified.c.seq)
        )
    ).mappings()
    return tuple((r["created_at"], Action.model_validate(r["proposal"])) for r in rows)


async def fingerprint(p: "Pipeline", stored: dict[str, Any]) -> dict[str, Any]:
    snapshot = await p.snapshot(p.clock())
    data: Any = snapshot.data
    bound = {(b["adapter"], b["entity_id"]) for b in data["asset_bindings"]}
    applied = (
        tuple(
            (at, a)
            for at, a in await applied_controls(p, stored)
            if (a.target.adapter, a.target.entity) in bound
        )
        if stored["runtime"]
        else ()
    )
    policy = p.bundle.policy().model_dump(mode="json")
    inputs = dict(data=data, runtime=stored["runtime"], applied=applied, policy=policy)
    cached = p._refresh_fingerprint
    if (
        p.repo._at is not None
        and cached is not None
        and cached[0] == p.repo._revision
        and cached[1] == inputs
    ):
        return deepcopy(cached[2])
    structural = {}
    for name in (
        "households",
        "members",
        "member_accounts",
        "asset_bindings",
        "assets",
        "asset_policies",
        "schedule_events",
        "constraints",
        "preferences",
    ):
        structural[name] = [
            {
                k: v
                for k, v in r.items()
                if k not in {"valid_from", "valid_to", "staleness_seconds"}
            }
            for r in data.get(name, [])
        ]
    runtime = (
        RuntimeInputs.model_validate(stored["runtime"]) if stored["runtime"] else None
    )
    bindings = {str(b["asset_id"]): b["entity_id"] for b in data["asset_bindings"]}
    samples = {}
    for o in data["observations"]:
        key = str(o.get("asset_id") or o.get("member_id") or o["domain"])
        state = o["state"]
        entity = bindings.get(str(o.get("asset_id")), "")
        expected = (
            predicted(
                runtime, datetime.fromisoformat(o["observed_at"]), applied=applied
            )
            if runtime
            else {}
        )
        physical = expected.get(entity, {})
        thresholds = (
            runtime.thresholds.get(key, Thresholds()) if runtime else Thresholds()
        )
        samples[key] = {
            k: v
            for k, v in state.items()
            if v is not None
            and k
            in {
                "present",
                "sleeping",
                "zone_id",
                "available",
                "plugged_in",
                "charging",
                "dispatch_kw",
                "on",
                "mode",
                "target_f",
            }
        }
        physical = {
            k: v for k, v in physical.items() if k in {"temp_f", "soc", "power_kw"}
        }
        if runtime and entity == "ev" and state.get("soc") is not None:
            governing = next(
                (
                    a
                    for at, a in reversed(applied)
                    if at <= datetime.fromisoformat(o["observed_at"])
                    and a.target.entity == entity
                    and a.action_class == "energy.ev_charge"
                ),
                None,
            )
            ev = (runtime.prediction_workload or runtime.workload).ev
            if (
                governing
                and governing.params.get("charging") is True
                and ev
                and "charge_limit" in governing.params
                and abs(
                    Decimal(str(state["soc"]))
                    - Decimal(str(governing.params["charge_limit"]))
                )
                <= Decimal("0.0001")
                and state.get("power_kw") in {0, round(ev.charger_kw, 4)}
            ):
                physical.pop("power_kw", None)
        if deviates(state, physical, thresholds):
            samples[key]["deviation"] = {
                k: v for k, v in state.items() if v is not None
            }
    result = {
        "graph": digest(structural),
        "policy": digest(policy),
        "samples": samples,
        "inputs": digest(stored["runtime"]),
    }
    if p.repo._at is not None:
        p._refresh_fingerprint = (p.repo._revision, deepcopy(inputs), deepcopy(result))
    return result


async def compensate_owned_controls(
    p: "Pipeline", previous: dict[str, Any], current: dict[str, Any]
) -> None:
    from hirz.graph.models import Observation
    from hirz.planner.coordinator import clean

    snapshot = await p.snapshot(p.clock())
    observations = tuple(
        Observation.model_validate(clean(raw))
        for raw in snapshot.data["observations"]
        if raw.get("asset_id")
    )
    if not observations:
        return
    assets = {str(o.asset_id) for o in observations}
    relevant = [
        b for b in snapshot.data["asset_bindings"] if str(b["asset_id"]) in assets
    ]
    bindings = {str(b["asset_id"]): b for b in relevant}
    if len(bindings) != len(relevant):
        raise ValueError("Ambiguous asset binding")
    rows = await _verified_controls(p, max(o.observed_at for o in observations))
    for obs in observations:
        key = str(obs.asset_id)
        previous_sample = previous.get("samples", {}).get(key, {})
        binding = bindings.get(key)
        if binding and await _matches_control(
            p, obs, binding, rows, previous_mode=previous_sample.get("mode")
        ):
            for field in ("charging", "dispatch_kw", "on", "mode", "target_f"):
                if field in current["samples"].get(key, {}):
                    previous_sample[field] = current["samples"][key][field]


async def detect(
    p: "Pipeline", stored: dict[str, Any], *, decision: int | None = None
) -> None:
    if stored["document"]["status"] in TERMINAL:
        return
    old = await job(p, stored)
    current = await fingerprint(p, stored)
    reason = None
    if old and old["fingerprint"]:
        original_fingerprint = digest(old["fingerprint"])
        await compensate_owned_controls(p, old["fingerprint"], current)
        if old["fingerprint"] == current and original_fingerprint != digest(current):
            await save(p, stored, {"fingerprint": current}, decision=decision)
    if stored["runtime"] is None:
        if not old or old["state"] != "blocked" or current != old["fingerprint"]:
            reason = "Complete runtime inputs are required from an eligible member."
    elif old and old["fingerprint"] and current != old["fingerprint"]:
        reason = "Household inputs, policy, control state or prediction changed."
    if reason:
        await queue(p, stored, reason, fingerprint=current, decision=decision)
        if stored["runtime"] is None:
            await save(
                p,
                stored,
                {"state": "blocked", "blocking_reason": reason, "next_retry": None},
                decision=decision,
            )
    elif not old or not old["fingerprint"]:
        await save(p, stored, {"fingerprint": current}, decision=decision)


async def invalidate_all(
    p: "Pipeline", reason: str, *, explicit: bool = False, decision: int | None = None
) -> None:
    rows = (
        (await p.connection.execute(sa.select(db.plans).where(p.scope(db.plans))))
        .mappings()
        .all()
    )
    for row in rows:
        await queue(p, dict(row), reason, explicit=explicit, decision=decision)


async def fresh(p: "Pipeline", stored: dict[str, Any]) -> bool:
    old = await job(p, stored)
    if not stored["runtime"] or (old and old["state"] != "idle"):
        return False
    if not old:
        return True
    current = await fingerprint(p, stored)
    await compensate_owned_controls(p, old["fingerprint"], current)
    return bool(old["fingerprint"] == current)


async def prepare(p: "Pipeline", action: Action, principal: Principal) -> None:
    from hirz.executor.plans import eligible, get
    from hirz.pipeline.service import identity

    if action.params != getattr(p, "_refresh_command", None):
        raise ValueError("Refresh lifecycle requires its internal service")
    stored = await get(p, str(action.params["plan_id"]))
    member = await p.requester(principal)
    if not eligible(p, member, principal) or stored["document"]["status"] in TERMINAL:
        raise ValueError("Refresh requires current household authority")
    if principal.surface == "scheduler" and identity(principal) != (
        stored["approver"] or stored["requester"]
    ):
        raise ValueError("Background refresh requires the linked initiating account")


async def commit(
    p: "Pipeline", action: Action, decision: Decision, principal: Principal
) -> None:
    from hirz.executor.plans import get

    stored = await get(p, str(action.params["plan_id"]))
    op = action.params["operation"]
    seq = decision.audit_id
    if op == "resume":
        from hirz.executor.plans import resume

        await resume(
            p,
            stored,
            str(action.params["action_id"]),
            str(action.params["approval_id"]),
        )
    elif op == "feeds":
        runtime = RuntimeInputs.model_validate(action.params["runtime"])
        runtime.validate_plan(Plan.model_validate(stored["document"]))
        stored["runtime"] = runtime.model_dump(mode="json")
        await p.connection.execute(
            db.plans.update()
            .where(p.scope(db.plans), db.plans.c.plan_id == stored["plan_id"])
            .values(runtime=stored["runtime"])
        )
        current = await fingerprint(p, stored)
        if action.params["baseline"]:
            await save(p, stored, {"fingerprint": current}, decision=seq)
        else:
            await queue(
                p,
                stored,
                "Configured price, weather or calendar changed",
                fingerprint=current,
                decision=seq,
            )
    elif op in {"request", "inputs"}:
        if stored["requester"] is None:
            from hirz.pipeline.service import identity

            stored["requester"] = identity(
                principal.model_copy(update={"surface": "scheduler"})
            )
            await p.connection.execute(
                db.plans.update()
                .where(p.scope(db.plans), db.plans.c.plan_id == stored["plan_id"])
                .values(requester=stored["requester"])
            )
        retry_id = action.params.get("retry_action_id")
        if retry_id is not None:
            from hirz.executor.replanning import operation
            from hirz.executor.storage import row

            if (
                principal.surface == "scheduler"
                or not action.params["explicit"]
                or not stored["runtime"]
            ):
                raise ValueError(
                    "A device retry requires an explicit eligible member request"
                )
            failed = await row(p, str(retry_id))
            failed_action = Action.model_validate(failed["proposal"])
            if failed["execution_status"] != "failed" or not failed_action.plan_id:
                raise ValueError("Explicit retry must name a failed plan operation")
            original = await get(p, failed_action.plan_id)
            if original["lineage_id"] != stored["lineage_id"]:
                raise ValueError("Retry belongs to a different plan lineage")
            prior_runtime = RuntimeInputs.model_validate(stored["runtime"])
            op_key = operation(failed_action)
            failures = (
                (
                    await p.connection.execute(
                        sa.select(db.actions).where(
                            p.scope(db.actions),
                            db.actions.c.execution_status == "failed",
                        )
                    )
                )
                .mappings()
                .all()
            )
            retry_ids = tuple(
                r["action_id"]
                for r in failures
                if operation(Action.model_validate(r["proposal"])) == op_key
            )
            retry_runtime = prior_runtime.model_copy(
                update={
                    "retry_actions": tuple(
                        dict.fromkeys((*prior_runtime.retry_actions, *retry_ids))
                    ),
                    "exhausted": tuple(
                        k for k in prior_runtime.exhausted if k != op_key
                    ),
                }
            )
            stored["runtime"] = retry_runtime.model_dump(mode="json")
            await p.connection.execute(
                db.plans.update()
                .where(p.scope(db.plans), db.plans.c.plan_id == stored["plan_id"])
                .values(runtime=stored["runtime"])
            )
        if op == "inputs":
            runtime = RuntimeInputs.model_validate(action.params["runtime"])
            runtime.validate_plan(Plan.model_validate(stored["document"]))
            prior = (
                RuntimeInputs.model_validate(stored["runtime"])
                if stored["runtime"]
                else None
            )
            if prior:
                runtime.preserves(prior)
            if prior:
                runtime = runtime.model_copy(
                    update={
                        "prediction": prior.prediction,
                        "prediction_workload": prior.prediction_workload
                        or prior.workload,
                        "estimates": prior.estimates,
                        "exhausted": prior.exhausted,
                        "retry_actions": prior.retry_actions,
                    }
                )
            stored["runtime"] = runtime.model_dump(mode="json")
            await p.connection.execute(
                db.plans.update()
                .where(p.scope(db.plans), db.plans.c.plan_id == stored["plan_id"])
                .values(runtime=stored["runtime"])
            )
        await queue(
            p,
            stored,
            str(action.params["reason"]),
            explicit=action.params["explicit"] is True,
            decision=seq,
        )
    elif op == "detect":
        await detect(p, stored, decision=seq)
    elif op == "transition":
        old = await job(p, stored)
        if old is None or old["requested_generation"] != action.params["generation"]:
            raise ValueError("Refresh generation changed")
        values: dict[str, Any] = dict(action.params["values"])  # type: ignore[arg-type]
        if values.get("next_retry") is not None:
            values["next_retry"] = datetime.fromisoformat(values["next_retry"])
        await save(p, stored, values, decision=seq)
    else:
        raise ValueError("Unknown refresh operation")


class RefreshService:
    def __init__(self, pipeline: "Pipeline"):
        self.pipeline = pipeline

    async def command(
        self, principal: Principal, params: dict[str, Any], *, locked: bool = False
    ) -> Decision:
        from hirz.executor.plans import governance

        p = self.pipeline
        if getattr(p, "_refresh_command", None) is not None:
            raise ValueError("Overlapping refresh commands")
        p._refresh_command = params
        try:
            action = governance(p, "refresh_plan", params, principal)
            return (
                await p.mutate_locked(action, principal)
                if locked
                else await p.redeem(action, principal)
            )
        finally:
            p._refresh_command = None

    async def request(
        self,
        plan_id: str,
        principal: Principal,
        *,
        reason: str = "Explicit change request",
        explicit: bool = True,
        retry_action_id: str | None = None,
    ) -> Decision:
        return await self.command(
            principal,
            dict(
                plan_id=plan_id,
                operation="request",
                reason=reason,
                explicit=explicit,
                retry_action_id=retry_action_id,
            ),
        )

    async def update(
        self,
        plan_id: str,
        runtime: RuntimeInputs,
        principal: Principal,
        *,
        explicit: bool = True,
    ) -> Decision:
        runtime = RuntimeInputs.model_validate(runtime.model_dump())
        return await self.command(
            principal,
            dict(
                plan_id=plan_id,
                operation="inputs",
                runtime=runtime.model_dump(mode="json"),
                reason="Supplied forecast or workload changed",
                explicit=explicit,
            ),
        )

    async def read(self, plan_id: str, principal: Principal) -> Plan:
        from hirz.executor.plans import get

        p = self.pipeline
        async with p.connection.begin():
            if (await p.requester(principal)).member_id is None:
                raise ValueError("Plan reads require a linked household member")
            original = await get(p, plan_id)
            lineage = await job(p, original)
            if lineage:
                plan_id = lineage["plan_id"]
        await self.command(principal, dict(plan_id=plan_id, operation="detect"))
        async with p.connection.begin():
            stored = await get(p, plan_id)
            current = await job(p, stored)
            narration_context = context(await p.snapshot(p.clock()))
        plan = Plan.model_validate(stored["document"])
        if current and current["state"] in {"queued", "running", "blocked"}:
            reason = (
                current["blocking_reason"]
                or "A replacement is being computed; this is a historical reference."
            )
            plan = plan.model_copy(
                update=dict(
                    status="refreshing",
                    summary=plan.summary.model_copy(
                        update=dict(estimated_savings_usd=None, peak_kwh_avoided=None)
                    ),
                    comparison_validity=plan.comparison_validity.model_copy(
                        update=dict(valid=False, reasons=(reason,))
                    ),
                    alternatives=tuple(
                        a.model_copy(
                            update=dict(
                                cost_delta_usd=None,
                                validity=a.validity.model_copy(
                                    update=dict(valid=False, reasons=(reason,))
                                ),
                            )
                        )
                        for a in plan.alternatives
                    ),
                    speakable={
                        "headline": "The plan is held for an update.",
                        "details": [
                            "Historical plan; its estimates are not current.",
                            reason,
                        ],
                        "options": ["Review"],
                    },
                )
            )
        return prepared(plan, narration_context)
