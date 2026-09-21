"""Proposal construction, validated fallback and explicit infeasibility evidence."""

from time import perf_counter
from typing import Literal

from hirz.adapters.energy.real.tariff import CHICAGO
from hirz.pipeline.hashing import action_hash, digest
from hirz.pipeline.models import (
    Action,
    ComparisonValidity,
    Explanation,
    Plan,
    PlanAlternative,
    PlanHorizon,
    PlanSummary,
    Target,
)
from hirz.planner.feedback import forecast_replay
from hirz.planner.heuristic import baseline
from hirz.planner.models import (
    PlannerInput,
    PlannerResult,
    Replay,
    Schedule,
    SolverDiagnostics,
)
from hirz.planner.solver import solve


def peak(p: PlannerInput, r: Replay) -> float:
    return sum(
        energy
        for slot, energy in zip(p.slots, r.grid_kwh, strict=True)
        if 13 <= slot.start.astimezone(CHICAGO).hour < 19
    )


def compare(a: Replay, b: Replay) -> tuple[ComparisonValidity, float | None]:
    reasons = tuple(dict.fromkeys((*a.reasons, *b.reasons)))
    if abs(a.ev_delivered_kwh - b.ev_delivered_kwh) > 1e-6:
        reasons += ("Unequal EV delivery between strategies",)
    if (
        a.battery_end_kwh is not None
        and b.battery_end_kwh is not None
        and abs(a.battery_end_kwh - b.battery_end_kwh) > 1e-6
    ):
        reasons += ("Unequal ending battery energy between strategies",)
    valid = a.valid and b.valid and not reasons
    return ComparisonValidity(valid=valid, reasons=reasons), (
        b.electricity_usd + b.wear_usd - a.electricity_usd - a.wear_usd
        if valid
        else None
    )


def actions(p: PlannerInput, schedule: Schedule, plan_id: str) -> tuple[Action, ...]:
    result = []
    ev_soc = p.ev.soc if p.ev else 0.0
    last: dict[str, dict[str, object]] = {}
    for i, (slot, control) in enumerate(zip(p.slots, schedule.controls, strict=True)):
        changes: list[tuple[str, str, dict[str, object]]] = []
        if p.ev:
            ev_soc += control.ev_kwh * p.ev.efficiency / p.ev.capacity_kwh
            changes.append(
                (
                    "energy.ev_charge",
                    "ev",
                    {
                        "charging": control.ev_kwh > 1e-9,
                        "charge_limit": min(0.8, ev_soc),
                    },
                )
            )
        if p.battery:
            changes.append(
                (
                    "energy.battery_dispatch",
                    "home_battery",
                    {"dispatch_kw": control.battery_kw},
                )
            )
        changes += [
            ("energy.hvac_adjust", z.entity, {"target_f": t, "mode": mode})
            for z, t, mode in zip(p.zones, control.targets, control.modes, strict=True)
        ]
        if control.appliance_start:
            changes.append(("energy.appliance_start", "dishwasher", {}))
        for cls, entity, params in changes:
            if last.get(entity) == params:
                continue
            last[entity] = params
            action = Action.model_validate(
                dict(
                    action_id="act_"
                    + digest([str(p.household_id), plan_id, i, entity]),
                    **{"class": cls},
                    target=Target(adapter="twin", entity=entity),
                    params=params,
                    requested_by=p.requester,
                    reason="Read-only simulated energy proposal; requires pipeline authorization",
                    plan_id=plan_id,
                    scheduled_for=slot.start,
                    content_hash="",
                )
            )
            result.append(
                action.model_copy(update={"content_hash": action_hash(action)})
            )
    # End bounded controls explicitly; a schedule cannot leave dispatch running.
    end_changes: list[tuple[str, str, dict[str, object]]] = [
        ("energy.ev_charge", "ev", {"charging": False}),
        ("energy.battery_dispatch", "home_battery", {"dispatch_kw": 0.0}),
    ]
    for cls, entity, params in end_changes:
        if entity not in last:
            continue
        action = Action.model_validate(
            dict(
                action_id="act_"
                + digest([str(p.household_id), plan_id, "end", entity]),
                **{"class": cls},
                target=Target(adapter="twin", entity=entity),
                params=params,
                requested_by=p.requester,
                reason="End hypothetical schedule",
                plan_id=plan_id,
                scheduled_for=p.slots[-1].end,
                content_hash="",
            )
        )
        result.append(action.model_copy(update={"content_hash": action_hash(action)}))
    return tuple(result)


