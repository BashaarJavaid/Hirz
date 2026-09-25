"""Item 8 scoring and floors only; no runtime enforcement or execution claims."""

from copy import deepcopy
from itertools import product
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from hirz.constitution.evaluator import resolve
from hirz.constitution.preview import situation
from hirz.constitution.schema import Constitution, Rule, load
from hirz.pipeline.models import Action
from hirz.risk import CLASSES, RiskBand, floor_outcome, load_catalog
from hirz.risk.engine import RiskFacts, score

ROOT = Path(__file__).resolve().parents[2]
BASES = {
    "low": "energy.optimize_cost energy.hvac_adjust energy.ev_charge energy.battery_dispatch "
    "environment.lights environment.comfort_profile environment.shades "
    "health.routine_reminders health.comfort_preferences communication.notify_member "
    "communication.contact_trusted_contact finance.verify_request governance.pause_automation governance.resume_automation governance.record_constraint governance.withdraw_constraint governance.record_plan governance.approve_plan governance.revise_plan governance.cancel_plan governance.record_observations governance.refresh_plan governance.memory governance.record_tool_request governance.propose_rule governance.request_plan governance.record_verification",
    "medium": "energy.appliance_start",
    "high": "communication.contact_emergency_services security.door_unlock "
    "security.camera_disable security.arm_disarm",
    "critical": "health.medical_decisions security.access_code_share "
    "finance.transfer_money finance.change_payee",
}


def action(name="energy.ev_charge", role="owner", **params):
    return Action(
        action_id="risk-example",
        action_class=name,
        target={"adapter": "devices", "entity": "example", "zone": "bedroom"},
        params={"target_f": 72} | params,
        requested_by={"member_id": "member", "role": role, "surface": "app"},
        reason="Risk test only",
        content_hash="not-an-approval",
    )


def facts(**changes):
    return {
        "observation_ages_seconds": (),
        "sleeping_in_target_zone": False,
        "sleeping_any": False,
        "target_is_bedroom": False,
        "guest_present": False,
        "doorbell_online": True,
        "baseline_target_f": 72,
        "scam_pattern": False,
    } | changes


def names(result):
    return [f.factor for f in result.factors]


@pytest.mark.parametrize("base,classes", BASES.items())
def test_static_profiles(base, classes):
    assert set(CLASSES) == {n for group in BASES.values() for n in group.split()}
    for name in classes.split():
        result = score(action(name), facts(), Rule(mode="ask"))
        assert result.band == result.base_band == base
        assert result.factors == ()
        assert CLASSES[name]["freshness_seconds"] == (
            60 if name.startswith("security.") else 300
        )


@pytest.mark.parametrize(
    "band,floor",
    [("low", "none"), ("medium", "none"), ("high", "ask"), ("critical", "never_auto")],
)
def test_floors(band, floor):
    assert floor_outcome(RiskBand(band)) == floor


@pytest.mark.parametrize("name", CLASSES)
@pytest.mark.parametrize(
    "factor,changes,applicable",
    [
        (
            "occupant_asleep",
            {
                "sleeping_in_target_zone": True,
                "sleeping_any": True,
                "target_is_bedroom": True,
            },
            {"energy.hvac_adjust", "energy.appliance_start", "environment.lights"},
        ),
        (
            "guest_present",
            {"guest_present": True},
            {
                "security.door_unlock",
                "security.camera_disable",
                "security.access_code_share",
            },
        ),
        ("deviation_from_baseline", {"baseline_target_f": 65}, {"energy.hvac_adjust"}),
        (
            "scam_pattern",
            {"scam_pattern": True},
            {
                "finance.transfer_money",
                "finance.change_payee",
                "security.access_code_share",
                "finance.verify_request",
            },
        ),
        ("state_stale", {"observation_ages_seconds": (301, 302, 302)}, set(CLASSES)),
    ],
)
def test_factor_applicability(name, factor, changes, applicable):
    result = score(action(name), facts(**changes), Rule(mode="ask"))
    assert names(result) == ([factor] if name in applicable else [])
    if name in applicable:
        expected = (
            "critical"
            if factor == "scam_pattern"
            else tuple(RiskBand)[min(tuple(RiskBand).index(result.base_band) + 1, 3)]
        )
        assert result.band == expected


@pytest.mark.parametrize("name", CLASSES)
def test_unknown_requester_every_class(name):
    result = score(action(name, "unknown"), facts(), Rule(mode="ask"))
    assert names(result) == ["unknown_requester"]
    assert (
        result.band
        == tuple(RiskBand)[min(tuple(RiskBand).index(result.base_band) + 1, 3)]
    )


