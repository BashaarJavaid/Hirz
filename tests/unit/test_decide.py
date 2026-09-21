"""CLI inputs are hypothetical and validation never echoes their values."""

from unittest.mock import patch

import pytest

from hirz import cli
from hirz.constitution.schema import load, loads
from hirz.local import LocalError
from hirz.pipeline.cli import HOMES, json_input
from tests.unit.test_pipeline import HOME


def arguments(**changes):
    values = {
        "household": str(HOME),
        "as": "malik",
        "surface": "alexa",
        "action": "finance.transfer_money",
        "adapter": "household",
        "entity": str(HOME),
        "params": "{}",
    } | changes
    return ["hirz", "decide", *[x for k, v in values.items() for x in ("--" + k, v)]]


@pytest.mark.parametrize(
    "change",
    [
        {"household": "PRIVATE"},
        {"household": "00000000-0000-0000-0000-000000000000"},
        {"zone": "PRIVATE"},
        {"surface": "PRIVATE"},
        {"action": "PRIVATE"},
        {"adapter": ""},
        {"entity": ""},
        {"at": "2026-10-13T17:35:00"},
        {"at": "PRIVATE"},
        {"cost": "PRIVATE"},
        {"cost": "NaN"},
        {"cost": "Infinity"},
        {"cost": "-0.01"},
        {"params": "PRIVATE"},
        {"params": "[]"},
        {"params": '{"PRIVATE":1,"PRIVATE":2}'},
        {"params": '{"nested":{"PRIVATE":1,"PRIVATE":2}}'},
        {"params": '{"PRIVATE":NaN}'},
        {"params": '{"PRIVATE":1e999}'},
        {"params": '{"PRIVATE":1152921504606846976}'},
    ],
)
def test_bad_inputs_precede_configuration(change, capsys):
    with (
        patch("sys.argv", arguments(**change)),
        patch(
            "hirz.pipeline.cli.read_env", side_effect=AssertionError("No config read")
        ),
    ):
        assert cli.main() == 2
    output = capsys.readouterr()
    assert output.out == "" and "Invalid decide input" in output.err
    assert "PRIVATE" not in output.err


@pytest.mark.parametrize(
    "text",
    [
        "PRIVATE",
        "[]",
        '[{"PRIVATE":true}]',
        '[{"source":"real"}]',
        '[{"household_id":"'
        + str(HOME)
        + '","observed_at":"2026-10-13T17:35:00Z","source":"real"}]',
    ],
)
def test_invalid_evidence(text, tmp_path, capsys):
    path = tmp_path / "evidence.json"
    path.write_text(text)
    with patch("sys.argv", arguments(evidence=str(path))):
        assert cli.main() == 2
    output = capsys.readouterr()
    assert not output.out and "PRIVATE" not in output.err


def test_missing_evidence_and_config(tmp_path, capsys):
    with patch("sys.argv", arguments(evidence=str(tmp_path / "PRIVATE"))):
        assert cli.main() == 1
    assert "PRIVATE" not in capsys.readouterr().err
    for values in ({}, {"AUDIT_SIGNING_KEY": "PRIVATE"}):
        with (
            patch("sys.argv", arguments()),
            patch("hirz.pipeline.cli.read_env", return_value=values),
        ):
            assert cli.main() == 1
        output = capsys.readouterr()
        assert not output.out and "PRIVATE" not in output.err
    with (
        patch("sys.argv", arguments()),
        patch("hirz.pipeline.cli.read_env", side_effect=LocalError("safe error")),
    ):
        assert cli.main() == 1
    assert "safe error" in capsys.readouterr().err


def test_help_and_shared_policy_parser(capsys):
    from pathlib import Path

    with (
        patch("sys.argv", ["hirz", "decide", "--help"]),
        pytest.raises(SystemExit) as exc,
    ):
        cli.main()
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "--requester-confirmed" in output and "--evidence" in output
    for slug in HOMES.values():
        path = Path(f"constitutions/{slug}.yaml")
        assert loads(path.read_text()) == load(path)
    assert json_input('{"target_f":72}') == {"target_f": 72}
