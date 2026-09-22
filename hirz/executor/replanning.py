"""Rebuild the outstanding workload from configured facts and immutable endings."""

from datetime import datetime
from typing import Any
from uuid import UUID

from hirz.executor.contracts import ending
from hirz.executor.runtime import RuntimeInputs, slice_input
from hirz.graph.context import ContextSnapshot
from hirz.pipeline.hashing import action_hash, digest
from hirz.pipeline.models import Action, Plan, Requester, Target
from hirz.planner.models import PlannerInput, PlannerResult, split_at
from hirz.twin.physics import changed
from hirz.twin.world import State


def operation(action: Action) -> str:
    return digest([action.action_class, action.target.model_dump(), action.params])


def outstanding(
    runtime: RuntimeInputs,
    snapshot: ContextSnapshot,
    requester: Requester,
    actions: tuple[dict[str, Any], ...],
    state: State | None,
    ha: dict[str, dict[str, Any]],
) -> tuple[PlannerInput, dict[str, Any], tuple[str, ...]]:
    at = snapshot.as_of
    p = slice_input(runtime.workload, at, runtime.workload.slots[-1].end)
    data: Any = snapshot.data
    bindings = {b["entity_id"]: b for b in data["asset_bindings"]}
    observations = {
        str(o["asset_id"]): o for o in data["observations"] if o.get("asset_id")
    }
    committed: dict[str, datetime] = {}
    exhausted = set(runtime.exhausted)
    by_id = {a["action_id"]: a for a in actions}
    for stored in actions:
        a = Action.model_validate(stored["proposal"])
        life = stored["lifecycle"] or {}
        if life.get("ending_of"):
            continue
        if (
            stored["execution_status"] == "failed"
            and stored["action_id"] not in runtime.retry_actions
        ):
            retry = next(
                (
                    r
                    for r in actions
                    if (r["lifecycle"] or {}).get("retry_of") == a.action_id
                ),
                None,
            )
            if retry is None or retry["execution_status"] != "verified":
                exhausted.add(operation(a))
        if a.revert and stored["execution_attempt_seq"] is not None:
            end = ending(a)
            ending_row = by_id.get(end.action_id)
            if ending_row is None or ending_row["execution_status"] != "verified":
                if end.scheduled_for is None or end.scheduled_for <= at:
                    raise ValueError("An authorized ending is still unverified.")
                committed[a.target.entity] = end.scheduled_for
                if stored["execution_status"] != "verified":
                    raise ValueError(
                        "An uncertain dispatch retains its commitment and reservation."
                    )
    # Split exactly at existing endings; no replacement can extend or shorten one.
    p = split_at(p, tuple(committed.values()))

    def facts(entity: str) -> tuple[dict[str, Any], dict[str, Any]]:
        binding = bindings.get(entity)
        if binding is None:
            raise ValueError("A required workload device has no configured binding.")
        obs = observations.get(str(binding["asset_id"]))
        if (
            obs is None
            or not 0
            <= (at - datetime.fromisoformat(obs["observed_at"])).total_seconds()
            <= 300
            or obs["state"].get("available") is False
        ):
            raise ValueError(
                "A required device is unavailable or stale; actual state is unknown."
            )
        if binding["adapter"] not in {"ha", "twin"}:
            raise ValueError("The required adapter is not supported for local refresh.")
        return binding, obs["state"]

    zones = []
    for z in p.zones:
        binding, obs = facts(z.entity)
        if (
            obs.get("temp_f") is None
            or obs.get("target_f") is None
            or obs.get("mode") is None
        ):
            raise ValueError(
                "A thermostat lacks current temperature, target or supported mode."
            )
        physical = changed(
            z.physical, **{k: obs[k] for k in ("temp_f", "target_f", "mode")}
        )
        updates: dict[str, Any] = dict(
            physical=physical,
            asset_id=UUID(str(binding["asset_id"])),
            held_targets=(),
            held_modes=(),
            preferences=(),
        )
        if binding["adapter"] == "ha":
            device = ha.get(z.entity)
            if not device or device["mode"] not in {"heat", "cool"}:
                raise ValueError(
                    "The HA thermostat needs a supported observed heat or cool mode."
                )
            updates.update(
                control_mode=device["mode"],
                setpoint_step_f=device["step"],
                setpoint_origin_f=device["origin"],
                setpoint_lower_f=max(
                    z.setpoint_lower_f if z.setpoint_lower_f is not None else 66,
                    device["low"],
                ),
                setpoint_upper_f=min(
                    z.setpoint_upper_f if z.setpoint_upper_f is not None else 76,
                    device["high"],
                ),
            )
        if z.entity in committed:
            updates.update(
                held_targets=tuple(
                    physical.target_f if s.start < committed[z.entity] else None
                    for s in p.slots
                ),
                held_modes=tuple(
                    physical.mode if s.start < committed[z.entity] else None
                    for s in p.slots
                ),
            )
        zones.append(z.model_copy(update=updates))
    ev = p.ev
    if ev:
        binding, obs = facts("ev")
        if (
            binding["adapter"] != "twin"
            or obs.get("soc") is None
            or obs.get("plugged_in") is not True
        ):
            raise ValueError("The required EV state is unavailable.")
        ev = changed(
            ev,
            soc=state.evs[UUID(str(binding["asset_id"]))].soc
            if state and UUID(str(binding["asset_id"])) in state.evs
            else obs["soc"],
            plugged_in=True,
            charging=bool(obs.get("charging")),
            charge_limit=obs.get("charge_limit")
            if obs.get("charge_limit") is not None
            else ev.charge_limit,
        )
    battery = p.battery
    if battery:
        binding, obs = facts("home_battery")
        if (
            binding["adapter"] != "twin"
            or obs.get("soc") is None
            or obs.get("dispatch_kw") is None
        ):
            raise ValueError("The required battery state is unavailable.")
        battery = changed(
            battery,
            soc=state.batteries[UUID(str(binding["asset_id"]))].soc
            if state and UUID(str(binding["asset_id"])) in state.batteries
            else obs["soc"],
            dispatch_kw=obs["dispatch_kw"],
        )
    appliance = p.appliance
    if appliance:
        binding, obs = facts("dishwasher")
        asset_id = UUID(str(binding["asset_id"]))
        if (
            binding["adapter"] != "twin"
            or state is None
            or asset_id not in state.appliances
        ):
            raise ValueError("The appliance's remaining cycle is unknown.")
        appliance = state.appliances[asset_id]
        if appliance.completions >= (runtime.appliance_completions or 0):
            appliance = None
    fixed_ev: list[float | None] = []
    fixed_battery = []
    predicted_ev = ev
    for slot in p.slots:
        if predicted_ev and slot.start < committed.get("ev", at):
            after = predicted_ev.advance(slot.hours * 3600)
            fixed_ev.append(after.grid_kwh - predicted_ev.grid_kwh)
            predicted_ev = after
        else:
            fixed_ev.append(None)
        fixed_battery.append(
            battery.dispatch_kw
            if battery and slot.start < committed.get("home_battery", at)
            else None
        )
    # Supplied installed physics is retained; only observations update physical state.
    p = p.model_copy(
        update=dict(
            requester=requester,
            zones=tuple(zones),
            ev=ev,
            battery=battery,
            appliance=appliance,
            appliance_completed=bool(
                runtime.appliance_completions is not None and appliance is None
            ),
            constraints=(),
            battery_terminal_kwh=runtime.battery_terminal_kwh,
            fixed_ev_kwh=tuple(fixed_ev),
            fixed_battery_kw=tuple(fixed_battery),
            causal_controls=False,
            actuator_precision=True,
        )
    )
    return (
        PlannerInput.model_validate(p.model_dump()),
        bindings,
        tuple(sorted(exhausted)),
    )


