"""Local diagnostics, synthetic demo bootstrap, and graph reads."""

import argparse
import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from uuid import UUID

import httpx
import sqlalchemy as sa

from hirz.audit.cli import add_commands, audit_command, validate_args
from hirz.constitution.cli import constitution_command
from hirz.db import connect_database, require_current
from hirz.graph.context import ContextService
from hirz.graph.models import SCOPES, GraphError, utc
from hirz.graph.seeds import load_seeds, read_seed
from hirz.local import (
    DEMO_ENTITIES,
    HA_URL,
    REQUEST_TIMEOUT,
    LocalError,
    read_env,
    signing_key,
)
from hirz.pipeline.cli import add_decide, decide_command
from hirz.twin.scenario_cli import (
    add_scenario,
    scenario_command,
    validate_scenario_args,
)


async def check_postgres(values: dict[str, str]) -> str:
    async with connect_database(values) as connection:
        if await connection.scalar(sa.text("SELECT 1")) != 1:
            raise LocalError("Postgres returned an unexpected query result.")
    return "authenticated SELECT 1."


async def check_ha(values: dict[str, str]) -> str:
    token = values.get("HA_TOKEN")
    if not token:
        raise LocalError("HA_TOKEN is missing; run scripts/init_dev.py.")
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, trust_env=False) as client:
        response = await client.get(
            HA_URL + "/api/states", headers={"Authorization": f"Bearer {token}"}
        )
    if response.status_code != 200:
        raise LocalError("HA state read failed; check the service and saved HA_TOKEN.")
    data = response.json()
    if not isinstance(data, list) or any(
        not isinstance(row, dict) or not isinstance(row.get("entity_id"), str)
        for row in data
    ):
        raise LocalError("HA returned malformed entity states.")
    if not DEMO_ENTITIES <= {row["entity_id"] for row in data}:
        raise LocalError("HA demo entities are missing; check HA initialization.")
    return "real API, demo devices (simulated); required entities present."


async def check_key(values: dict[str, str]) -> str:
    signing_key(values)
    return "P-256 private key signs and verifies an in-memory probe."


async def check_migrations(values: dict[str, str]) -> str:
    async with connect_database(values) as connection:
        await connection.run_sync(require_current)
    return "database matches the sole Alembic head; graph tables and household_context present."


async def doctor() -> int:
    checks: list[tuple[str, Callable[[dict[str, str]], Awaitable[str]], str]] = [
        ("Postgres", check_postgres, "Check Postgres and restore its .env password."),
        ("HA", check_ha, "Check HA service status and saved HA_TOKEN."),
        ("Signing key", check_key, "Restore the original AUDIT_SIGNING_KEY."),
        (
            "Migrations",
            check_migrations,
            "Check Postgres, then run uv run alembic upgrade head from the checkout root.",
        ),
    ]
    failed = False
    for name, check, recovery in checks:
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                detail = await check(read_env(Path(".env")))
            print(f"PASS {name}: {detail}")
        except LocalError as exc:
            failed = True
            print(f"FAIL {name}: {exc}")
        except Exception:
            failed = True
            print(f"FAIL {name}: check failed or timed out. {recovery}")
    return int(failed)


def aware_timestamp(value: str) -> datetime:
    try:
        return utc(datetime.fromisoformat(value))
    except ValueError:
        raise argparse.ArgumentTypeError(
            "Use a timezone-aware ISO-8601 timestamp."
        ) from None


async def graph_command(args: argparse.Namespace) -> int:
    try:
        seeds = (
            [read_seed(path) for path in args.paths] if args.command == "seed" else []
        )
        async with connect_database(read_env(Path(".env"))) as connection:
            if args.command == "seed":
                result = await load_seeds(connection, seeds)
                print(json.dumps(result))
            else:
                snapshot = await ContextService(connection).get_household_context(
                    args.household_id,
                    args.scope,
                    args.as_of,
                    args.member,
                    allow_stale=True,
                )
                print(snapshot.model_dump_json())
        return 0
    except (GraphError, LocalError) as exc:
        print(str(exc), file=sys.stderr)
    except Exception:
        print(
            "Graph operation failed; check Postgres, migrations, and seed data. "
            "Private values and upstream details withheld.",
            file=sys.stderr,
        )
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    worker_parser = commands.add_parser(
        "worker", help="Sweep durable local household execution"
    )
    worker_parser.add_argument("--household", type=UUID, required=True)
    worker_parser.add_argument("--once", action="store_true")
    worker_parser.add_argument(
        "--historical-fixture",
        action="store_true",
        help="Allow unactivated historical policies only in disposable smoke databases",
    )
    worker_parser.add_argument(
        "--database", default="hirz", help="Explicit local database (no migrations)"
    )
    add_commands(commands)
    add_decide(commands)
    add_scenario(commands)
    commands.add_parser(
        "doctor", help="Check local services, signing key, and migrations"
    )
    seed = commands.add_parser("seed", help="Bootstrap the synthetic demo households")
    seed.add_argument("paths", nargs="+", type=Path)
    context = commands.add_parser("context", help="Read redacted household context")
    context.add_argument("household_id", type=UUID)
    context.add_argument("--scope", choices=SCOPES, default="all")
    context.add_argument("--member", type=UUID)
    context.add_argument("--as-of", type=aware_timestamp)
    constitution = commands.add_parser(
        "constitution", help="Validate, compile, or preview rules without a database"
    )
    operations = constitution.add_subparsers(dest="operation", required=True)
    for operation in ("validate", "compile"):
        command = operations.add_parser(operation)
        command.add_argument("file", type=Path)
        command.add_argument("--gateway-resource", default="hirz-local")
    preview = operations.add_parser("preview")
    preview.add_argument("old", type=Path)
    preview.add_argument("new", type=Path)
    args = parser.parse_args()
    if args.command == "worker":
        from hirz.executor.local import worker

        return asyncio.run(worker(args))
    if args.command == "scenario":
        validate_scenario_args(args, parser)
        return asyncio.run(scenario_command(args))
    if args.command == "decide":
        return asyncio.run(decide_command(args))
    if args.command in {"audit", "verify-audit"}:
        validate_args(args, parser)
        return asyncio.run(audit_command(args))
    if args.command == "constitution":
        return asyncio.run(constitution_command(args))
    if args.command == "context" and (args.scope == "member") != (
        args.member is not None
    ):
        parser.error("--member is required only for member scope")
    if args.command == "doctor":
        return asyncio.run(doctor())
    return asyncio.run(graph_command(args))
