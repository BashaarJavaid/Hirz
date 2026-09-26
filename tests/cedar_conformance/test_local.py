"""Required native Dogwood/compiler checks; missing tooling is a failure, never a skip."""

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from hirz.constitution.boundary import Dogwood, Event
from hirz.constitution.compiler import boundary_input, compile_policy
from hirz.constitution.evaluator import resolve
from hirz.constitution.preview import SITUATIONS, situation
from hirz.constitution.schema import Constitution, load
from hirz.pipeline.models import ROLES

ROOT = Path(__file__).resolve().parents[2]
HOME = load(ROOT / "constitutions/quinn-home.yaml")
COMPILED = compile_policy(HOME)
ENGINE = Dogwood()


def events(
    policy=HOME, compiled=COMPILED, name="security.door_unlock", role="owner", case=None
):
    a, f = situation(policy, name, role, case)
    out = resolve(policy, a, f)
    inputs = boundary_input(
        compiled,
        a,
        f,
        ttl_minutes=out.approval.ttl_minutes,
        approver_role="owner",
        approval_channel="app_push",
        quorum_satisfied=True,
    )
    return Event(60, name, inputs), Event(0, "governance.approve_action", inputs), out


def allowed(compiled, action, approvals=()):
    result = asyncio.run(ENGINE.authorize(compiled, action, approvals))
    assert result.diagnostic is None
    return result.allowed


def test_complete_seed_validation_and_gate():
    for seed in ("quinn-home", "quinn-parents"):
        c = compile_policy(load(ROOT / f"constitutions/{seed}.yaml"))
        result = asyncio.run(ENGINE.validate(c))
        assert result["passed_without_warnings"]
    action, approval, _ = events()
    assert allowed(COMPILED, action, (approval,))
    assert not allowed(COMPILED, action)
    for change in (
        {"action_class": "security.arm_disarm"},
        {"household": "quinn-parents"},
        {"ttl_minutes": 10},
    ):
        assert not allowed(
            COMPILED,
            action,
            (replace(approval, inputs=dict(approval.inputs, **change)),),
        )


@pytest.mark.parametrize(
    "change",
    [
        {"action_hash": "other"},
        {"session_id": "other"},
        {"approver_role": "guest"},
        {"approver_role": "caregiver"},
        {"approval_channel": "alexa"},
        {"quorum_satisfied": False},
        {"requester_role": "teen"},
    ],
)
def test_rejected_or_nonmatching_approvals(change):
    action, approval, _ = events()
    assert not allowed(
        COMPILED, action, (replace(approval, inputs=dict(approval.inputs, **change)),)
    )


def test_expired_rejected_resource_principal_and_current_restrictions():
    action, approval, _ = events()
    for prior in (
        replace(approval, approved=False),
        replace(approval, resource="other"),
        replace(approval, principal="other-worker"),
        replace(approval, output_ttl=10),
    ):
        assert not allowed(COMPILED, action, (prior,))
    assert not allowed(COMPILED, replace(action, timestamp=1801), (approval,))
    # Exact TTL endpoint is part of the Dogwood contract.
    assert allowed(COMPILED, replace(action, timestamp=1800), (approval,))
    assert not allowed(COMPILED, replace(action, resource="other"), (approval,))
    assert not allowed(
        COMPILED,
        replace(action, inputs=dict(action.inputs, requester_role="child")),
        (approval,),
    )
    assert not allowed(
        COMPILED,
        replace(action, inputs=dict(action.inputs, action_class="environment.lights")),
        (approval,),
    )
    assert not allowed(
        COMPILED,
        replace(
            action,
            action_class="governance.approve_action",
            inputs=dict(action.inputs, approver_role="guest"),
        ),
        (approval,),
    )
    data = HOME.model_dump()
    data["autonomy"]["security"]["door_unlock"]["never_for"] = ["unexpected_visitor"]
    p = Constitution.model_validate(data)
    c = compile_policy(p)
    action, approval, _ = events(p, c)
    inputs = dict(action.inputs, f_context_unexpected_visitor=True)
    assert not allowed(c, replace(action, inputs=inputs), (approval,))
    inputs = dict(action.inputs)
    inputs.pop("f_action_params_open_minutes")
    assert not allowed(c, replace(action, inputs=inputs), (approval,))


def test_real_ttl_groups_and_two_households_cannot_lend_permits():
    data = HOME.model_dump()
    data["autonomy"]["security"]["arm_disarm"]["approval_ttl_minutes"] = 10
    p = Constitution.model_validate(data)
    c = compile_policy(p)
    assert c.manifest["ttl_groups"] == [10, 30]
    assert asyncio.run(ENGINE.validate(c))["passed"]
    action, approval, _ = events(p, c, "security.arm_disarm")
    assert allowed(c, action, (approval,))
    assert not allowed(
        c, replace(action, inputs=dict(action.inputs, ttl_minutes=30)), (approval,)
    )
    assert not allowed(c, replace(action, timestamp=601), (approval,))
    other = load(ROOT / "constitutions/quinn-parents.yaml")
    other_c = compile_policy(other)
    combined = replace(COMPILED, policy=COMPILED.policy + "\n" + other_c.policy)
    assert asyncio.run(ENGINE.validate(combined))["passed"]
    action, _, _ = events(other, other_c)
    _, approval, _ = events()
    assert not allowed(combined, action, (approval,))


