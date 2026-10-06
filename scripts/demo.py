"""Initialize isolated recording credentials, or run one fresh foreground demo."""

import argparse
import fcntl
import json
import os
import re
import secrets
import socket
import stat
import subprocess
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hirz.audit import verify_file, write_export  # noqa: E402
from hirz.companion.auth import Config  # noqa: E402
from hirz.graph.seeds import read_seed  # noqa: E402
from hirz.local import LocalError, read_env, signing_key  # noqa: E402
from hirz.mcp.dev_oauth import KEY_NAME  # noqa: E402
from hirz.mcp.dev_oauth import signing_key as oauth_key

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "secrets/demo"
LABEL = "org.hirz.recording=v1"
KEYS = {
    "POSTGRES_PASSWORD",
    "AUDIT_SIGNING_KEY",
    KEY_NAME,
    "HIRZ_DEMO_ORIGIN",
    "HIRZ_DEMO_NAMESPACE",
}
DEADLINE = 180


def private_dir(path: Path) -> None:
    if path.is_symlink():
        raise LocalError(f"Restore a regular private directory: {path}")
    path.mkdir(mode=0o700, exist_ok=True)
    if not path.is_dir() or stat.S_IMODE(path.stat().st_mode) != 0o700:
        raise LocalError(f"Directory must have mode 0700: {path}")


def command(
    *args: str,
    env: dict[str, str] | None = None,
    timeout: int = 30,
    log: Path | None = None,
) -> str:
    output = ""
    try:
        result = subprocess.run(
            args,
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
            start_new_session=True,
        )
        output = result.stdout + result.stderr
    except (OSError, subprocess.SubprocessError) as exc:
        for part in (getattr(exc, "stdout", ""), getattr(exc, "stderr", "")):
            output += (
                part.decode(errors="replace") if isinstance(part, bytes) else part or ""
            )
        raise LocalError(
            f"{args[0]} command failed or timed out; check Docker/HTTPS prerequisites. "
            "Output withheld because it may contain credentials. Storage retained."
        ) from None
    finally:
        if log is not None:
            fd = os.open(
                log, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600
            )
            with os.fdopen(fd, "w") as file:
                file.write(output)
    return result.stdout


def configuration(origin: str | None = None) -> dict[str, str]:
    values = read_env(DEMO / ".env")
    if set(values) != KEYS or values.get("HIRZ_DEMO_NAMESPACE") != "hirz-recording-v1":
        raise LocalError(
            "Incomplete or conflicting demo configuration; restore the original secrets/demo/.env."
        )
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", values["POSTGRES_PASSWORD"]):
        raise LocalError(
            "Malformed demo database credential; restore the original .env."
        )
    saved = values["HIRZ_DEMO_ORIGIN"]
    Config(saved, urlsplit(saved).hostname or "")
    if origin is not None and origin != saved:
        raise LocalError(
            "Demo origin conflicts with saved identity; restore/use the original origin."
        )
    signing_key(values)
    oauth_key(values)
    return values


def forwarding(origin: str) -> None:
    Config(origin, urlsplit(origin).hostname or "")
    status = json.loads(command("tailscale", "serve", "status", "--json"))
    handler = (
        status.get("Web", {})
        .get(urlsplit(origin).netloc + ":443", {})
        .get("Handlers", {})
        .get("/", {})
    )
    if (
        status.get("TCP", {}).get("443", {}).get("HTTPS") is not True
        or handler.get("Proxy") != "http://127.0.0.1:8002"
    ):
        raise LocalError(
            "Configure trusted Tailscale HTTPS forwarding for the saved origin to http://127.0.0.1:8002, then retry."
        )


