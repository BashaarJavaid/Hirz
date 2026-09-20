"""Item 16 proves simulated observations, never pretends deferred tools executed."""

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from hirz.constitution.boundary import Dogwood
from hirz.twin.scenario import LoadedScenario, instant, run_scenario

ROOT = Path(__file__).resolve().parents[2]
EVENING = ROOT / "scenarios/demo-evening.yaml"
PARENTS = ROOT / "scenarios/parents-scam-check.yaml"


def altered(tmp_path, source=EVENING, edit=lambda data: None, patch_edit=None):
    data = yaml.safe_load(source.read_text())
    data["household"] = str((source.parent / data["household"]).resolve())
    for event in data["timeline"]:
        if "patch" in event:
            patch = yaml.safe_load((source.parent / event["patch"]).read_text())
            if patch_edit:
                patch_edit(patch)
            target = tmp_path / "patch.yaml"
            target.write_text(yaml.safe_dump(patch))
            event["patch"] = str(target)
    edit(data)
    path = tmp_path / "scenario.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def run(path=EVENING, **kwargs):
    return asyncio.run(
        run_scenario(LoadedScenario(path), headless=True, assertions=True, **kwargs)
    )


@pytest.mark.parametrize(
    "path,events,checks,deferred", [(EVENING, 20, 16, 25), (PARENTS, 5, 9, 9)]
)
def test_full_scenarios_are_repeatable_and_honest(path, events, checks, deferred):
    first = run(path)
    assert first == run(path)
    assert first["status"] == "item16_observations_passed"
    assert len(first["events"]) == events
    assert len(first["checks"]) == checks
    assert all(c["status"] == "passed" for c in first["checks"])
    assert len(first["deferred"]) == deferred
    assert all(
        r["source"] == "twin" for s in first["snapshots"] for r in s["observations"]
    )
    assert all(
        e["status"] == "deferred"
        for e in first["events"]
        if e["event"] in {"voice", "app.approve", "link.replay"}
    )
    text = json.dumps(first)
    for private in (
        "+1 312 555 0199",
        "five hundred dollars",
        "value_hash",
        "claimed_author",
        '"audit_range"',
    ):
        assert private not in text
    if path == EVENING:
        activation = first["events"][2]
        assert activation["recorded"] and activation["authenticated"] is False
        assert (
            "Expected arrival: still asks on your phone"
            in activation["preview"]["lines"]
        )
        assert any(
            "Unexpected visitor" in line and "never" in line
            for line in activation["preview"]["lines"]
        )
        # Both entities share household_id/domain; tariff must not match the battery.
        assert first["checks"][-1]["status"] == "passed"


def test_paced_and_headless_match_without_real_waiting():
    delays = []

    async def sleep(seconds):
        delays.append(seconds)

    paced = asyncio.run(
        run_scenario(LoadedScenario(PARENTS), assertions=True, sleep=sleep)
    )
    assert paced == run(PARENTS)
    assert sum(delays) == 25
    assert all(0 < delay <= 30 for delay in delays)


def test_step_excludes_same_time_events_and_marks_checks_not_reached():
    report = run(to="18:40")
    assert report["status"] == "stopped"
    assert len(report["events"]) == 6
    assert report["checks"][4]["status"] == "not_reached"
    assert not any(
        r["state"]["last_press_at"] for r in report["snapshots"][-1]["observations"]
    )
    full = run()
    tied = [e for e in full["events"] if e["at"] == report["end"]]
    assert [e["event"] for e in tied] == ["doorbell.press", "voice"]
    assert run(to="17:30")["events"] == []


@pytest.mark.parametrize(
    "edit",
    [
        lambda d: d.update(extra=True),
        lambda d: d["clock"].update(speed=float("inf")),
        lambda d: d["clock"].update(end=d["clock"]["start"]),
        lambda d: d["initial"].pop("presence"),
        lambda d: d["initial"].update(presence=[]),
        lambda d: d["initial"]["presence"].update(malik=1),
        lambda d: d["initial"]["weekly"].update(malik=1),
        lambda d: d["initial"]["weekly"].update(malik=[1]),
        lambda d: d["initial"].update(couplings={}),
        lambda d: d["initial"].update(couplings=[1]),
        lambda d: d["adapters"].pop("doorbell"),
        lambda d: d["timeline"][18].update(score=True),
        lambda d: d["initial"]["evs"]["ev"].update(soc=2),
        lambda d: d["initial"]["presence"].update(
            stranger=dict(present=False, sleeping=False, zone_id=None)
        ),
        lambda d: d["timeline"][0].update(member="someone_else"),
        lambda d: d["timeline"][0].update(at="+1d 08:00"),
        lambda d: d["timeline"][0].update(at="tomorrow"),
        lambda d: d["timeline"][0].update(at="18:00"),
        lambda d: d["timeline"][0].update(event="arbitrary.execute"),
        lambda d: d["timeline"][11].pop("deferred"),
        lambda d: d["timeline"][1].update(script=["invented_tool"]),
        lambda d: d["timeline"][6].update(entity="lock.front_door"),
        lambda d: d["timeline"][15].update(zone="lock.front_door"),
        lambda d: d["assert"]["checks"][0].update(subject="someone_else"),
        lambda d: d["assert"]["checks"][0].update(equals={"made_up": True}),
        lambda d: d["assert"]["checks"][0].update(domain="energy"),
        lambda d: d["assert"].update(checks=[]),
        lambda d: d["adapters"].update(devices="ha"),
    ],
)
def test_invalid_inputs_fail_before_execution(tmp_path, edit):
    with pytest.raises((ValueError, KeyError)):
        LoadedScenario(altered(tmp_path, edit=edit))


