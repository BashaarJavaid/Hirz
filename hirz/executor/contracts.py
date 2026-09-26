"""The deliberately small local device command surface."""

import math
from datetime import datetime, timedelta
from typing import Any

from hirz.pipeline.hashing import action_hash, ingest
from hirz.pipeline.models import Action, ExpectedEffect, Inverse

SUPPORTED = {
    "environment.lights": ("devices", "on"),
    "energy.hvac_adjust": ("devices", "target_f"),
    "energy.ev_charge": ("ev", "charging"),
    "energy.battery_dispatch": ("energy", "dispatch_kw"),
    "energy.appliance_start": ("devices", "on"),
    "security.door_unlock": ("devices", "locked"),
}


def expired(action: Action, at: datetime) -> bool:
    return bool(
        action.expected_effect is None
        or at >= action.expected_effect.by
        or action.action_class != "security.door_unlock"
        and action.revert
        and action.scheduled_for is not None
        and at >= action.scheduled_for + timedelta(seconds=action.revert.after_s)
    )


def number(value: Any, low: float, high: float) -> bool:
    return type(value) in {int, float} and math.isfinite(value) and low <= value <= high


def parameters(name: str, params: dict[str, Any], adapter: str) -> None:
    valid = False
    if name == "environment.lights":
        valid = set(params) == {"on"} and type(params["on"]) is bool
    elif name == "energy.hvac_adjust":
        valid = (
            set(params) in ({"target_f"}, {"target_f", "mode"})
            and number(params["target_f"], 66, 76)
            and (
                "mode" not in params
                or adapter == "twin"
                and params["mode"] in {"heat", "cool", "off"}
            )
        )
    elif adapter == "twin" and name == "energy.ev_charge":
        valid = (
            set(params) in ({"charging"}, {"charging", "charge_limit"})
            and type(params["charging"]) is bool
            and (not params["charging"] or "charge_limit" in params)
            and ("charge_limit" not in params or number(params["charge_limit"], 0, 0.8))
        )
    elif adapter == "twin" and name == "energy.battery_dispatch":
        valid = set(params) == {"dispatch_kw"} and number(params["dispatch_kw"], -5, 5)
    elif adapter == "twin" and name == "energy.appliance_start":
        valid = not params
    elif adapter == "twin" and name == "security.door_unlock":
        valid = set(params) == {"locked", "open_minutes"} and (
            params["locked"] is False
            and number(params["open_minutes"], 0.01, 10)
            or params["locked"] is True
            and params["open_minutes"] == 0
        )
    if not valid:
        raise ValueError("Unsupported local execution parameters")


def validate(action: Action) -> Action:
    action = Action.model_validate(action.model_dump(by_alias=True))
    if (
        action.target.adapter not in {"ha", "twin"}
        or action.action_class not in SUPPORTED
    ):
        raise ValueError("Unsupported local device action")
    parameters(action.action_class, action.params, action.target.adapter)
    effect = action.expected_effect
    attr = SUPPORTED[action.action_class][1]
    if (
        effect is None
        or effect.entity != action.target.entity
        or effect.attr != attr
        or effect.value != action.params.get(attr, True)
        or action.scheduled_for is not None
        and effect.by <= action.scheduled_for
        or type(action.params.get(attr, True)) is bool
        and type(effect.value) is not bool
    ):
        raise ValueError("Queued work requires a consistent command-state deadline")
    bounded = (
        action.params.get("charging") is True
        or action.params.get("dispatch_kw", 0) != 0
        or action.action_class == "security.door_unlock"
        and action.params.get("locked") is False
    )
    if bounded and action.revert is None:
        raise ValueError("Nonzero EV/battery controls require a bounded stop")
    if action.revert:
        if action.scheduled_for is None:
            raise ValueError("Bounded work requires an explicit scheduled start")
        inverse = action.revert.inverse
        parameters(inverse.action_class, inverse.params, inverse.target.adapter)
        if (
            inverse.target != action.target
            or inverse.action_class != action.action_class
        ):
            raise ValueError("Ending must have the opening's class and target")
        if action.action_class == "energy.ev_charge":
            allowed = inverse.params == {"charging": False}
        elif action.action_class == "energy.battery_dispatch":
            allowed = inverse.params == {"dispatch_kw": 0}
        elif action.action_class == "security.door_unlock":
            allowed = (
                inverse.params == {"locked": True, "open_minutes": 0}
                and action.params["locked"] is False
                and action.revert.after_s
                == float(str(action.params["open_minutes"])) * 60
            )
        else:
            allowed = action.action_class in {
                "environment.lights",
                "energy.hvac_adjust",
            }
        if not allowed:
            raise ValueError("Unsupported bounded ending")
    return ingest(action)


def ending(action: Action, *, start: datetime | None = None) -> Action:
    assert action.revert and action.scheduled_for
    inverse = action.revert.inverse
    at = (
        start
        if action.action_class == "security.door_unlock" and start is not None
        else action.scheduled_for
    ) + timedelta(seconds=action.revert.after_s)
    result = action.model_copy(
        update={
            "action_id": action.action_id + ":ending",
            "action_class": inverse.action_class,
            "params": inverse.params,
            "revert": None,
            "scheduled_for": at,
            "expected_effect": ExpectedEffect(
                entity=action.target.entity,
                attr=SUPPORTED[action.action_class][1],
                value=inverse.params[SUPPORTED[action.action_class][1]],
                by=at + timedelta(seconds=10),
            ),
            "reason": "Exact preauthorized bounded ending",
        }
    )
    return validate(result.model_copy(update={"content_hash": action_hash(result)}))


def inverse(action: Action, state: dict[str, Any]) -> Inverse | None:
    if action.action_class == "security.door_unlock":
        if state.get("locked") is not True:
            raise ValueError("A bounded unlock requires a verified locked door")
        return Inverse(
            **{"class": action.action_class},
            target=action.target,
            params={"locked": True, "open_minutes": 0},
        )
    if action.action_class == "energy.appliance_start":
        return None
    keys = set(action.params)
    if not keys <= state.keys() or any(state[k] is None for k in keys):
        raise ValueError("Previous command state unavailable")
    return Inverse(
        **{"class": action.action_class},
        target=action.target,
        params={k: state[k] for k in keys},
    )
