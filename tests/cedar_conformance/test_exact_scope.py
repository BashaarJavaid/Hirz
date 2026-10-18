"""Exact action scopes retain approval semantics and aggregate publication limits."""

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from hirz.aws.policy import inventory, quota
from hirz.constitution.boundary import Dogwood, Event
from hirz.constitution.compiler import action_name, boundary_input, compile_policy
from hirz.constitution.preview import situation
from hirz.constitution.schema import Constitution, load


def result(policy, name, *, role="owner", case=None, approval=False):
    compiled = compile_policy(policy)
    action, facts = situation(policy, name, role, case)
    inputs = boundary_input(
        compiled,
        action,
        facts,
        ttl_minutes=30,
        approver_role="owner",
        approval_channel="app_push",
        quorum_satisfied=True,
    )
    prior = Event(0, "governance.approve_action", inputs)
    decision = asyncio.run(
        Dogwood().authorize(
            compiled,
            Event(60, name, inputs),
            (prior,) if approval else (),
        )
    )
    assert decision.diagnostic is None
    return decision.allowed


@pytest.mark.parametrize("change", ["role", "condition", "override"])
def test_auto_class_gains_temporal_policy_when_it_can_require_approval(change):
    data = load(Path("constitutions/quinn-home.yaml")).model_dump()
    rule = data["autonomy"]["energy"]["battery_dispatch"]
    if change == "role":
        data["per_role"]["teen"]["energy.battery_dispatch"] = {"mode": "ask"}
    elif change == "condition":
        rule["conditions"] = ["context.hour < 0"]
    else:
        rule["overrides"] = [{"when": "context.hour >= 0", "mode": "ask"}]
    policy = Constitution.model_validate(data)
    compiled = compile_policy(policy)
    assert compiled.manifest["temporal_policies"] == 8
    assert not result(policy, "energy.battery_dispatch", role="teen")
    assert result(policy, "energy.battery_dispatch", role="teen", approval=True)


def test_removing_redundant_temporal_permit_keeps_current_hard_bounds():
    data = load(Path("constitutions/quinn-home.yaml")).model_dump()
    data["autonomy"]["energy"]["hvac_adjust"].update(conditions=[], overrides=[])
    data["per_role"]["teen"]["energy.hvac_adjust"] = {"mode": "auto"}
    policy = Constitution.model_validate(data)
    compiled = compile_policy(policy)
    assert compiled.manifest["temporal_policies"] == 6
    assert not any(
        s.temporal and action_name("energy.hvac_adjust") in s.text
        for s in compiled.statements
    )
    for value, expected in [(72, True), (65, False), (77, False), (None, False)]:
        for approval in (False, True):
            assert (
                result(
                    policy,
                    "energy.hvac_adjust",
                    case={"params": {"target_f": value}},
                    approval=approval,
                )
                is expected
            )


def test_temporal_names_survive_ttl_changes_and_shared_quota_is_enforced():
    home = load(Path("constitutions/quinn-home.yaml"))
    parents = load(Path("constitutions/quinn-parents.yaml"))
    original = compile_policy(home, engine="agentcore-policy")
    data = home.model_dump()
    data["autonomy"]["security"]["door_unlock"]["approval_ttl_minutes"] = 10
    changed = compile_policy(
        Constitution.model_validate(data), engine="agentcore-policy"
    )
    assert {s.name for s in original.statements} == {s.name for s in changed.statements}
    assert changed.manifest["ttl_groups"] == [10, 30]
    quota(inventory([changed]), inventory([original]))

    def expand(policy, count):
        data = policy.model_dump()
        data["per_role"]["guest"]["environment.lights"] = {"mode": "ask"}
        for name in ("lights", "shades", "comfort_profile")[:count]:
            data["autonomy"]["environment"][name]["mode"] = "ask"
        if count == 4:
            data["autonomy"]["health"]["routine_reminders"]["mode"] = "ask"
        return compile_policy(
            Constitution.model_validate(data), engine="agentcore-policy"
        )

    full = inventory([expand(home, 3), expand(parents, 3)])
    assert sum("when temporal" in s for s in full.values()) == 20
    with pytest.raises(ValueError, match="headroom"):
        inventory([expand(home, 3), expand(parents, 4)])
    with pytest.raises(ValueError, match="headroom"):
        quota(full, {"retiring_ttl_group": "when temporal"})


def test_exact_scope_cannot_authorize_a_schema_descendant():
    policy = load(Path("constitutions/quinn-home.yaml"))
    compiled = compile_policy(policy)
    schema = (
        compiled.schema[:-1]
        + """
action "HirzActions___unexpected_child" in [Action::"HirzActions___security_door_unlock"] appliesTo {
  principal: [Worker], resource: [Gateway], context: { input: Input }
};
}"""
    )
    compiled = replace(compiled, schema=schema)
    assert asyncio.run(Dogwood().validate(compiled))["passed_without_warnings"]
    action, facts = situation(policy, "security.door_unlock", "owner")
    inputs = boundary_input(compiled, action, facts, ttl_minutes=30)
    approval = Event(0, "governance.approve_action", inputs)
    child = Event(60, "unexpected.child", inputs)
    decisions = asyncio.run(
        Dogwood().replay(compiled, approval.line("response") + "\n" + child.line())
    )
    assert decisions[-1]["verdict"] == "deny"
