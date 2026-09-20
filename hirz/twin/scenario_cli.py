"""Scenario CLI: exact simulated time and redacted JSON reports."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import yaml

from hirz.twin.scenario import LoadedScenario, run_scenario


def positive_speed(value: str) -> float:
    try:
        speed = float(value)
        if math.isfinite(speed) and speed > 0:
            return speed
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("Speed must be positive and finite.")


def add_scenario(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    scenario = commands.add_parser("scenario", help="Run an offline simulated scenario")
    operations = scenario.add_subparsers(dest="operation", required=True)
    for operation in ("run", "step"):
        command = operations.add_parser(operation)
        command.add_argument("file", type=Path)
        command.add_argument("--assert", dest="assertions", action="store_true")
        command.add_argument("--output", type=Path)
        command.add_argument("--to", required=operation == "step")
        if operation == "run":
            command.add_argument("--headless", action="store_true")
            command.add_argument("--speed", type=positive_speed)
            command.add_argument("--step", action="store_true")


def validate_scenario_args(
    args: argparse.Namespace, parser: argparse.ArgumentParser
) -> None:
    if args.operation == "run" and bool(args.step) != (args.to is not None):
        parser.error("--step and --to must be supplied together")


async def scenario_command(args: argparse.Namespace) -> int:
    try:
        # Fail before a paced run, including for dangling symlinks.
        if args.output is not None and (
            args.output.exists() or args.output.is_symlink()
        ):
            raise ValueError("Report output already exists.")
        loaded = LoadedScenario(args.file)
        report = await run_scenario(
            loaded,
            headless=getattr(args, "headless", False),
            assertions=args.assertions,
            speed=getattr(args, "speed", None),
            to=args.to,
            progress=lambda line: print(line, file=sys.stderr),
        )
        encoded = json.dumps(report, sort_keys=True, allow_nan=False) + "\n"
        if args.output is not None:
            with args.output.open("x") as output:
                output.write(encoded)
        print(encoded, end="")
        return int(report["status"] == "failed")
    except (ValueError, OSError, TypeError, KeyError, yaml.YAMLError):
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": "Invalid scenario, unavailable validator, or report output failure; private inputs withheld.",
                }
            ),
            file=sys.stderr,
        )
        return 1