def test_requester_is_resolved_role_not_member_or_claim():
    a = action()
    a = a.model_copy(
        update={
            "requested_by": a.requested_by.model_copy(
                update={
                    "member_id": None,
                    "surface": "scheduler",
                    "speaker": "unknown",
                    "claimed_author": "unknown",
                }
            )
        }
    )
    assert score(a, {"observation_ages_seconds": ()}, Rule(mode="auto")).band == "low"


@pytest.mark.parametrize(
    "name,changes,expected",
    [
        ("energy.hvac_adjust", {"sleeping_any": True}, False),
        ("energy.hvac_adjust", {"sleeping_in_target_zone": True}, True),
        ("energy.appliance_start", {"sleeping_in_target_zone": True}, False),
        ("energy.appliance_start", {"sleeping_any": True}, True),
        (
            "environment.lights",
            {"sleeping_any": True, "target_is_bedroom": True},
            False,
        ),
        ("environment.lights", {"sleeping_in_target_zone": True}, False),
        (
            "environment.lights",
            {"sleeping_in_target_zone": True, "target_is_bedroom": True},
            True,
        ),
    ],
)
def test_sleep_scope(name, changes, expected):
    assert (
        "occupant_asleep"
        in names(score(action(name), facts(**changes), Rule(mode="ask")))
    ) == expected


@pytest.mark.parametrize("name", CLASSES)
def test_freshness_exact_boundary(name):
    threshold = CLASSES[name]["freshness_seconds"]
    for age, expected in ((0, False), (threshold, False), (threshold + 0.0001, True)):
        result = score(
            action(name), facts(observation_ages_seconds=(age,)), Rule(mode="ask")
        )
        assert ("state_stale" in names(result)) == expected


def test_doorbell_offline_deduplicates_stale():
    result = score(
        action("security.door_unlock"),
        facts(
            observation_ages_seconds=(61, 61),
            doorbell_online=False,
        ),
        Rule(mode="ask"),
    )
    assert names(result) == ["state_stale"]
    assert "offline" in result.factors[0].evidence
    assert "61" in result.factors[0].evidence
    assert names(
        score(
            action("security.door_unlock"),
            facts(doorbell_online=False),
            Rule(mode="ask"),
        )
    ) == ["state_stale"]
    assert not score(
        action("security.camera_disable"),
        facts(doorbell_online=False),
        Rule(mode="ask"),
    ).factors


@pytest.mark.parametrize(
    "target,expected", [(66, False), (78, False), ("65.9999", True), ("78.0001", True)]
)
def test_deviation_exact_boundary(target, expected):
    result = score(
        action("energy.hvac_adjust", target_f=target), facts(), Rule(mode="ask")
    )
    assert ("deviation_from_baseline" in names(result)) == expected


@pytest.mark.parametrize(
    "name,rule,param,equal,outside",
    [
        ("energy.hvac_adjust", {"bounds": {"min_f": 66}}, "target_f", 66, "65.9999"),
        ("energy.hvac_adjust", {"bounds": {"max_f": 76}}, "target_f", 76, "76.0001"),
        (
            "energy.ev_charge",
            {"bounds": {"ev_soc_floor": "0.3"}},
            "ev_soc_floor",
            "0.3",
            "0.2999",
        ),
        (
            "security.door_unlock",
            {"max_open_minutes": 10},
            "open_minutes",
            10,
            "10.0001",
        ),
        ("security.camera_disable", {"max_minutes": 15}, "minutes", 15, "15.0001"),
    ],
)
def test_bounds_preserve_hard_denial(name, rule, param, equal, outside):
    policy = load(ROOT / "constitutions/quinn-home.yaml")
    data = policy.model_dump()
    domain, short_name = name.split(".")
    data["autonomy"][domain][short_name].update(rule)
    policy = Constitution.model_validate(data)
    for value, violated in ((equal, False), (outside, True)):
        a, policy_facts = situation(policy, name, case={"params": {param: value}})
        result = score(
            a,
            facts(baseline_target_f=value if param == "target_f" else 72),
            Rule(mode="ask", **rule),
        )
        assert ("outside_bounds" in names(result)) == violated
        if violated:
            outcome = resolve(policy, a, policy_facts)
            assert outcome.effective_mode == "never"
            assert "DENY_BOUNDS" in [d.code for d in outcome.diagnostics]