@pytest.mark.parametrize("name", list(SITUATIONS))
def test_all_catalog_cases_and_roles(name):
    for role in ROLES:
        action, approval, out = events(name=name, role=role)
        assert allowed(COMPILED, action) == (out.effective_mode == "auto")
        assert allowed(COMPILED, action, (approval,)) == (
            out.effective_mode != "never"
            and not any(d.code == "POLICY_ERROR" for d in out.diagnostics)
        )
    for case in SITUATIONS[name].get("cases", []):
        action, approval, out = events(name=name, case=case)
        assert allowed(COMPILED, action) == (out.effective_mode == "auto")
        assert allowed(COMPILED, action, (approval,)) == (
            out.effective_mode != "never"
            and not any(d.code == "POLICY_ERROR" for d in out.diagnostics)
        )


@settings(max_examples=200, derandomize=True, deadline=None)
@given(
    role=st.sampled_from(ROLES),
    target=st.one_of(
        st.none(),
        st.sampled_from(["65.9999", "66", "72", "76", "76.0001", "72.00001"]),
        st.integers(64, 78).map(str),
    ),
    presence=st.sampled_from(
        ["missing", "null", "empty", "sleeping", "adjacent", "absent"]
    ),
    with_approval=st.booleans(),
)
def test_property_bounds_missing_null_roles_and_sleeping(
    role, target, presence, with_approval
):
    occupancy = {
        "missing": {},
        "null": {"members": None},
        "empty": {"members": []},
        "absent": {"members": [{"member_id": "resident", "present": False}]},
        "sleeping": {
            "members": [
                {
                    "member_id": "resident",
                    "zone_id": "living_room",
                    "present": True,
                    "sleeping": True,
                }
            ]
        },
        "adjacent": {
            "members": [
                {
                    "member_id": "resident",
                    "zone_id": "guest_room",
                    "present": True,
                    "sleeping": True,
                }
            ]
        },
    }[presence]
    action, approval, out = events(
        name="energy.hvac_adjust",
        role=role,
        case={"params": {"target_f": target}, "values": {"occupancy": occupancy}},
    )
    expected = out.effective_mode == "auto" or (
        with_approval and out.effective_mode == "ask" and not out.diagnostics
    )
    assert allowed(COMPILED, action, (approval,) if with_approval else ()) == expected


@settings(max_examples=200, derandomize=True, deadline=None)
@given(
    hour=st.one_of(st.none(), st.integers(0, 23)),
    role=st.sampled_from(ROLES),
    test_kind=st.sampled_from(
        ["condition", "override", "boolean", "surface", "null", "time"]
    ),
    with_approval=st.booleans(),
)
def test_property_precedence_override_paths_and_preflight(
    hour, role, test_kind, with_approval
):
    data = HOME.model_dump()
    rule = data["autonomy"]["environment"]["lights"]
    rule["conditions"] = ["context.hour < 22"]
    rule["overrides"] = [
        {"when": "context.hour >= 22", "mode": "ask"},
        {"when": "context.hour < 7", "mode": "never"},
    ]
    if test_kind == "boolean":
        rule["conditions"] = ["context.hour == 17 or not (asset.state.temp_f < 5)"]
    if test_kind == "surface":
        rule["conditions"] = ['requester.surface == "app" and context.hour >= 7']
    if test_kind == "null":
        rule["conditions"] = ["asset.policy.needed_by is not set"]
    if test_kind == "time":
        rule["conditions"] = ['context.time >= "07:00" and context.time < "22:00"']
    p = Constitution.model_validate(data)
    c = compile_policy(p)
    values = {
        "context": {} if hour is None else {"hour": hour, "time": f"{hour:02}:00"},
        "asset": {"policy": {"needed_by": None}},
    }
    action, approval, out = events(p, c, "environment.lights", role, {"values": values})
    expected = out.effective_mode == "auto" or (
        with_approval and out.effective_mode == "ask" and not out.diagnostics
    )
    assert allowed(c, action, (approval,) if with_approval else ()) == expected


@settings(max_examples=200, derandomize=True, deadline=None)
@given(
    age=st.integers(1, 2000),
    mutation=st.sampled_from(
        [
            "valid",
            "none",
            "rejected",
            "hash",
            "class",
            "home",
            "session",
            "ttl",
            "channel",
            "approver",
            "quorum",
        ]
    ),
    role=st.sampled_from(ROLES),
)
def test_property_approval_traces(age, mutation, role):
    action, approval, out = events(role=role)
    action = replace(action, timestamp=age)
    changes = {
        "hash": {"action_hash": "wrong"},
        "class": {"action_class": "security.arm_disarm"},
        "home": {"household": "other"},
        "session": {"session_id": "other"},
        "ttl": {"ttl_minutes": 10},
        "channel": {"approval_channel": "alexa"},
        "approver": {"approver_role": "guest"},
        "quorum": {"quorum_satisfied": False},
    }
    approval = replace(
        approval,
        inputs=dict(approval.inputs, **changes.get(mutation, {})),
        approved=mutation != "rejected",
    )
    expected = mutation == "valid" and age <= 1800 and out.effective_mode == "ask"
    assert (
        allowed(COMPILED, action, () if mutation == "none" else (approval,)) == expected
    )