def test_duplicate_keys_are_rejected(tmp_path):
    path = altered(tmp_path)
    path.write_text(path.read_text() + "seed: 1\n")
    with pytest.raises(ValueError, match="Duplicate"):
        LoadedScenario(path)


@pytest.mark.parametrize(
    "edit,patch_edit",
    [
        (lambda d: d["timeline"][2].update(member="mom"), None),
        (lambda d: d["timeline"][1].update(script=["get_household_plan"]), None),
        (lambda d: None, lambda p: p.update(base_version=6)),
        (lambda d: None, lambda p: p.update(version=9)),
        (
            lambda d: None,
            lambda p: p["autonomy"]["security"]["door_unlock"].update(
                ask_channels=["alexa"]
            ),
        ),
    ],
)
def test_failed_activation_retains_old_policy(tmp_path, edit, patch_edit):
    loaded = LoadedScenario(altered(tmp_path, edit=edit, patch_edit=patch_edit))
    report = asyncio.run(run_scenario(loaded, headless=True, assertions=True))
    assert report["status"] == "failed"
    assert loaded.policy.version == 7
    assert not loaded.registry.started


def test_unavailable_native_validator_fails_closed():
    loaded = LoadedScenario(EVENING)
    report = asyncio.run(
        run_scenario(
            loaded,
            headless=True,
            assertions=True,
            dogwood=Dogwood("/nonexistent/hirz-dogwood"),
        )
    )
    assert report["status"] == "failed"
    assert loaded.policy.version == 7


def test_assertions_unchecked_and_failed(tmp_path):
    unchecked = asyncio.run(run_scenario(LoadedScenario(PARENTS), headless=True))
    assert unchecked["status"] == "completed_unchecked"
    assert all(c["status"] == "unchecked" for c in unchecked["checks"])
    path = altered(
        tmp_path,
        PARENTS,
        edit=lambda d: d["assert"]["checks"][0].update(equals={"present": False}),
    )
    assert run(path)["status"] == "failed"
    assert cli("run", str(path), "--headless", "--assert").returncode == 1


def test_time_grammar_and_existing_dst_rules():
    start = datetime.fromisoformat("2026-11-01T00:00:00-05:00")
    assert (
        instant("01:30", start, "America/Chicago").isoformat()
        == "2026-11-01T06:30:00+00:00"
    )
    start = datetime.fromisoformat("2026-03-08T00:00:00-06:00")
    assert (
        instant("02:30", start, "America/Chicago").isoformat()
        == "2026-03-08T08:30:00+00:00"
    )
    assert instant("+1d 06:45", start, "America/Chicago").day == 9
    for value in ("24:00", "06:60", "-1d 06:00", "6:00"):
        with pytest.raises(ValueError):
            instant(value, start, "America/Chicago")


def cli(*args):
    return subprocess.run(
        [str(Path(sys.executable).with_name("hirz")), "scenario", *args],
        cwd=ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
    )


def test_cli_reports_alias_no_overwrite_and_usage(tmp_path):
    output = tmp_path / "report.json"
    result = cli("run", str(PARENTS), "--headless", "--assert", "--output", str(output))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == json.loads(output.read_text())
    before = output.read_bytes()
    assert cli("run", str(PARENTS), "--output", str(output)).returncode == 1
    assert output.read_bytes() == before
    link = tmp_path / "link.json"
    link.symlink_to(tmp_path / "absent")
    assert cli("run", str(PARENTS), "--output", str(link)).returncode == 1
    a = cli("step", str(PARENTS), "--to", "17:05", "--assert")
    b = cli("run", str(PARENTS), "--step", "--to", "17:05", "--assert")
    assert a.returncode == b.returncode == 0
    assert json.loads(a.stdout) == json.loads(b.stdout)
    for args in [("--speed", "0"), ("--speed", "nan"), ("--to", "17:05"), ("--step",)]:
        assert cli("run", str(PARENTS), *args).returncode == 2