@pytest.mark.parametrize("enabled", list(product((False, True), repeat=5)))
def test_all_hvac_factor_combinations_cap_and_keep_evidence(enabled):
    unknown, sleeping, stale, deviation, outside = enabled
    a = action(
        "energy.hvac_adjust",
        "unknown" if unknown else "owner",
        target_f=80 if outside else 72,
    )
    inputs = facts(
        sleeping_in_target_zone=sleeping,
        observation_ages_seconds=(301, 301) if stale else (),
        baseline_target_f=a.params["target_f"] - (7 if deviation else 0),
    )
    result = score(a, inputs, Rule(mode="auto", bounds={"max_f": 76}))
    assert names(result) == [
        name
        for name, active in zip(
            [
                "unknown_requester",
                "occupant_asleep",
                "state_stale",
                "deviation_from_baseline",
                "outside_bounds",
            ],
            enabled,
        )
        if active
    ]
    assert result.band == tuple(RiskBand)[min(sum(enabled), 3)]


def test_forced_critical_keeps_later_bounds():
    result = score(
        action("finance.verify_request", "unknown", minutes=2),
        facts(
            scam_pattern=True,
            observation_ages_seconds=(301,),
        ),
        Rule(mode="auto", max_minutes=1),
    )
    assert result.band == "critical" and result.base_band == "low"
    assert names(result) == [
        "unknown_requester",
        "state_stale",
        "scam_pattern",
        "outside_bounds",
    ]


@pytest.mark.parametrize(
    "name,field,changes",
    [
        ("energy.ev_charge", "observation_ages_seconds", {}),
        ("energy.hvac_adjust", "sleeping_in_target_zone", {}),
        ("energy.appliance_start", "sleeping_any", {}),
        ("environment.lights", "target_is_bedroom", {}),
        ("environment.lights", "sleeping_in_target_zone", {"target_is_bedroom": True}),
        ("security.door_unlock", "guest_present", {}),
        ("security.door_unlock", "doorbell_online", {}),
        ("security.camera_disable", "guest_present", {}),
        ("security.access_code_share", "scam_pattern", {}),
        ("finance.transfer_money", "scam_pattern", {}),
        ("finance.change_payee", "scam_pattern", {}),
        ("finance.verify_request", "scam_pattern", {}),
    ],
)
def test_missing_required_facts_fail_closed(name, field, changes):
    inputs = facts(**changes)
    del inputs[field]
    result = score(action(name), inputs, Rule(mode="ask"))
    assert result.band == "critical"
    assert names(result)[-1] == "scoring_error"
    assert field in result.factors[-1].evidence


@pytest.mark.parametrize("baseline", [{}, {"baseline_target_f": None}])
def test_hvac_without_baseline_has_no_deviation(baseline):
    inputs = facts()
    del inputs["baseline_target_f"]
    result = score(action("energy.hvac_adjust"), inputs | baseline, Rule(mode="auto"))
    assert result.band == "low" and result.factors == ()


def test_irrelevant_missing_fields_and_known_empty_observations():
    result = score(
        action("environment.lights"),
        {"observation_ages_seconds": (), "target_is_bedroom": False},
        Rule(mode="auto"),
    )
    assert result.band == "low" and not result.factors
    result = score(
        action("security.arm_disarm"),
        {"observation_ages_seconds": ()},
        Rule(mode="ask"),
    )
    assert result.band == "high" and not result.factors


@pytest.mark.parametrize(
    "changes",
    [
        {"guest_present": "false"},
        {"guest_present": 0},
        {"observation_ages_seconds": (-1,)},
        {"observation_ages_seconds": (True,)},
        {"observation_ages_seconds": ("300",)},
        {"observation_ages_seconds": (float("nan"),)},
        {"observation_ages_seconds": (float("inf"),)},
        {"observation_ages_seconds": 0},
        {"baseline_target_f": True},
        {"baseline_target_f": "NaN"},
        {"secret-unrecognized-key": "secret-value"},
    ],
)
def test_malformed_facts_fail_closed_without_echo(changes):
    result = score(action(), facts(**changes), Rule(mode="auto"))
    assert result.band == "critical" and result.base_band == "low"
    assert names(result) == ["scoring_error"]
    assert result.factors[0].evidence == "Invalid risk facts."


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"target_f": None},
        {"target_f": True},
        {"target_f": "secret"},
        {"target_f": float("inf")},
    ],
)
@pytest.mark.parametrize("baseline", [72, None])
def test_invalid_action_parameter_fails_closed(params, baseline):
    a = action("energy.hvac_adjust").model_copy(update={"params": params})
    result = score(a, facts(baseline_target_f=baseline), Rule(mode="auto"))
    assert result.band == "critical" and names(result)[-1] == "scoring_error"
    assert "secret" not in result.model_dump_json()


