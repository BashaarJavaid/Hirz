"""Static resources, retained evidence integrity and observation-only door state."""

import asyncio
from datetime import timedelta
from hashlib import sha256
from pathlib import Path

import httpx
import pytest
import yaml
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from hirz.api.app import create_app
from hirz.mcp.card_data import doorbell
from hirz.mcp.card_evidence import load
from hirz.mcp.cards import MIME, NAMES, register
from tests.unit.test_pipeline import AT, HOME, snapshot


def test_anonymous_templates_contain_no_household_data():
    async def run():
        app = create_app(register=register)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app)
            ) as http:
                async with streamable_http_client(
                    "http://127.0.0.1:8000/mcp", http_client=http
                ) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        resources = (await session.list_resources()).resources
                        assert len(resources) == 5
                        for resource in resources:
                            result = await session.read_resource(resource.uri)
                            content = result.contents[0]
                            assert content.mimeType == MIME
                            assert str(HOME) not in content.text
                            assert "BEGIN PRIVATE KEY" not in content.text
                            assert "quinn-home" not in content.text
                            assert content.meta["ui"]["csp"]["connectDomains"] == []

    asyncio.run(run())


def test_missing_card_prevents_startup(monkeypatch, tmp_path):
    import hirz.mcp.cards as cards

    monkeypatch.setattr(cards, "__file__", str(tmp_path / "cards.py"))
    with pytest.raises(RuntimeError, match="Build all five"):
        create_app(register=register)
    assert len(NAMES) == 5


def test_evidence_preserves_negative_results_and_refuses_mismatches(tmp_path):
    results = Path("scripts/backtest-data/results.json").resolve()
    entry = dict(
        results_file=str(results),
        sha256=sha256(results.read_bytes()).hexdigest(),
        profile="comed_time_of_day",
        household_variant="solar_battery_ev",
        wear_per_internal_kwh=0.01,
    )
    path = tmp_path / "evidence.yaml"

    def write():
        path.write_text(yaml.safe_dump({"households": {str(HOME): entry}}))

    write()
    assert load(path)[HOME].usd < 0
    for key, wrong in (
        ("sha256", "0" * 64),
        ("profile", "unknown"),
        ("household_variant", "unknown"),
        ("wear_per_internal_kwh", 99),
    ):
        original = entry[key]
        entry[key] = wrong
        write()
        assert load(path) == {}
        entry[key] = original
    assert load(None) == {}
    assert load(tmp_path / "missing") == {}


def test_doorbell_freshness_sources_and_schedule_do_not_identify_visitors():
    snap = snapshot()
    bell_id = next(a["id"] for a in snap.data["assets"] if a["kind"] == "doorbell")
    lock_id = next(a["id"] for a in snap.data["assets"] if a["kind"] == "lock")
    bell = next(o for o in snap.data["observations"] if o.get("asset_id") == bell_id)
    lock = next(o for o in snap.data["observations"] if o.get("asset_id") == lock_id)
    bell["state"]["last_press_at"] = AT.isoformat()
    lock["state"]["locked"] = True
    card = doorbell(snap)
    assert card.snapshot == "twin" and card.lock_state == "locked"
    assert card.source == "simulated" and card.can_request
    lock["source"] = "real"
    assert doorbell(snap).source == "simulated"
    bell["source"] = "real"
    assert doorbell(snap).snapshot is None and doorbell(snap).source == "live"
    lock["state"]["locked"] = False
    assert doorbell(snap).lock_state == "unlocked"
    lock["state"]["locked"] = None
    assert doorbell(snap).lock_state == "unknown" and not doorbell(snap).can_request
    lock["state"]["locked"] = False
    lock["observed_at"] = (AT - timedelta(seconds=61)).isoformat()
    assert doorbell(snap).lock_state == "unknown" and not doorbell(snap).can_request
    bell["state"]["last_press_at"] = (AT - timedelta(seconds=61)).isoformat()
    assert doorbell(snap) is None
