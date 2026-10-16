"""Full companion ceremonies, persisted assertions and independently verified exports."""

import asyncio
import json
from pathlib import Path

import pytest

from hirz.twin.scenario import LoadedScenario, run_scenario

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "name",
    [
        "stranger-in-window",
        "parents-scam-check",
        "parents-scam-no-answer",
        "parents-ordinary-request",
    ],
)
def test_full_local_sequence(name, tmp_path):
    folder = tmp_path / name
    report = asyncio.run(
        run_scenario(
            LoadedScenario(Path(f"scenarios/{name}.yaml")),
            headless=True,
            assertions=True,
            artifacts_dir=folder,
        )
    )
    assert report["status"] == "full_sequence_passed", report.get("error")
    assert all(c["status"] == "passed" for c in report["checks"])
    assert report["setup"]["authenticated"] is True
    assert report["audit"]["status"] == "valid"
    assert json.loads((folder / "report.json").read_text()) == report
    assert folder.stat().st_mode & 0o777 == 0o700