def test_invalid_bound_parameter_fails_closed():
    result = score(action(), facts(), Rule(mode="ask", bounds={"ev_soc_floor": "0.3"}))
    assert result.band == "critical"
    assert "action.params.ev_soc_floor" in result.factors[-1].evidence


def test_exceptions_preserve_completed_evidence(monkeypatch):
    def broken(_):
        raise RuntimeError("secret exception payload")

    monkeypatch.setattr("hirz.risk.engine.guards", broken)
    result = score(action(role="unknown"), facts(), Rule(mode="auto"))
    assert result.band == "critical" and result.base_band == "low"
    assert names(result) == ["unknown_requester", "scoring_error"]
    assert result.factors[-1].evidence == "Risk calculation failed."
    assert "secret" not in result.model_dump_json()


def test_failed_catalog_lookup_uses_critical_base():
    result = score(
        action().model_copy(update={"action_class": "unknown.class"}),
        facts(),
        Rule(mode="auto"),
    )
    assert result.band == result.base_band == "critical"
    assert names(result) == ["scoring_error"]


def test_models_immutable_revalidated_and_no_input_mutation():
    a, inputs, rule = action(), facts(), Rule(mode="auto")
    before = deepcopy((a.model_dump(), inputs, rule.model_dump()))
    typed = RiskFacts.model_validate(inputs)
    result = score(a, typed, rule)
    assert score(a, inputs, rule) == score(a, typed, rule) == result
    assert (a.model_dump(), inputs, rule.model_dump()) == before
    assert set(result.model_dump()) == {"band", "base_band", "factors"}
    with pytest.raises(ValidationError):
        typed.guest_present = True
    with pytest.raises(ValidationError):
        result.band = RiskBand.CRITICAL
    bypassed = typed.model_copy(update={"guest_present": "false"})
    assert score(a, bypassed, rule).band == "critical"


@pytest.mark.parametrize("seed", ["quinn-home", "quinn-parents"])
def test_constitutions_cannot_loosen_static_or_dynamic_floors(seed):
    policy = load(ROOT / f"constitutions/{seed}.yaml")
    for name, profile in CLASSES.items():
        if profile["band"] not in ("HIGH", "CRITICAL"):
            continue
        data = policy.model_dump()
        domain, short_name = name.split(".")
        data["autonomy"].setdefault(domain, {})[short_name] = {
            "mode": "auto",
            "ask_channels": ["app_push"],
        }
        with pytest.raises(
            ValidationError, match="Static HIGH/CRITICAL classes cannot be auto"
        ):
            Constitution.model_validate(data)
    for mode in ("auto", "ask", "never"):
        data = policy.model_dump()
        data["autonomy"]["energy"]["hvac_adjust"] = {"mode": mode}
        data["per_role"] = {}
        edited = Constitution.model_validate(data)
        a = action("energy.hvac_adjust", "unknown")
        result = score(
            a,
            facts(sleeping_in_target_zone=True, observation_ages_seconds=(301,)),
            edited.rule(a.action_class, "owner"),
        )
        assert result.band == "critical" and floor_outcome(result.band) == "never_auto"


@pytest.mark.parametrize("bad", [None, [], {}, {"bad": {}}, {"energy.ev_charge": []}])
def test_invalid_catalog_shape(bad):
    with pytest.raises(ValueError):
        load_catalog(yaml.safe_dump(bad))


@pytest.mark.parametrize(
    "change",
    [
        {"impact": True},
        {"impact": 0},
        {"impact": 6},
        {"reversibility": ""},
        {"reversibility": None},
        {"band": "low"},
        {"band": "EXTREME"},
        {"band": []},
        {"freshness_seconds": 0},
        {"freshness_seconds": -1},
        {"freshness_seconds": True},
        {"freshness_seconds": 1.5},
        {"extra": "field"},
    ],
)
def test_invalid_catalog_profile(change):
    with pytest.raises(ValueError):
        load_catalog(
            yaml.safe_dump({"energy.ev_charge": CLASSES["energy.ev_charge"] | change})
        )