def plan(
    p: PlannerInput, *, previous: Plan | None = None, cold_start: bool = False
) -> PlannerResult:
    # Revalidate even models made through model_copy: no trusted construction bypass.
    p = PlannerInput.model_validate(p.model_dump())
    if previous is not None and previous.household_id != p.household_id:
        raise ValueError("Previous plan belongs to another household")
    input_hash = digest(p.model_dump(mode="json"))
    began = perf_counter()
    schedule: Schedule | None
    if cold_start:
        schedule = baseline(p)
        diagnostics = SolverDiagnostics(
            status="cold_start", elapsed_seconds=perf_counter() - began
        )
    else:
        schedule, diagnostics = solve(p)
        if schedule is None and diagnostics.status == "timeout":
            schedule = baseline(p)
    checked = forecast_replay(p, schedule) if schedule is not None else None
    if schedule is None or checked is None or not checked.valid:
        blocking = []
        if diagnostics.status == "infeasible":
            for c in sorted(
                p.constraints, key=lambda c: c.provenance.recorded_at, reverse=True
            ):
                candidate = p.model_copy(
                    update={"constraints": tuple(x for x in p.constraints if x != c)}
                )
                replacement, _ = solve(candidate)
                if (
                    replacement is not None
                    and forecast_replay(candidate, replacement).valid
                ):
                    blocking.append(c.provenance)
        return PlannerResult(
            plan=None,
            schedule=None,
            replay=checked,
            diagnostics=diagnostics,
            blocking_constraints=tuple(blocking),
            unresolved_conflict=diagnostics.status == "infeasible" and not blocking,
            previous_feasible_reference=previous,
            reference_label="Previous proposal only; not valid under replacement constraints"
            if previous
            else None,
            input_hash=input_hash,
            provenance=p.provenance,
        )
    baselines = {
        name: forecast_replay(p, baseline(p, name))
        for name in ("timer", "immediate", "greedy")
    }
    alternatives = []
    for name, other in baselines.items():
        validity, delta = compare(checked, other)
        alternatives.append(
            PlanAlternative.model_validate(
                dict(
                    label=name,
                    cost_delta_usd=delta,
                    validity=validity,
                    why_rejected="Same EV deadline, comfort bands, appliance workload and ending battery energy"
                    if validity.valid
                    else "; ".join(validity.reasons),
                )
            )
        )
    validity, saving = compare(checked, baselines["timer"])
    plan_id = "plan_" + digest(
        [
            input_hash,
            schedule.model_dump(mode="json"),
            previous.plan_id if previous else None,
        ]
    )
    proposed = actions(p, schedule, plan_id)
    method: Literal["milp", "timeout_incumbent", "greedy"] = (
        "greedy"
        if schedule.method == "greedy"
        else "timeout_incumbent"
        if schedule.method == "timeout_incumbent"
        else "milp"
    )
    proposal = Plan(
        plan_id=plan_id,
        household_id=p.household_id,
        version=previous.version + 1 if previous else 1,
        supersedes=previous.plan_id if previous else None,
        horizon=PlanHorizon(start=p.slots[0].start, end=p.slots[-1].end),
        goals=("minimize_cost_and_wear", "comfort", "ev_deadline"),
        constraints=tuple(c.provenance for c in p.constraints),
        actions=tuple(a.action_id for a in proposed),
        summary=PlanSummary(
            estimated_savings_usd=saving,
            peak_kwh_avoided=peak(p, baselines["timer"]) - peak(p, checked)
            if validity.valid
            else None,
            grid_kwh=sum(checked.grid_kwh),
            solar_kwh=sum(s.solar_kw * s.hours for s in p.slots),
            exported_kwh=sum(checked.export_kwh),
            electricity_usd=checked.electricity_usd,
            wear_usd=checked.wear_usd,
            comfort_violations_minutes=checked.comfort_violations_minutes,
        ),
        alternatives=tuple(alternatives),
        explain=Explanation(
            facts=(
                "Simulated devices; supply plus distribution; zero export credit",
                *diagnostics.binding,
            )
        ),
        speakable={
            "headline": "A simulated energy plan is ready for review.",
            "details": [],
            "options": ["Review"],
        },
        method=method,
        optimality_gap=diagnostics.gap,
        comparison_validity=validity,
    )
    return PlannerResult(
        plan=proposal,
        actions=proposed,
        schedule=schedule,
        replay=checked,
        baselines=baselines,
        diagnostics=diagnostics,
        input_hash=input_hash,
        provenance=p.provenance,
    )