def initialize(origin: str) -> None:
    Config(origin, urlsplit(origin).hostname or "")
    command("docker", "info", "--format", "{{.ServerVersion}}")
    if urlsplit(origin).hostname != "localhost":
        forwarding(origin)
    if (DEMO / ".env").exists() or (DEMO / ".env").is_symlink():
        configuration(origin)
        print("Demo configuration validated and preserved.")
        return
    retained = any(p.name != ".lock" for p in DEMO.iterdir())
    for kind in ("volume", "container"):
        flags = ("--all",) if kind == "container" else ()
        retained |= bool(
            command(
                "docker", kind, "ls", *flags, "--quiet", "--filter", f"label={LABEL}"
            ).strip()
        )
    if retained:
        raise LocalError(
            "Demo state exists without credentials; restore the original secrets/demo/.env. Nothing was reset."
        )

    def pem(key: ec.EllipticCurvePrivateKey | rsa.RSAPrivateKey) -> str:
        return key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()

    values = {
        "HIRZ_DEMO_NAMESPACE": "hirz-recording-v1",
        "HIRZ_DEMO_ORIGIN": origin,
        "POSTGRES_PASSWORD": secrets.token_urlsafe(32),
        "AUDIT_SIGNING_KEY": pem(ec.generate_private_key(ec.SECP256R1())),
        KEY_NAME: pem(rsa.generate_private_key(public_exponent=65537, key_size=2048)),
    }
    fd = os.open(DEMO / ".env", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        output.write("".join(f"{key}='{value}'\n" for key, value in values.items()))
        output.flush()
        os.fsync(output.fileno())
    configuration(origin)
    print(
        "Demo credentials initialized in secrets/demo/.env (0600); development unchanged."
    )


def ports_available() -> None:
    for port in (8002, 8003):
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                raise LocalError(
                    f"Port {port} is occupied; stop its owner yourself or finish that run first. No service was stopped."
                ) from None


def ready(path: Path, run_id: str) -> None:
    receipt = json.loads(path.read_text())
    expected = {
        "demo-evening": "2026-10-13T17:30:00-05:00",
        "parents-scam-check": "2026-10-13T17:00:00-05:00",
    }
    if (
        receipt.get("run_id") != run_id
        or receipt.get("mode") != "scripted"
        or receipt.get("seed") != 20261013
        or receipt.get("selected") != "demo-evening"
        or receipt.get("playing") is not False
        or receipt.get("failure") is not None
        or set(receipt.get("scenarios", {})) != set(expected)
        or any(
            datetime.fromisoformat(receipt["scenarios"][name]["at"])
            != datetime.fromisoformat(at)
            or receipt["scenarios"][name].get("next") != 0
            for name, at in expected.items()
        )
    ):
        raise LocalError(
            "Recording readiness receipt does not match the required fresh paused state."
        )


def wait_ready(path: Path, run_id: str, origin: str, *, until: float) -> None:
    with httpx.Client(timeout=3, trust_env=False) as client:
        while time.monotonic() < until:
            if path.exists():
                ready(path, run_id)
                try:
                    for url in (
                        "http://127.0.0.1:8002/health",
                        "http://127.0.0.1:8002/simulator",
                        "http://127.0.0.1:8003/.well-known/oauth-authorization-server",
                        origin + "/simulator",
                    ):
                        client.get(url).raise_for_status()
                    return
                except httpx.HTTPError:
                    pass
            time.sleep(0.5)
    raise LocalError(
        "Recording readiness timed out after 180 seconds; check private logs and trusted HTTPS forwarding. Storage retained."
    )


def open_browser(origin: str) -> None:
    url = origin + "/simulator"
    try:
        opened = webbrowser.open(url)
    except webbrowser.Error:
        opened = False
    print(f"{'Opened' if opened else 'Open manually'}: {url}", flush=True)


def verify_shutdown(
    artifacts: Path, run_id: str, values: dict[str, str], state: dict[str, Any]
) -> None:
    if (
        state.get("Status") != "exited"
        or state.get("ExitCode") != 0
        or state.get("OOMKilled")
    ):
        raise LocalError("Runtime did not exit successfully; storage retained.")
    if json.loads((artifacts / "shutdown.json").read_text()) != {
        "run_id": run_id,
        "exports_verified": True,
    }:
        raise LocalError("Missing successful shutdown receipt; storage retained.")
    for seed in ("quinn-home", "quinn-parents"):
        household = UUID(
            str(read_seed(ROOT / "constitutions" / (seed + ".yaml")).household_id)
        )
        verify_file(
            artifacts / str(household) / "audit.json",
            household,
            key=signing_key(values).public_key(),
        )


def run() -> None:
    values = configuration()
    if os.getuid() == 0:
        raise LocalError("Run the recording launcher as a non-root user.")
    ports_available()
    if urlsplit(values["HIRZ_DEMO_ORIGIN"]).hostname != "localhost":
        forwarding(values["HIRZ_DEMO_ORIGIN"])
    command("docker", "info", "--format", "{{.ServerVersion}}")
    private_dir(DEMO / "runs")
    run_id = "hirz-demo-" + uuid4().hex
    folder = DEMO / "runs" / run_id
    folder.mkdir(mode=0o700)
    env = {
        k: v
        for k, v in os.environ.items()
        if k
        in {
            "PATH",
            "HOME",
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
            "DOCKER_CONFIG",
            "DOCKER_TLS_VERIFY",
            "DOCKER_CERT_PATH",
        }
    }
    env.update(
        {
            "POSTGRES_PASSWORD": values["POSTGRES_PASSWORD"],
            "HIRZ_DEMO_ORIGIN": values["HIRZ_DEMO_ORIGIN"],
            "HIRZ_DEMO_UID": str(os.getuid()),
            "HIRZ_DEMO_GID": str(os.getgid()),
            "HIRZ_DEMO_RUN": run_id,
            "HIRZ_DEMO_RUN_DIR": str(folder),
        }
    )
    prefix = (
        "docker",
        "compose",
        "--project-name",
        run_id,
        "--env-file",
        str(DEMO / ".env"),
        "-f",
        str(ROOT / "compose.demo.yml"),
    )

    def compose(*args: str, timeout: int = 30) -> str:
        return command(
            *prefix, *args, env=env, timeout=timeout, log=folder / "commands.log"
        )

    def retain_logs() -> None:
        if not (folder / "compose.log").exists():
            logs = compose("logs", "--no-color")
            fd = os.open(
                folder / "compose.log", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
            )
            with os.fdopen(fd, "w") as output:
                output.write(logs)

    write_export(
        folder / "run.json",
        {
            "run_id": run_id,
            "origin": values["HIRZ_DEMO_ORIGIN"],
            "uid": os.getuid(),
            "gid": os.getgid(),
        },
    )
    print(f"Building recording image. Private run: {folder}", flush=True)
    healthy = False
    try:
        compose("build", timeout=1800)
        until = time.monotonic() + DEADLINE
        compose("up", "-d", timeout=DEADLINE)
        wait_ready(
            folder / "artifacts/ready.json",
            run_id,
            values["HIRZ_DEMO_ORIGIN"],
            until=until,
        )
        healthy = True
        print(
            f"Ready, paused. Private invitations: {folder / 'artifacts/invitations.json'}",
            flush=True,
        )
        open_browser(values["HIRZ_DEMO_ORIGIN"])
        print(
            "Keep this launcher attached. Ctrl-C exports and verifies both households before cleanup.",
            flush=True,
        )
        container = compose("ps", "--all", "--quiet", "simulator").strip()
        try:
            while True:
                state = json.loads(
                    command(
                        "docker", "inspect", "--format", "{{json .State}}", container
                    )
                )
                if state["Status"] != "running":
                    raise LocalError(
                        "Runtime stopped unexpectedly; inspect retained storage and evidence."
                    )
                time.sleep(1)
        except KeyboardInterrupt:
            compose("stop", "--timeout", "120", "simulator", timeout=130)
        state = json.loads(
            command("docker", "inspect", "--format", "{{json .State}}", container)
        )
        verify_shutdown(folder / "artifacts", run_id, values, state)
        retain_logs()
        compose("down", "--volumes", timeout=60)
        write_export(
            folder / "cleanup.json",
            {"run_id": run_id, "exports_verified": True, "storage_removed": True},
        )
        print(
            f"Verified shutdown; recording storage removed. Evidence preserved: {folder}"
        )
    except BaseException:
        # Stop this runtime first, but never delete failed storage, even if it exports.
        try:
            compose("stop", "--timeout", "120", "simulator", timeout=130)
            compose("stop", "postgres", timeout=60)
        except LocalError:
            pass
        print(
            f"Run failed ({'after' if healthy else 'before'} readiness). Storage/evidence retained: {folder}",
            file=sys.stderr,
        )
        raise
    finally:
        try:
            retain_logs()
        except LocalError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    sub.add_parser("init").add_argument("--origin", required=True)
    sub.add_parser("run")
    args = parser.parse_args()
    os.umask(0o077)
    if (ROOT / "secrets").is_symlink():
        raise LocalError("secrets must be a regular directory, not a symlink.")
    (ROOT / "secrets").mkdir(mode=0o700, exist_ok=True)
    private_dir(DEMO)
    fd = os.open(DEMO / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise LocalError(
                "Another demo initializer/launcher is attached; finish it first."
            ) from None
        if args.operation == "init":
            initialize(args.origin)
        else:
            run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("FAIL: interrupted before verified cleanup; storage retained.")
    except Exception as exc:
        sys.exit(
            f"FAIL: {exc}"
            if isinstance(exc, LocalError)
            else "FAIL: demo failed; private evidence and storage retained. See docs/development.md."
        )
