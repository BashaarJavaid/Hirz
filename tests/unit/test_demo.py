"""Recording credentials and destructive cleanup must fail closed."""

import json
import socket
import stat
import time

import pytest

from hirz.audit import export_document, write_export
from hirz.local import LocalError, signing_key
from scripts import demo

ORIGIN = "https://recording.example.test"


@pytest.fixture
def initialized(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "DEMO", tmp_path)
    monkeypatch.setattr(demo, "command", lambda *args, **kwargs: "")
    monkeypatch.setattr(demo, "forwarding", lambda origin: None)
    demo.initialize(ORIGIN)
    return tmp_path


def test_initialization_preserves_complete_config(initialized):
    path = initialized / ".env"
    before = path.read_bytes()
    demo.initialize(ORIGIN)
    assert path.read_bytes() == before
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(LocalError, match="conflicts"):
        demo.initialize("https://other.example.test")
    assert path.read_bytes() == before


@pytest.mark.parametrize("origin", ["http://localhost:8002", ORIGIN])
def test_forwarding_required_only_outside_localhost(tmp_path, monkeypatch, origin):
    monkeypatch.setattr(demo, "DEMO", tmp_path)
    monkeypatch.setattr(demo, "command", lambda *args, **kwargs: "")

    def forwarding(origin):
        raise AssertionError("forwarding called")

    monkeypatch.setattr(demo, "forwarding", forwarding)
    if origin == ORIGIN:
        with pytest.raises(AssertionError, match="forwarding called"):
            demo.initialize(origin)
        monkeypatch.setattr(demo, "forwarding", lambda origin: None)
    demo.initialize(origin)
    monkeypatch.setattr(demo, "forwarding", forwarding)
    monkeypatch.setattr(demo, "ports_available", lambda: None)

    def stop_before_startup(*args, **kwargs):
        raise LocalError("reached startup")

    monkeypatch.setattr(demo, "command", stop_before_startup)
    if origin == ORIGIN:
        with pytest.raises(AssertionError, match="forwarding called"):
            demo.run()
    else:
        with pytest.raises(LocalError, match="reached startup"):
            demo.run()


@pytest.mark.parametrize(
    "change", ["partial", "malformed", "identity", "permissions", "symlink", "missing"]
)
def test_init_refuses_damage_without_replacement(initialized, change):
    path = initialized / ".env"
    if change == "partial":
        path.write_text("POSTGRES_PASSWORD='partial'\n")
    elif change == "malformed":
        path.write_text(path.read_text().replace("BEGIN PRIVATE KEY", "BROKEN KEY"))
    elif change == "identity":
        path.write_text(path.read_text() + "\nDATABASE_URL='postgresql://elsewhere'\n")
    elif change == "permissions":
        path.chmod(0o644)
    elif change == "symlink":
        target = initialized / "saved"
        path.rename(target)
        path.symlink_to(target)
    else:
        path.unlink()
        (initialized / "runs").mkdir()
    before = path.read_bytes() if path.exists() else None
    with pytest.raises((LocalError, ValueError)):
        demo.initialize(ORIGIN)
    assert (path.read_bytes() if path.exists() else None) == before


def test_missing_credentials_with_retained_docker_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "DEMO", tmp_path)
    monkeypatch.setattr(demo, "forwarding", lambda origin: None)
    monkeypatch.setattr(
        demo,
        "command",
        lambda *args, **kw: "retained-volume" if "volume" in args else "",
    )
    with pytest.raises(LocalError, match="state exists"):
        demo.initialize(ORIGIN)
    assert not (tmp_path / ".env").exists()


def test_ports_and_private_directories(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 8003))
        listener.listen()
        with pytest.raises(LocalError, match="occupied"):
            demo.ports_available()
    demo.private_dir(tmp_path / "run")
    assert stat.S_IMODE((tmp_path / "run").stat().st_mode) == 0o700
    (tmp_path / "alias").symlink_to(tmp_path / "run")
    with pytest.raises(LocalError):
        demo.private_dir(tmp_path / "alias")


