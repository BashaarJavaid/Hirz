"""Item 7 semantics only: these tests do not claim pipeline or device behavior."""

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from hirz.constitution.boundary import BoundaryError, Dogwood, Event
from hirz.constitution.compiler import compile_policy
from hirz.constitution.conditions import FactError, PolicyFacts, evaluate, number, parse
from hirz.constitution.evaluator import policy_values, resolve
from hirz.constitution.preview import SITUATIONS, preview, situation
from hirz.constitution.render import render
from hirz.constitution.schema import Constitution, dump, load
from hirz.pipeline.models import ROLES, Action
from hirz.risk import CLASSES

ROOT = Path(__file__).resolve().parents[2]


def home():
    return load(ROOT / "constitutions/quinn-home.yaml")


def edit(policy, domain, name, **changes):
    data = policy.model_dump()
    data["autonomy"][domain][name].update(changes)
    return Constitution.model_validate(data)


@pytest.mark.parametrize("seed", ["quinn-home", "quinn-parents"])
def test_seeds_and_lossless_render(seed, tmp_path):
    policy = load(ROOT / f"constitutions/{seed}.yaml")
    path = tmp_path / "policy.yaml"
    path.write_text(dump(policy))
    assert load(path) == policy
    assert render(load(path)) == render(policy)
    assert any("ev soc floor: 0.3" in line for line in render(policy))
    assert len(CLASSES) == len(SITUATIONS) == 40
    assert any("enforced by the internal pipeline" in line for line in render(policy))
    assert all(
        CLASSES[c]["band"] != "HIGH" or policy.rule(c, "owner").mode != "auto"
        for c in CLASSES
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(typo=True),
        lambda p: p["autonomy"]["energy"].update(unknown={"mode": "auto"}),
        lambda p: p["autonomy"].update(unknown={}),
        lambda p: p["roles"].update(robot={}),
        lambda p: p["roles"].pop("child"),
        lambda p: p["roles"]["adult"].update(inherits="owner"),
        lambda p: p["roles"]["guest"].update(inherits="adult"),
        lambda p: p["roles"]["caregiver"].update(limited_to=["finance"]),
        lambda p: p["autonomy"]["security"]["door_unlock"].update(mode="auto"),
        lambda p: p["autonomy"]["finance"]["transfer_money"].update(mode="auto"),
        lambda p: p["autonomy"]["security"]["access_code_share"].pop("ask_channels"),
        lambda p: p["autonomy"]["security"]["door_unlock"].update(
            ask_channels=["alexa"]
        ),
        lambda p: p["autonomy"]["energy"]["ev_charge"].update(ask_channels=[]),
        lambda p: p["autonomy"]["energy"]["ev_charge"].update(
            conditions=["asset.typo is set"]
        ),
        lambda p: p["autonomy"]["energy"]["ev_charge"].update(
            overrides=[{"when": "context.hour > 1", "mode": "auto"}], mode="ask"
        ),
        lambda p: p["per_role"]["teen"].update(
            {"finance.transfer_money": {"mode": "auto"}}
        ),
        lambda p: p["per_role"]["teen"].update({"bogus.class": {"mode": "never"}}),
        lambda p: p["defaults"].update(approval_ttl_minutes=True),
        lambda p: p["defaults"].update(approval_ttl_minutes=1441),
        lambda p: p["defaults"].update(approval_ttl_minutes=0),
        lambda p: p["autonomy"]["energy"]["hvac_adjust"].update(
            bounds={"min_f": 77, "max_f": 76}
        ),
        lambda p: p["quiet_hours"][0].update(from_time="25:00"),
        lambda p: p["quiet_hours"][0].update(affects=["unknown"]),
        lambda p: p["verification"].update(require_requester_confirmation=["unknown"]),
    ],
)
def test_closed_schema(mutate):
    data = home().model_dump()
    # Pydantic dumps tuples: retain the documents' editable sequence shape.
    data = json.loads(json.dumps(data, default=str))
    mutate(data)
    with pytest.raises(ValueError):
        Constitution.model_validate(data)


