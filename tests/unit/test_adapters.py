"""Adapter contract smoke: every implementation here is synthetic test code."""

import asyncio
from datetime import timedelta
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from hirz.adapters.base import (
    AdapterError,
    AdapterUnavailable,
    PriceSlot,
    WeatherSample,
    validate_range,
)
from hirz.adapters.registry import Registry, parse_config
from hirz.graph.models import AssetBinding, Observation
from tests.unit.test_pipeline import AT, HOME, SEED, ident


class TestAdapter:
    __test__ = False

    def __init__(self, household, capabilities=frozenset({"get_state"})):
        self.household_id = household.id
        self.capabilities = capabilities
        self.start = AsyncMock()
        self.close = AsyncMock()
        self.get_state = AsyncMock()
        self.get_charge_state = AsyncMock()


def registry(**changes):
    models = SEED.models(AT)
    home = models["households"][0]
    values = dict(
        members=tuple(models["members"]),
        assets=tuple(models["assets"]),
        factories={
            (d, i): (
                lambda h, domain=d: TestAdapter(
                    h,
                    frozenset({"get_charge_state" if domain == "ev" else "get_state"}),
                )
            )
            for d, i in (("devices", "ha"), ("devices", "twin"), ("ev", "twin"))
        },
        sources={},
        config="devices:ha,ev:twin",
    )
    return Registry(home, **(values | changes))


def reading(asset="light.living_room", **changes):
    return Observation.model_validate(
        dict(
            id=uuid4(),
            household_id=HOME,
            asset_id=ident("assets", asset),
            domain="devices",
            observed_at=AT,
            source="real",
            state={"available": True},
        )
        | changes
    )


def test_mixed_boot(capsys):
    async def run():
        light, climate, guest = (
            ident("assets", s)
            for s in ("light.living_room", "hvac.living_room", "hvac.guest_room")
        )
        binding = AssetBinding(
            id=uuid4(),
            household_id=HOME,
            asset_id=guest,
            adapter="twin",
            entity_id="hvac.guest_room",
        )
        reg = registry(
            bindings=(binding,),
            sources={
                ("devices", "ha", light): "real",
                ("devices", "ha", climate): "real API, demo devices",
            },
        )
        await reg.start()
        try:
            assert len(reg.instances) == 3
            assert (
                reg.resolve("devices", asset_id=guest)
                is reg.instances[("devices", "twin")]
            )
            assert (
                reg.resolve("devices", asset_id=light, capability="get_state")
                is reg.instances[("devices", "ha")]
            )
            for asset, impl, source, domain in (
                ("light.living_room", "ha", "real", "devices"),
                ("hvac.living_room", "ha", "real API, demo devices", "devices"),
                ("hvac.guest_room", "twin", "twin", "devices"),
                ("ev", "twin", "twin", "ev"),
            ):
                result = reg.stamp(
                    domain, impl, reading(asset, domain=domain, source=source), at=AT
                )
                assert result.source == source
                print(
                    f"TEST IMPLEMENTATION: {domain}:{impl}; {asset}; source={result.source}"
                )
            with pytest.raises(AdapterUnavailable):
                reg.resolve("presence")
            with pytest.raises(AdapterUnavailable):
                reg.resolve("devices", capability="set_light")
            with pytest.raises(AdapterError):
                reg.resolve("ev", asset_id=light)
            with pytest.raises(AdapterError):
                await reg.start()
        finally:
            instances = tuple(reg.instances.values())
            await reg.close()
        assert not reg.instances
        for adapter in instances:
            adapter.start.assert_awaited_once()
            adapter.close.assert_awaited_once()
        with pytest.raises(AdapterUnavailable):
            reg.resolve("devices")

    asyncio.run(run())
    output = capsys.readouterr().out
    assert output.count("TEST IMPLEMENTATION") == 4
    print(output, end="")


@pytest.mark.parametrize(
    "config",
    [
        "devices",
        "devices:ha,",
        "unknown:twin",
        "devices:",
        "devices:ha:extra",
        "devices:ha,devices:twin",
    ],
)
def test_bad_config(config):
    with pytest.raises(AdapterError):
        parse_config(config)