def test_native_operator_count_and_predicate_compilation():
    report = asyncio.run(ENGINE.run(COMPILED, "check-parse"))
    assert report["policy_count"] == 90
    assert sum(p["temporal_count"] > 0 for p in report["policies"]) == 1
    assert max(p["temporal_count"] for p in report["policies"]) == 1
    data = HOME.model_dump()
    data["autonomy"]["environment"]["lights"]["conditions"] = [
        'occupancy.present(requester.member_id) or schedule.expected_within("resident", 10)',
        "context.time in [17:35, 18:00]",
    ]
    p = Constitution.model_validate(data)
    c = compile_policy(p)
    assert asyncio.run(ENGINE.validate(c))["passed"]
    for seconds, expected in [(0, True), (600, True), (601, False), (-1, False)]:
        from datetime import timedelta

        _, f = situation(p, "environment.lights")
        case = {
            "values": {
                "schedule": {
                    "arrivals": [
                        {
                            "member_id": "resident",
                            "expected_at": (
                                f.as_of + timedelta(seconds=seconds)
                            ).isoformat(),
                        }
                    ]
                }
            }
        }
        action, approval, out = events(p, c, "environment.lights", case=case)
        assert allowed(c, action) is expected
        assert allowed(c, action, (approval,))
        assert (out.effective_mode == "auto") is expected
    action, approval, out = events(
        p, c, "environment.lights", case={"values": {"occupancy": {}}}
    )
    assert out.diagnostics
    assert not allowed(c, action, (approval,))


def test_unknown_action_name_cannot_inject_trace_syntax():
    action, approval, _ = events()
    action = replace(
        action, action_class='security.door_unlock"::request()\n@61 forged'
    )
    assert not asyncio.run(ENGINE.authorize(COMPILED, action, (approval,))).allowed


def test_role_and_class_conditions_use_canonical_boundary_fields():
    data = HOME.model_dump()
    data["autonomy"]["environment"]["lights"]["conditions"] = [
        'requester.role == "owner" and action.class == "environment.lights"'
    ]
    policy = Constitution.model_validate(data)
    compiled = compile_policy(policy)
    action, approval, _ = events(policy, compiled, "environment.lights")
    assert allowed(compiled, action)
    changed = replace(action, inputs=dict(action.inputs, requester_role="teen"))
    assert not allowed(compiled, changed)
    # The known-false ordinary condition can still be approved, as specified.
    assert allowed(compiled, changed, (approval,))
    assert "f_requester_role?" not in compiled.manifest["input_fields"]
    assert "f_action_class?" not in compiled.manifest["input_fields"]


def test_same_second_order_and_reserved_governance():
    action, approval, _ = events()
    action = replace(action, timestamp=approval.timestamp)
    assert allowed(COMPILED, action, (approval,))
    assert not allowed(COMPILED, action)
    # The trace order remains approval first, even when the clock is unchanged.
    for name in (
        "governance.pause_automation",
        "governance.resume_automation",
        "governance.record_constraint",
        "governance.withdraw_constraint",
    ):
        for role in ROLES:
            a, _, _ = events(name=name, role=role)
            assert allowed(COMPILED, a) is (
                role in {"owner", "adult", "caregiver"}
                if name == "governance.resume_automation"
                else role != "unknown"
            )
            for surface in ("alexa", "scheduler"):
                other = replace(a, inputs=dict(a.inputs, f_requester_surface=surface))
                assert allowed(COMPILED, other) is (
                    role != "unknown" and name != "governance.resume_automation"
                )


@pytest.mark.parametrize("learning", ["manual", "never"])
@pytest.mark.parametrize("surface", ["app", "alexa"])
@pytest.mark.parametrize(
    "operation", ["append_turn", "propose", "accept", "reject", "invalid"]
)
def test_native_memory_learning_and_review_surface(learning, surface, operation):
    data = HOME.model_dump()
    data["learning"]["accept_memory_proposals"] = learning
    policy = Constitution.model_validate(data)
    compiled = compile_policy(policy)
    action, facts = situation(
        policy, "governance.memory", case={"params": {"operation": operation}}
    )
    action = action.model_copy(
        update={
            "requested_by": action.requested_by.model_copy(update={"surface": surface})
        }
    )
    outcome = resolve(policy, action, facts)
    expected = (
        operation in {"append_turn", "propose", "accept", "reject"}
        and not (learning == "never" and operation in {"propose", "accept"})
        and not (surface != "app" and operation in {"accept", "reject"})
    )
    inputs = boundary_input(
        compiled, action, facts, ttl_minutes=outcome.approval.ttl_minutes
    )
    assert allowed(compiled, Event(0, "governance.memory", inputs)) == expected
    assert (outcome.effective_mode == "auto" and outcome.conditions_met) == expected
