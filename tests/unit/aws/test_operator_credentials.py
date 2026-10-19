import os
import shlex
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from botocore.credentials import ProcessProvider

from scripts import aws_operator_credentials as bridge

NETWORK = 'aws: [ERROR]: Could not connect to the endpoint URL: "https://us-east-1.signin.aws.amazon.com/v1/token"'


def result(code=0, out="synthetic credential JSON", err=""):
    return subprocess.CompletedProcess([], code, stdout=out, stderr=err)


@pytest.mark.parametrize(
    "failure", [result(1, err=NETWORK), subprocess.TimeoutExpired("aws", 35)]
)
def test_transient_failure_recovers_without_logging_credentials(
    monkeypatch, capsys, failure
):
    run = Mock(side_effect=[failure, result()])
    monkeypatch.setattr(bridge.subprocess, "run", run)
    monkeypatch.setattr(bridge.time, "sleep", Mock())
    assert bridge.credentials() == "synthetic credential JSON"
    assert capsys.readouterr() == ("", "")
    assert run.call_count == 2
    command = run.call_args.args[0]
    assert command[command.index("--profile") + 1] == "hirz-operator-login"
    assert 0 < run.call_args.kwargs["timeout"] <= 35


@pytest.mark.parametrize(
    "error",
    ["Your session has expired", "Access denied: synthetic secret must not leak"],
)
def test_permanent_failure_is_not_retried_or_echoed(monkeypatch, capsys, error):
    run = Mock(return_value=result(1, out="private stdout", err=error))
    monkeypatch.setattr(bridge.subprocess, "run", run)
    assert bridge.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert (
        "synthetic secret" not in captured.err and "private stdout" not in captured.err
    )
    assert run.call_count == 1


def test_retries_are_bounded(monkeypatch):
    run = Mock(return_value=result(1, err=NETWORK))
    monkeypatch.setattr(bridge.subprocess, "run", run)
    monkeypatch.setattr(bridge.time, "sleep", Mock())
    with pytest.raises(RuntimeError, match="bounded retry window"):
        bridge.credentials()
    assert run.call_count == 3
    monkeypatch.setattr(bridge.time, "monotonic", Mock(side_effect=[0, 121]))
    run.reset_mock()
    with pytest.raises(RuntimeError, match="bounded retry window"):
        bridge.credentials()
    run.assert_not_called()


def test_success_uses_only_the_credential_protocol_stdout(monkeypatch, capsys):
    monkeypatch.setattr(bridge.subprocess, "run", Mock(return_value=result()))
    assert bridge.main() == 0
    assert capsys.readouterr() == ("synthetic credential JSON", "")


def test_sdk_process_bridge_recovers_from_cli_connection_failure(tmp_path, monkeypatch):
    count = tmp_path / "calls"
    aws = tmp_path / "aws"
    aws.write_text(
        f"#!{sys.executable}\n"
        "import json,sys\nfrom pathlib import Path\n"
        f"count=Path({str(count)!r})\n"
        "n=int(count.read_text()) if count.exists() else 0\n"
        "count.write_text(str(n+1))\n"
        f"if n == 0:\n print({NETWORK!r},file=sys.stderr)\n sys.exit(1)\n"
        "print(json.dumps({'Version':1,'AccessKeyId':'synthetic-access',"
        "'SecretAccessKey':'synthetic-secret','SessionToken':'synthetic-token',"
        "'Expiration':'2099-01-01T00:00:00Z'}))\n"
    )
    aws.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    command = shlex.join([sys.executable, str(Path(bridge.__file__).resolve())])
    provider = ProcessProvider(
        "fixture", lambda: {"profiles": {"fixture": {"credential_process": command}}}
    )
    credentials = provider.load().get_frozen_credentials()
    assert credentials.access_key == "synthetic-access"
    assert credentials.token == "synthetic-token"
    assert count.read_text() == "2"