def test_environment_and_unregistered_configuration(monkeypatch):
    monkeypatch.delenv("HIRZ_ADAPTERS", raising=False)
    assert parse_config() == {}
    monkeypatch.setenv("HIRZ_ADAPTERS", " devices:ha , ev:twin ")
    assert parse_config() == {"devices": "ha", "ev": "twin"}
    assert parse_config("") == {}
    with pytest.raises(AdapterError):
        registry(config="devices:missing")
    asyncio.run(registry(config="").start())


@pytest.mark.parametrize(
    "failure",
    ["factory", "start", "scope", "capabilities", "method", "close", "cancel"],
)
def test_start_failure_cleans_all_resources(failure):
    created = []

    def factory(home):
        if len(created) == 1 and failure == "factory":
            raise RuntimeError("PRIVATE")
        adapter = TestAdapter(
            home, frozenset({"get_charge_state" if created else "get_state"})
        )
        created.append(adapter)
        if len(created) == 2:
            if failure == "scope":
                adapter.household_id = uuid4()
            elif failure == "capabilities":
                adapter.capabilities = {"get_state"}
            elif failure == "method":
                adapter.get_charge_state = None
            else:
                adapter.start.side_effect = (
                    asyncio.CancelledError()
                    if failure == "cancel"
                    else RuntimeError("PRIVATE")
                )
            if failure == "close":
                adapter.close.side_effect = RuntimeError("PRIVATE")
        return adapter

    async def run():
        reg = registry(
            factories={(d, i): factory for d, i in (("devices", "ha"), ("ev", "twin"))}
        )
        with pytest.raises(
            asyncio.CancelledError if failure == "cancel" else AdapterError
        ) as error:
            await reg.start()
        assert "PRIVATE" not in str(error.value)
        assert not reg.started and not reg.instances
        for adapter in created:
            adapter.close.assert_awaited_once()

    asyncio.run(run())


@pytest.mark.parametrize(
    "change",
    [
        {"household_id": uuid4()},
        {"asset_id": uuid4()},
        {"observed_at": AT + timedelta(seconds=1)},
        {"source": "twin"},
        {"domain": None},
    ],
)
def test_observation_scope_time_and_provenance(change):
    async def run():
        light = ident("assets", "light.living_room")
        reg = registry(sources={("devices", "ha", light): "real"})
        await reg.start()
        try:
            with pytest.raises(AdapterError):
                reg.stamp("devices", "ha", reading(**change), at=AT)
            with pytest.raises(AdapterError):
                reg.stamp("devices", "twin", reading(), at=AT)
            with pytest.raises(AdapterError):
                reg.stamp("devices", "ha", reading("hvac.living_room"), at=AT)
        finally:
            await reg.close()

    asyncio.run(run())


def test_invalid_registration_and_values():
    models = SEED.models(AT)
    asset = models["assets"][0]
    for changes in (
        {"assets": (asset, asset)},
        {"assets": (asset.model_copy(update={"household_id": uuid4()}),)},
        {
            "bindings": (
                AssetBinding(
                    id=uuid4(),
                    household_id=HOME,
                    asset_id=uuid4(),
                    adapter="ha",
                    entity_id="unknown",
                ),
            )
        },
        {"sources": {("devices", "ha", uuid4()): "real"}},
        {"sources": {("ev", "twin", asset.id): "real"}},
        {"sources": {("devices", "ha", asset.id): "invalid"}},
    ):
        with pytest.raises(AdapterError):
            registry(**changes)
    price = PriceSlot(
        start=AT, end=AT + timedelta(hours=1), import_cents_per_kwh="-1.2345"
    )
    assert (
        price.import_cents_per_kwh == Decimal("-1.2345")
        and price.export_cents_per_kwh is None
    )
    for end in (AT, AT - timedelta(seconds=1), AT.replace(tzinfo=None)):
        with pytest.raises(ValueError):
            validate_range(AT, end)
    with pytest.raises(ValueError):
        WeatherSample(at=AT, temp_f=70, cloud_cover_percent=101)
    assert (
        WeatherSample(at=AT, temp_f=70.123456, cloud_cover_percent=50).temp_f == 70.1235
    )
