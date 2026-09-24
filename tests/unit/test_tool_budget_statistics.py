"""The benchmark cannot hide a slow path by pooling or omitting samples."""

import asyncio
import sys
from types import SimpleNamespace

import pytest

from hirz.mcp.contracts import TOOLS
from scripts.smoke_tool_budget import (
    SAMPLES,
    SELECTION_CASES,
    Environment,
    statistics,
    timing_report,
)
from scripts.tool_selection import CASES


def test_nearest_rank_retains_outliers_and_requires_complete_measurements():
    values = list(range(1, 101))
    result = statistics(values)
    assert result["count"] == SAMPLES
    assert result["p95_ms"] == 95
    assert result["median_ms"] == 50.5
    assert result["max_ms"] == 100
    assert result["samples_ms"] == values
    assert len(SELECTION_CASES) == len(CASES)
    with pytest.raises(AssertionError, match="Every tool"):
        timing_report([])
    incomplete = SimpleNamespace(
        samples={tool: [1.0] * SAMPLES for tool in TOOLS},
        tools={tool: tool for tool in TOOLS},
    )
    with pytest.raises(AssertionError, match="Missing or unexpected cases"):
        timing_report([incomplete])
    with pytest.raises(AssertionError):
        statistics([float("nan")])


def test_cancelled_benchmark_reaps_its_worker(tmp_path, monkeypatch):
    async def run():
        create = asyncio.create_subprocess_exec
        started = asyncio.Event()
        children = []

        async def worker(*args, **kwargs):
            child = await create(sys.executable, "-c", "import time; time.sleep(30)")
            children.append(child)
            started.set()
            return child

        monkeypatch.setattr(asyncio, "create_subprocess_exec", worker)
        connection = SimpleNamespace(
            engine=SimpleNamespace(url=SimpleNamespace(database="unused-disposable"))
        )
        env = Environment(connection, tmp_path, "demo-evening")
        env.fixture = tmp_path / "unused.yaml"
        env.clock_file = tmp_path / "clock.txt"
        env.clock_file.write_text("2026-09-23T00:00:00+00:00")
        task = asyncio.create_task(env.run_worker())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert children[0].returncode is not None

    asyncio.run(run())
