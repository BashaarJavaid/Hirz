"""Household authority and privacy through the authenticated HTTP SDK surface."""

import asyncio

import pytest

from scripts.smoke_tool_budget import run

pytestmark = pytest.mark.integration


def test_authenticated_household_isolation(tmp_path):
    report = asyncio.run(run("isolation", tmp_path / "isolation"))
    assert report["status"] == "passed"
