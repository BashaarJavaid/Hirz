"""Explicit 24-hour twin fixture; its start remains fixed across deployments."""

import os
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from hirz.aws.routing import Route, Routing
from hirz.graph.seeds import Seed, demo_id, read_seed
from hirz.twin.scenario import LoadedScenario


def policy_seeds() -> list[Seed]:
    """Approved initial acceptance copies; the hosted quinn-home fixture stays local."""
    seeds = []
    for suffix in ("home", "parents"):
        source = read_seed(Path(f"constitutions/quinn-{suffix}.yaml"))
        name = "item37-" + suffix
        source.graph["household"].update(
            slug=name, name=f"Inert AWS policy acceptance: {suffix}"
        )
        for row in source.graph.get("member_accounts", []):
            row["sub"] += "-item37"
        source.constitution["household"] = name
        seeds.append(Seed(source.graph, source.constitution))
    return seeds


def policy_routes(route: Route) -> Routing:
    return Routing(
        frozenset(
            demo_id(name, "households", name)
            for name in ("item37-home", "item37-parents")
        ),
        frozenset({demo_id("quinn-home", "households", "quinn-home")}),
        route,
    )


def load() -> LoadedScenario:
    start = datetime.fromisoformat(os.environ["HIRZ_FIXTURE_START"])
    if start.tzinfo is None:
        raise ValueError("Fixture start requires a timezone")
    start = start.astimezone(ZoneInfo("America/Chicago"))
    raw = yaml.safe_load(Path("scenarios/demo-evening.yaml").read_text())
    shift = start - datetime.fromisoformat(raw["clock"]["start"])

    def dates(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: dates(v) for k, v in value.items()}
        if isinstance(value, list):
            return [dates(v) for v in value]
        if isinstance(value, str) and value.startswith(("2026-10-13T", "2026-10-14T")):
            return (datetime.fromisoformat(value) + shift).isoformat()
        return value

    raw = dates(raw)
    raw.update(
        id="aws-item36-twin",
        household=str(Path("constitutions/quinn-home.yaml").resolve()),
        rate_plan="twin",
        clock={
            "start": start.isoformat(),
            "end": (start + timedelta(hours=24)).isoformat(),
            "speed": 1,
        },
        execution={"member": "malik", "rooms": raw["execution"]["rooms"]},
        timeline=[],
        planning=[],
    )
    next_minute = start + timedelta(minutes=1)
    check_at = (
        "+1d " if next_minute.date() != start.date() else ""
    ) + next_minute.strftime("%H:%M")
    raw["assert"] = {
        "checks": [
            {
                "at": check_at,
                "kind": "observation",
                "domain": "devices",
                "subject": "light.living_room",
                "equals": {"on": False},
            }
        ],
        "deferred": [],
    }
    raw["adapters"]["energy"] = "twin"
    # The temporary file is input only; all runtime changes remain Pipeline writes.
    with TemporaryDirectory(prefix="hirz-aws-fixture-") as folder:
        path = Path(folder) / "fixture.yaml"
        path.write_text(yaml.safe_dump(raw))
        return LoadedScenario(path)