def receipt(path):
    write_export(
        path,
        {
            "run_id": "test",
            "mode": "scripted",
            "seed": 20261013,
            "selected": "demo-evening",
            "playing": False,
            "failure": None,
            "scenarios": {
                "demo-evening": {"at": "2026-10-13T17:30:00-05:00", "next": 0},
                "parents-scam-check": {"at": "2026-10-13T17:00:00-05:00", "next": 0},
            },
        },
    )


def test_readiness_timeout_and_wrong_run(tmp_path):
    path = tmp_path / "ready.json"
    with pytest.raises(LocalError, match="timed out"):
        demo.wait_ready(path, "test", ORIGIN, until=time.monotonic())
    receipt(path)
    demo.ready(path, "test")
    value = json.loads(path.read_text())
    value["scenarios"]["demo-evening"]["at"] = "2026-10-13T22:30:00+00:00"
    path.write_text(json.dumps(value))
    demo.ready(path, "test")
    with pytest.raises(LocalError, match="paused state"):
        demo.ready(path, "wrong")
    value = json.loads(path.read_text())
    value["scenarios"]["demo-evening"]["next"] = 1
    path.write_text(json.dumps(value))
    with pytest.raises(LocalError):
        demo.ready(path, "test")


@pytest.mark.parametrize("raises", [False, True])
def test_browser_failure_keeps_url(monkeypatch, capsys, raises):
    def open_browser(url):
        if raises:
            raise demo.webbrowser.Error()
        return False

    monkeypatch.setattr(demo.webbrowser, "open", open_browser)
    demo.open_browser(ORIGIN)
    assert f"Open manually: {ORIGIN}/simulator" in capsys.readouterr().out


def test_cleanup_requires_exit_receipt_and_both_trusted_exports(initialized):
    values = demo.configuration()
    state = {"Status": "exited", "ExitCode": 0, "OOMKilled": False}
    write_export(
        initialized / "shutdown.json", {"run_id": "test", "exports_verified": True}
    )
    key = signing_key(values).public_key()
    paths = []
    for seed in ("quinn-home", "quinn-parents"):
        household = demo.read_seed(
            demo.ROOT / "constitutions" / (seed + ".yaml")
        ).household_id
        folder = initialized / str(household)
        folder.mkdir()
        path = folder / "audit.json"
        write_export(path, export_document(household, key, []))
        paths.append(path)
    demo.verify_shutdown(initialized, "test", values, state)
    for bad in ({"Status": "running"}, {"ExitCode": 137}, {"OOMKilled": True}):
        with pytest.raises(LocalError):
            demo.verify_shutdown(initialized, "test", values, state | bad)
    with pytest.raises(LocalError):
        demo.verify_shutdown(initialized, "other", values, state)
    paths[1].write_text("{}")
    with pytest.raises(ValueError):
        demo.verify_shutdown(initialized, "test", values, state)


@pytest.mark.parametrize("failure", ["startup", "runtime", "export", "shutdown", None])
def test_wrapper_cleanup_authorization(initialized, monkeypatch, failure):
    monkeypatch.setattr(demo, "ports_available", lambda: None)

    def wait(*args, **kwargs):
        if failure == "startup":
            raise LocalError("startup failure")

    monkeypatch.setattr(demo, "wait_ready", wait)
    monkeypatch.setattr(demo, "open_browser", lambda origin: None)
    calls = []
    inspected = 0

    def command(*args, **kwargs):
        nonlocal inspected
        calls.append(args)
        if "inspect" in args:
            inspected += 1
            if inspected == 1 and failure != "runtime":
                raise KeyboardInterrupt
            return json.dumps({"Status": "exited", "ExitCode": 1 if failure else 0})
        if "stop" in args and "simulator" in args and failure == "shutdown":
            raise LocalError("shutdown failure")
        return ""

    def verify(*args):
        if failure == "export":
            raise LocalError("export failure")

    monkeypatch.setattr(demo, "command", command)
    monkeypatch.setattr(demo, "verify_shutdown", verify)
    if failure:
        with pytest.raises(LocalError):
            demo.run()
    else:
        demo.run()
    assert any("down" in args for args in calls) is (failure is None)
    folder = next((initialized / "runs").iterdir())
    assert (folder / "run.json").exists()
    assert (folder / "cleanup.json").exists() is (failure is None)