def bind_result(
    result: PlannerResult,
    inputs: PlannerInput,
    previous: Plan,
    bindings: dict[str, Any],
    exhausted: tuple[str, ...],
) -> PlannerResult:
    if result.plan is None:
        return result
    actions = []
    for a in result.actions:
        binding = bindings[a.target.entity]
        if a.scheduled_for is not None:
            i = next(
                (
                    i
                    for i, s in enumerate(inputs.slots)
                    if s.start <= a.scheduled_for < s.end
                ),
                None,
            )
            if i is not None and (
                (
                    a.action_class == "energy.ev_charge"
                    and inputs.fixed_ev_kwh
                    and inputs.fixed_ev_kwh[i] is not None
                )
                or (
                    a.action_class == "energy.battery_dispatch"
                    and inputs.fixed_battery_kw
                    and inputs.fixed_battery_kw[i] is not None
                )
            ):
                continue
        target = Target(
            adapter=binding["adapter"],
            entity=binding["entity_id"],
            zone=str(binding["asset_id"])
            if a.action_class == "energy.hvac_adjust"
            else None,
        )
        params = (
            {"target_f": a.params["target_f"]}
            if binding["adapter"] == "ha"
            else a.params
        )
        a = a.model_copy(
            update=dict(
                target=target,
                params=params,
                expected_effect=a.expected_effect.model_copy(
                    update={"entity": target.entity}
                )
                if a.expected_effect
                else None,
                revert=a.revert.model_copy(
                    update={
                        "inverse": a.revert.inverse.model_copy(
                            update={"target": target}
                        )
                    }
                )
                if a.revert
                else None,
            )
        )
        if operation(a) in exhausted:
            raise ValueError(
                "A device operation exhausted its retry; an explicit member retry is required."
            )
        actions.append(a.model_copy(update={"content_hash": action_hash(a)}))
    plan = result.plan.model_copy(
        update=dict(
            actions=tuple(a.action_id for a in actions),
            goals=previous.goals,
            explain=result.plan.explain.model_copy(
                update={
                    "facts": (
                        *result.plan.explain.facts,
                        "Estimates and comparisons cover the remaining approved horizon only.",
                    )
                }
            ),
            speakable={
                "headline": "The updated plan is ready for review.",
                "details": ["Estimates cover the remaining horizon."],
                "options": ["Review"],
            },
        )
    )
    return result.model_copy(update=dict(plan=plan, actions=tuple(actions)))
