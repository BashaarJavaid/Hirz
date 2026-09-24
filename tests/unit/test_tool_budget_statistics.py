"""The benchmark cannot hide a slow path by pooling or omitting samples."""

from types import SimpleNamespace

import pytest

from hirz.mcp.contracts import TOOLS
from scripts.smoke_tool_budget import (
    SAMPLES,
    SELECTION_CASES,
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