@pytest.mark.parametrize(
    "text",
    [
        "version: 1\nversion: 2",
        "---\n{}\n---\n{}\n---\n{}",
        "---\nhousehold: {slug: other}\n---\nhousehold: home",
    ],
)
def test_bad_yaml(text, tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(text)
    with pytest.raises(ValueError):
        load(p)


@pytest.mark.parametrize(
    "source",
    [
        "context.hour + 1 > 2",
        "context.hour > 1.00001",
        "context.hour > context.hour",
        "unknown.foo is set",
        "true",
        "context.hour == true",
        'requester.role < "owner"',
        "occupancy.present()",
        'schedule.expected_within("resident", -1)',
        "context.hour in []",
        "context.hour is missing",
        "context.hour == 2 extra",
    ],
)
def test_invalid_grammar(source):
    with pytest.raises(ValueError):
        parse(source)


@pytest.mark.parametrize(
    "value", ["NaN", "Infinity", "1.00001", True, {}, "922337203685477.5808"]
)
def test_invalid_decimals(value):
    with pytest.raises(ValueError):
        number(value)


def test_boolean_precedence_null_and_preflight():
    p = home()
    action, facts = situation(p, "energy.hvac_adjust")
    values = policy_values(action, facts)
    assert evaluate(
        parse("context.hour == 17 or context.hour == 3 and context.hour == 4"),
        values,
        facts,
    )
    assert not evaluate(
        parse("(context.hour == 17 or context.hour == 3) and context.hour == 4"),
        values,
        facts,
    )
    for source in [
        "not (asset.state.temp_f < 5)",
        "context.hour == 17 or asset.state.temp_f < 5",
        "context.hour == 0 and asset.state.temp_f < 5",
        "asset.state.temp_f is not set",
    ]:
        with pytest.raises(FactError) as error:
            evaluate(parse(source), values, facts)
        assert error.value.paths == ("asset.state.temp_f",)
    facts = replace(facts, values={"asset": {"state": {"temp_f": None}}})
    values = policy_values(action, facts)
    assert evaluate(parse("asset.state.temp_f is not set"), values, facts)
    assert not evaluate(parse("asset.state.temp_f is set"), values, facts)
    with pytest.raises(FactError):
        evaluate(
            parse("asset.state.temp_f is not set or asset.state.temp_f < 4"),
            values,
            facts,
        )
    assert evaluate(
        parse('context.time >= "17:30"'),
        policy_values(action, situation(p, action.action_class)[1]),
        facts,
    )


def test_predicates_scoped_exact_zone_and_inclusive_horizon():
    p = home()
    action, facts = situation(p, "energy.hvac_adjust")
    facts = replace(
        facts,
        values={
            "occupancy": {
                "members": [
                    {
                        "member_id": "resident",
                        "zone_id": "guest_room",
                        "present": True,
                        "sleeping": True,
                    }
                ]
            },
            "schedule": {
                "arrivals": [
                    {"member_id": "resident", "expected_at": facts.as_of.isoformat()}
                ]
            },
        },
    )
    values = policy_values(action, facts)
    assert evaluate(parse('occupancy.present("resident")'), values, facts)
    assert not evaluate(
        parse("occupancy.sleeping_in(action.target.zone)"), values, facts
    )
    assert evaluate(parse('schedule.expected_within("resident", 0)'), values, facts)
    for offset, expected in [(600, True), (601, False), (-1, False)]:
        from datetime import timedelta

        f = replace(
            facts,
            values={
                "schedule": {
                    "arrivals": [
                        {
                            "member_id": "resident",
                            "expected_at": (
                                facts.as_of + timedelta(seconds=offset)
                            ).isoformat(),
                        }
                    ]
                }
            },
        )
        assert (
            evaluate(
                parse('schedule.expected_within("resident", 10)'),
                policy_values(action, f),
                f,
            )
            is expected
        )
    for values in (
        {},
        {"occupancy": {"members": None}},
        {"occupancy": {"members": [{"member_id": "other-home", "present": True}]}},
    ):
        f = replace(facts, values=values)
        with pytest.raises(FactError):
            evaluate(
                parse('occupancy.present("resident")'), policy_values(action, f), f
            )
    with pytest.raises(FactError):
        evaluate(parse('occupancy.sleeping_in("other-home-zone")'), values, facts)
    empty = replace(
        facts, values={"occupancy": {"members": []}, "schedule": {"arrivals": []}}
    )
    assert not evaluate(parse('occupancy.present("resident")'), empty.values, empty)
    assert not evaluate(
        parse('schedule.expected_within("resident", 10)'), empty.values, empty
    )


def test_snapshot_is_immutable():
    original = {"context": {"hour": 17}}
    f = PolicyFacts("home", datetime.now(UTC), original)
    original["context"]["hour"] = 22
    assert f.values["context"]["hour"] == 17
    with pytest.raises(TypeError):
        f.values["context"]["hour"] = 1
    with pytest.raises(ValueError):
        replace(f, as_of=datetime(2026, 1, 1))


@pytest.mark.parametrize(
    "role,name,expected",
    [
        ("owner", "energy.hvac_adjust", "auto"),
        ("teen", "energy.hvac_adjust", "ask"),
        ("child", "environment.lights", "never"),
        ("guest", "environment.lights", "auto"),
        ("guest", "environment.shades", "never"),
        ("caregiver", "energy.hvac_adjust", "never"),
        ("teen", "security.door_unlock", "never"),
        ("unknown", "health.routine_reminders", "never"),
    ],
)
def test_precedence_and_domains(role, name, expected):
    p = home()
    a, f = situation(p, name, role)
    assert resolve(p, a, f).effective_mode == expected


def test_parent_restrictions_unlisted_and_approval_defaults():
    data = home().model_dump()
    data["per_role"]["adult"] = {"environment.lights": {"mode": "ask"}}
    p = Constitution.model_validate(data)
    for r in ["owner", "adult", "caregiver"]:
        assert (
            resolve(p, *situation(p, "environment.lights", r)).effective_mode == "ask"
        )
    data["per_role"]["owner"] = {"environment.lights": {"mode": "auto"}}
    with pytest.raises(ValueError):
        Constitution.model_validate(data)
    data = home().model_dump()
    del data["autonomy"]["environment"]["shades"]
    p = Constitution.model_validate(data)
    for r in ROLES:
        assert p.role_mode("environment.shades", r) == (
            "ask" if r in ["owner", "adult", "caregiver"] else "never"
        )
    assert p.approvers("security.door_unlock", "any_adult") == ("owner", "adult")
    assert p.approvers("environment.lights", "all_adults") == (
        "owner",
        "adult",
        "caregiver",
    )
    p = edit(p, "energy", "hvac_adjust", approval_ttl_minutes=10)
    assert resolve(p, *situation(p, "energy.hvac_adjust")).approval.ttl_minutes == 10


@pytest.mark.parametrize(
    "value,mode,error",
    [
        (66, "auto", False),
        (76, "auto", False),
        ("65.9999", "never", False),
        ("76.0001", "never", False),
        ("72.00001", "never", True),
        (None, "never", True),
    ],
)
def test_decimal_hard_bounds(value, mode, error):
    p = home()
    a, f = situation(p, "energy.hvac_adjust", case={"params": {"target_f": value}})
    out = resolve(p, a, f)
    assert out.effective_mode == mode
    assert any(d.code == "POLICY_ERROR" for d in out.diagnostics) == error


def test_conditions_overrides_and_vetoes_cannot_be_bypassed():
    p = home()
    a, f = situation(p, "energy.hvac_adjust", "teen", {"values": {"occupancy": {}}})
    out = resolve(p, a, f)
    assert out.effective_mode == "ask" and out.diagnostics[0].code == "POLICY_ERROR"
    p = edit(
        p,
        "energy",
        "hvac_adjust",
        overrides=[{"when": "context.hour > 16", "mode": "never"}],
    )
    assert (
        resolve(p, *situation(p, "energy.hvac_adjust", "teen")).effective_mode
        == "never"
    )
    p = edit(
        p,
        "energy",
        "hvac_adjust",
        overrides=[
            {"when": "context.hour > 16", "mode": "ask"},
            {"when": "context.hour > 15", "mode": "never"},
        ],
    )
    assert resolve(p, *situation(p, "energy.hvac_adjust")).effective_mode == "ask"
    p = edit(p, "energy", "hvac_adjust", conditions=["context.hour < 12"], overrides=[])
    out = resolve(p, *situation(p, "energy.hvac_adjust"))
    assert (
        out.effective_mode == "ask" and not out.conditions_met and not out.diagnostics
    )
    p = edit(p, "security", "door_unlock", never_for=["unexpected_visitor"])
    assert (
        resolve(
            p,
            *situation(
                p,
                "security.door_unlock",
                case={"values": {"context": {"unexpected_visitor": True}}},
            ),
        ).effective_mode
        == "never"
    )
    assert (
        resolve(
            p, *situation(p, "security.door_unlock", case={"values": {"context": {}}})
        ).effective_mode
        == "never"
    )
    a, f = situation(p, "environment.lights")
    assert resolve(p, a, replace(f, household="other")).effective_mode == "never"


def test_all_worked_examples_and_preview():
    old = home()
    data = old.model_dump()
    data["version"] = 8
    data["autonomy"]["security"]["door_unlock"]["never_for"] = ["unexpected_visitor"]
    new = Constitution.model_validate(data)
    assert preview(old, new)["lines"] == [
        "Unexpected visitor: ask on phone → never",
        "Expected arrival: still asks on your phone",
        "Hirz does not identify the visitor",
    ]
    assert any(
        r["label"] == "Unknown visitor context" and r["changed"]
        for r in preview(old, new)["situations"]
    )
    assert (
        resolve(old, *situation(old, "finance.verify_request")).effective_mode == "auto"
    )
    assert (
        resolve(old, *situation(old, "finance.transfer_money")).effective_mode
        == "never"
    )
    # Budget is configured on optimize_cost, not battery_dispatch; runtime denial is item 9.
    a, f = situation(
        old,
        "energy.optimize_cost",
        case={"values": {"household": {"budget_used_today": Decimal("9.60")}}},
    )
    out = resolve(old, a, f)
    assert out.effective_mode == "auto" and out.budget.usd_per_day == 10
    assert out.approval.quorum == "any_adult"
    with pytest.raises(ValueError):
        preview(old, load(ROOT / "constitutions/quinn-parents.yaml"))


@pytest.mark.parametrize(
    "body",
    [
        'print("not json")',
        'print("[]")',
        "raise SystemExit(3)",
        "import time;time.sleep(2)",
        "print('{\"verdicts\":[]}')",
        'print(\'{"verdicts":[{"index":0,"timestamp":1,"verdict":"allow","errors":["oops"],"determining_rules":[]}]}\')',
    ],
)
def test_subprocess_fail_closed(tmp_path, body):
    fake = tmp_path / "dogwood"
    fake.write_text("#!/usr/bin/env python3\n" + body + "\n")
    fake.chmod(0o700)
    c = compile_policy(home())
    d = Dogwood(str(fake), timeout=0.1)
    result = asyncio.run(d.authorize(c, Event(1, "environment.lights", {})))
    assert not result.allowed and result.diagnostic == "DENY_BOUNDARY"


def test_missing_binary_and_malformed_validation(tmp_path):
    c = compile_policy(home())
    with pytest.raises(BoundaryError):
        asyncio.run(Dogwood("/no/such/dogwood").validate(c))
    fake = tmp_path / "dogwood"
    fake.write_text("#!/usr/bin/env python3\nprint('{\"passed\":true}')")
    fake.chmod(0o700)
    with pytest.raises(BoundaryError):
        asyncio.run(Dogwood(str(fake)).validate(c))


def test_canonical_action_rejects_unknown_class():
    a, _ = situation(home(), "environment.lights")
    data = a.model_dump()
    data["action_class"] = "unknown.action"
    with pytest.raises(ValueError):
        Action.model_validate(data)


def test_policy_yaml_does_not_round_excess_precision(tmp_path):
    text = dump(home()).replace("min_f: '66'", "min_f: 66.000000000000001")
    assert "66.000000000000001" in text
    path = tmp_path / "precision.yaml"
    path.write_text(text)
    with pytest.raises(ValueError, match="four fractional digits"):
        load(path)


def test_bare_time_literal_and_membership():
    p = home()
    a, f = situation(p, "environment.lights")
    values = policy_values(a, f)
    assert evaluate(
        parse('context.time >= 17:30 and requester.role in ["owner", "adult"]'),
        values,
        f,
    )


def test_cli_workflows_and_errors(tmp_path, capsys, monkeypatch):
    from hirz.cli import main

    for operation in ("validate", "compile"):
        monkeypatch.setattr(
            "sys.argv",
            [
                "hirz",
                "constitution",
                operation,
                str(ROOT / "constitutions/quinn-home.yaml"),
            ],
        )
        assert main() == 0
        output = json.loads(capsys.readouterr().out)
        assert output["valid"] and output["analysis"] == "not analyzed: local mode"
        if operation == "compile":
            assert len(output["manifest"]["actions"]) == 40
    path = tmp_path / "bad.yaml"
    path.write_text(dump(home()).replace("version: 7", "version: 0"))
    monkeypatch.setattr("sys.argv", ["hirz", "constitution", "validate", str(path)])
    assert main() == 1
    captured = capsys.readouterr()
    assert (
        captured.out == ""
        and json.loads(captured.err)["error"] == "INVALID_CONSTITUTION"
    )
    path.write_text("version: 1\nversion: 2")
    assert main() == 1
    assert json.loads(capsys.readouterr().err)["error"] == "CONSTITUTION_ERROR"
    path.write_text(dump(home()))
    monkeypatch.setattr(
        "sys.argv", ["hirz", "constitution", "preview", str(path), str(path)]
    )
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["situations"] == []
