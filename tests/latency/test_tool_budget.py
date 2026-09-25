"""The complete local budget gate; deliberately excluded from coverage runs."""

import asyncio
import os
from pathlib import Path

import pytest

from scripts.smoke_tool_budget import run

pytestmark = pytest.mark.latency


@pytest.mark.parametrize(
    "scenario",
    [os.environ["HIRZ_BUDGET_SCENARIO"]]
    if "HIRZ_BUDGET_SCENARIO" in os.environ
    else ["demo-evening", "demo-evening-hourly"],
)
def test_tool_budget(tmp_path, scenario):
    directory = (
        Path(os.environ["HIRZ_BUDGET_ARTIFACTS"]) / scenario
        if "HIRZ_BUDGET_ARTIFACTS" in os.environ
        else tmp_path / "latency"
    )
    directory.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    report = asyncio.run(run("latency", directory, scenario=scenario))
    assert report["status"] == "passed"
