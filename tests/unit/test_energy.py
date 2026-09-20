"""Recorded contracts, reviewed primary tariff values, DST and failure boundaries."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import yaml

from hirz.adapters.base import (
    AdapterError,
    AdapterUnavailable,
    Gap,
    PriceSeries,
    WeatherSeries,
)
from hirz.adapters.energy.real import RealEnergy, factories, feeds
from hirz.adapters.energy.real.tariff import CHICAGO, DELIVERY_CLASS, load_tariff
from hirz.adapters.registry import Registry
from hirz.graph.models import Household, Location
from hirz.twin.adapters import factories as twin_factories
from scripts.smoke_energy import FIXTURES, TARIFF, recorded, smoke
from scripts.smoke_twin import demo_world

START = datetime(2026, 8, 1, tzinfo=CHICAGO)
NOW = datetime(2026, 9, 20, 15, tzinfo=UTC)


def home(plan="comed_hourly", location=True):
    return Household(
        id=uuid4(),
        name="test",
        timezone="America/Chicago",
        locale="en-US",
        rate_plan=plan,
        location=Location(latitude=41.8781, longitude=-87.6298, source="declared")
        if location
        else None,
    )


def adapter(plan="comed_hourly", handler=recorded, **kwargs):
    return RealEnergy(
        home(plan),
        delivery_class=DELIVERY_CLASS,
        tariff_path=TARIFF,
        transport=httpx.MockTransport(handler),
        clock=lambda: NOW,
        **kwargs,
    )


def read(
    start=START,
    end=None,
    kind="day_ahead",
    *,
    supply=False,
    plan="comed_hourly",
    handler=recorded,
):
    async def run():
        a = adapter(plan, handler)
        await a.start()
        try:
            method = a.get_supply_history if supply else a.get_prices
            return await method(start, end or start + timedelta(days=1), kind)
        finally:
            await a.close()

    return asyncio.run(run())


def test_retained_hashes_and_reviewed_tariff_values():
    tariff = load_tariff(TARIFF)
    for source in tariff.sources:
        assert (
            sha256((TARIFF.parent / source.file).read_bytes()).hexdigest()
            == source.sha256
        )
    for name, metadata in json.loads((FIXTURES / "manifest.json").read_text()).items():
        assert sha256((FIXTURES / name).read_bytes()).hexdigest() == metadata["sha256"]
        assert metadata["url"].startswith("https://")
        assert datetime.fromisoformat(metadata["retrieved_at"]).tzinfo
    # Reviewed against retained supply p1 and delivery pp1–2 (resultant, not base).
    reviewed = {
        "morning": (6, 13, "3.778", "4.768", "4.475"),
        "mid_day_peak": (13, 19, "16.594", "14.699", "11.852"),
        "evening": (19, 21, "5.793", "6.009", "4.185"),
        "overnight": (21, 6, "2.829", "3.394", "3.345"),
    }
    for row in tariff.rows:
        assert row.billing_start.isoformat() == "2026-06-01"
        assert row.verified_on.isoformat() == "2026-09-20"
        if row.period == "flat":
            assert row.cents_per_kwh == Decimal("6.333")
            continue
        start, end, summer, winter, delivery = reviewed[row.period]
        assert (row.start_hour, row.end_hour) == (start, end)
        assert row.cents_per_kwh == Decimal(
            delivery
            if row.component == "distribution"
            else summer
            if row.season == "summer"
            else winter
        )
        assert row.document_effective_date.isoformat() == (
            "2026-05-16" if row.component == "supply" else "2026-06-01"
        )
        if row.component == "supply":
            assert row.billing_end.isoformat() == "2027-06-01"
        else:
            assert row.billing_end is None


@pytest.mark.parametrize("month", [6, 9, 10, 1, 5])
@pytest.mark.parametrize(
    "hour,band",
    [
        (0, "overnight"),
        (5, "overnight"),
        (6, "morning"),
        (12, "morning"),
        (13, "mid_day_peak"),
        (18, "mid_day_peak"),
        (19, "evening"),
        (20, "evening"),
        (21, "overnight"),
        (23, "overnight"),
    ],
)
def test_tariff_every_boundary_season_and_weekends(month, hour, band):
    year = 2027 if month < 6 else 2026
    start = datetime(year, month, 6, hour, tzinfo=CHICAGO)
    result = read(start, start + timedelta(hours=1), plan="comed_time_of_day")
    supply = {
        "morning": ("3.778", "4.768"),
        "mid_day_peak": ("16.594", "14.699"),
        "evening": ("5.793", "6.009"),
        "overnight": ("2.829", "3.394"),
    }[band][0 if 6 <= month <= 9 else 1]
    distribution = {
        "morning": "4.475",
        "mid_day_peak": "11.852",
        "evening": "4.185",
        "overnight": "3.345",
    }[band]
    assert result.slots[0].import_cents_per_kwh == Decimal(supply) + Decimal(
        distribution
    )
    assert result.complete and result.source == "real" and result.retrieved_at is None
    assert result.slots[0].export_cents_per_kwh is None
    assert "published" in result.source_label and len(result.source_urls) == 2


@pytest.mark.parametrize(
    "date,valid",
    [
        ("2026-05-31", False),
        ("2026-06-01", True),
        ("2027-05-31", True),
        ("2027-06-01", False),
    ],
)
def test_supply_effective_boundaries(date, valid):
    start = datetime.fromisoformat(date).replace(tzinfo=CHICAGO)
    if valid:
        assert read(start, plan="comed_time_of_day").complete
    else:
        with pytest.raises(AdapterError, match="validity"):
            read(start, plan="comed_time_of_day")


def test_delivery_history_limit_and_pinned_until_replaced():
    def empty(request):
        return httpx.Response(200, text="[]")

    with pytest.raises(AdapterError, match="validity"):
        read(datetime(2026, 5, 31, tzinfo=CHICAGO), handler=empty)
    assert not read(
        datetime(2026, 5, 31, tzinfo=CHICAGO), supply=True, handler=empty
    ).complete
    assert read(datetime(2027, 8, 1, tzinfo=CHICAGO), handler=empty).tariff_version
    result = read(
        START.replace(month=9, day=30, hour=23),
        START.replace(month=10, day=1, hour=1),
        plan="comed_time_of_day",
    )
    assert [s.import_cents_per_kwh for s in result.slots] == [
        Decimal("6.174"),
        Decimal("6.739"),
    ]
    with pytest.raises(AdapterError):
        read(
            datetime(2027, 5, 31, 23, 30, tzinfo=CHICAGO),
            datetime(2027, 6, 1, 0, 30, tzinfo=CHICAGO),
            plan="comed_time_of_day",
        )


@pytest.mark.parametrize("day,hours", [("2026-03-08", 23), ("2025-11-02", 25)])
def test_day_ahead_dst_recordings(day, hours):
    start = datetime.fromisoformat(day).replace(tzinfo=CHICAGO)
    name = "dayahead-spring.txt" if hours == 23 else "dayahead-fall.txt"

    def handler(request):
        return httpx.Response(200, content=(FIXTURES / name).read_bytes())

    result = read(start, supply=True, handler=handler)
    assert len(result.slots) == 23
    assert result.complete == (hours == 23)
    if hours == 25:
        assert len(result.gaps) == 1 and result.gaps[0].end - result.gaps[
            0
        ].start == timedelta(hours=2)
        assert "ambiguous" in result.gaps[0].reason
    assert (
        result.tariff_version is None
        and "publication time unknown" in result.source_label
    )
    assert sum((s.end - s.start for s in result.slots), timedelta()) + sum(
        (g.end - g.start for g in result.gaps), timedelta()
    ) == timedelta(hours=hours)


@pytest.mark.parametrize(
    "day,name",
    [("2026-03-08", "realtime-spring.json"), ("2025-11-02", "realtime-fall.json")],
)
def test_realtime_dst_inclusive_utc_filtering(day, name):
    start = datetime.fromisoformat(day).replace(tzinfo=CHICAGO)
    end = start + timedelta(days=1)

    def handler(request):
        assert request.url.params["datestart"] == start.strftime("%Y%m%d") + "0000"
        assert request.url.params["dateend"] == end.strftime("%Y%m%d") + "0000"
        return httpx.Response(200, content=(FIXTURES / name).read_bytes())

    result = read(start, end, kind="realtime", supply=True, handler=handler)
    raw = json.loads((FIXTURES / name).read_text())
    expected = {
        datetime.fromtimestamp(int(r["millisUTC"]) / 1000, UTC)
        for r in raw
        if start.astimezone(UTC).timestamp() * 1000
        <= int(r["millisUTC"])
        < end.astimezone(UTC).timestamp() * 1000
    }
    assert {s.start for s in result.slots} == expected
    assert "not finalized" in result.source_label


def test_recorded_and_clipped_prices_supply_basis():
    result = read(
        START + timedelta(minutes=2), START + timedelta(minutes=13), kind="realtime"
    )
    assert len(result.slots) == 3 and result.complete
    assert result.slots[0].start == START + timedelta(minutes=2)
    assert result.slots[-1].end == START + timedelta(minutes=13)
    supply = read(
        START + timedelta(minutes=2),
        START + timedelta(minutes=13),
        kind="realtime",
        supply=True,
    )
    assert all(
        a.import_cents_per_kwh - b.import_cents_per_kwh == Decimal("6.333")
        for a, b in zip(result.slots, supply.slots)
    )
    assert read(
        START, START + timedelta(minutes=13), kind="realtime", plan="comed_time_of_day"
    ).complete
    assert len(read().slots) == 24


@pytest.mark.parametrize("kind", ["realtime", "day_ahead"])
def test_missing_and_null_prices_are_gaps(kind):
    for body in (
        "[]",
        '[{"millisUTC":"1785560400000","price":null}]'
        if kind == "realtime"
        else "[[Date.UTC(2026,7,1,0,0,0), null]]",
    ):
        result = read(kind=kind, handler=lambda request: httpx.Response(200, text=body))
        assert not result.complete and not result.slots and len(result.gaps) == 1
        assert result.gaps[0].start == START and result.gaps[
            0
        ].end == START + timedelta(days=1)


@pytest.mark.parametrize("kind", ["realtime", "day_ahead"])
def test_negative_and_duplicate_prices(kind):
    row = (
        '{"millisUTC":"1785560400000","price":"-10.5"}'
        if kind == "realtime"
        else "[Date.UTC(2026,7,1,0,0,0), -10.5]"
    )
    result = read(
        kind=kind, handler=lambda request: httpx.Response(200, text=f"[{row},{row}]")
    )
    assert result.slots[0].import_cents_per_kwh == Decimal("-4.167")
    assert len(result.slots) == 1
    with pytest.raises(AdapterUnavailable, match="Invalid ComEd"):
        read(
            kind=kind,
            handler=lambda request: httpx.Response(
                200, text=f"[{row},{row.replace('-10.5', '-10.4')}]"
            ),
        )


@pytest.mark.parametrize(
    "body",
    [
        "{}",
        "null",
        "[1]",
        '[{"millisUTC":"1785560400001","price":"1"}]',
        '[{"millisUTC":true,"price":"1"}]',
        '[{"millisUTC":"bad","price":"1"}]',
        '[{"millisUTC":"1785560400000","price":"NaN"}]',
        '[{"millisUTC":"1785560400000","price":true}]',
        '[{"millisUTC":"1785560400000","price":"3 USD"}]',
        '[{"millisUTC":"1785560400000","price":"1","unit":"dollars"}]',
        '[{"millisUTC":"999999999999999999999999900000","price":"1"}]',
    ],
)
def test_invalid_realtime_contract(body):
    with pytest.raises(AdapterUnavailable, match="Invalid ComEd"):
        read(kind="realtime", handler=lambda request: httpx.Response(200, text=body))


@pytest.mark.parametrize(
    "body",
    [
        "alert(1)",
        "[]; process.exit()",
        "[[Date.UTC(2026,7,1,0,0,0), (function(){return 1})()]]",
        "[[Date.UTC(2026,7,1,0,0,0), NaN]]",
        "[[Date.UTC(2026,7,1,24,0,0), 1]]",
        "[[Date.UTC(2026,7,2,0,0,0), 1]]",
        "[[Date.UTC(2026,7,1,0,1,0), 1]]",
        "[[[2026,7,1,0],1]]",
    ],
)
def test_javascript_is_data_never_executed(body):
    with pytest.raises(AdapterUnavailable, match="Invalid ComEd"):
        read(handler=lambda request: httpx.Response(200, text=body))


def test_spring_nonexistent_label_rejected():
    with pytest.raises(ValueError, match="Nonexistent"):
        feeds.day_ahead("[[Date.UTC(2026,2,8,2,0,0), 1]]", datetime(2026, 3, 8).date())


@pytest.mark.parametrize("failure", ["timeout", "http", "second_day"])
def test_request_failure_fails_whole_read_without_retry(failure):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.extensions["timeout"] == dict(
            connect=10, read=10, write=10, pool=10
        )
        if failure == "second_day" and len(calls) == 1:
            return recorded(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("private upstream text")
        return httpx.Response(503, text="private upstream text")

    with pytest.raises(AdapterUnavailable, match="^Energy feed request failed.$"):
        read(end=START + timedelta(days=2), handler=handler)
    assert len(calls) == (2 if failure == "second_day" else 1)


@pytest.mark.parametrize(
    "start,end,kind",
    [
        (START, START, "day_ahead"),
        (START.replace(tzinfo=None), START + timedelta(days=1), "day_ahead"),
        (START, START + timedelta(days=367), "day_ahead"),
        (START, START + timedelta(days=1), "invalid"),
    ],
)
def test_invalid_requests_never_fetch(start, end, kind):
    def fail(request):
        pytest.fail("invalid input fetched")

    with pytest.raises(AdapterError):
        read(start, end, kind, handler=fail)


@pytest.mark.parametrize("plan", [None, "twin"])
def test_unsupported_plan(plan):
    with pytest.raises(AdapterError):
        adapter(plan)


def test_class_tariff_and_missing_location():
    for cls in ("", "residential_multifamily", "auto"):
        with pytest.raises(AdapterError):
            RealEnergy(home(), delivery_class=cls, tariff_path=TARIFF)
    with pytest.raises(AdapterError):
        load_tariff(Path("absent-tariff.yaml"))
    a = RealEnergy(
        home(location=False),
        delivery_class=DELIVERY_CLASS,
        tariff_path=TARIFF,
        transport=httpx.MockTransport(recorded),
    )

    async def run():
        assert "get_weather" not in a.capabilities
        await a.start()
        try:
            assert (
                await a.get_prices(START, START + timedelta(days=1), "day_ahead")
            ).slots
            with pytest.raises(AdapterUnavailable):
                await a.get_weather(NOW, NOW + timedelta(hours=1))
        finally:
            await a.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(unit="dollars"),
        lambda d: d["rows"].pop(),
        lambda d: d["rows"][0].update(start_hour=7),
        lambda d: d["rows"][0].update(billing_end=None),
        lambda d: d["rows"][0].update(source_url="unknown"),
        lambda d: d["rows"][0].update(cents_per_kwh="Infinity"),
    ],
)
def test_malformed_tariff_fails_safely(tmp_path, mutate):
    body = yaml.safe_load(TARIFF.read_text())
    mutate(body)
    path = tmp_path / "tariff.yaml"
    path.write_text(yaml.safe_dump(body))
    with pytest.raises(AdapterError, match="Invalid or unreadable"):
        load_tariff(path)


def weather_read(body=None, start=NOW, end=None, handler=None):
    async def run():
        a = adapter(
            handler=handler
            or (
                recorded
                if body is None
                else lambda request: httpx.Response(200, json=body)
            )
        )
        await a.start()
        try:
            return await a.get_weather(start, end or start + timedelta(hours=3))
        finally:
            await a.close()

    return asyncio.run(run())


def test_weather_recorded_coordinates_units_horizon_and_clipping():
    def handler(request):
        assert request.url.params["latitude"] == "41.8781"
        assert request.url.params["longitude"] == "-87.6298"
        assert request.url.params["timezone"] == "UTC"
        assert request.url.params["temperature_unit"] == "fahrenheit"
        assert request.url.params["forecast_days"] == "16"
        return recorded(request)

    result = weather_read(start=NOW + timedelta(minutes=17), handler=handler)
    assert (
        result.complete
        and len(result.samples) == 4
        and result.samples[0].at == NOW + timedelta(minutes=17)
    )
    raw = feeds.weather((FIXTURES / "weather.json").read_text())
    assert result.samples[0].temp_f == raw[NOW].temp_f
    assert (
        result.source == "real"
        and result.retrieved_at == NOW
        and result.tariff_version is None
    )
    assert weather_read(
        start=NOW.replace(hour=0), end=NOW.replace(hour=0) + timedelta(days=16)
    ).complete
    for start, end in [
        (NOW - timedelta(days=1), NOW),
        (NOW, NOW.replace(hour=0) + timedelta(days=16, seconds=1)),
        (NOW.replace(tzinfo=None), NOW),
    ]:
        with pytest.raises(AdapterError):
            weather_read(start=start, end=end)


def test_missing_weather_hours_do_not_carry_across_gaps():
    body = json.loads((FIXTURES / "weather.json").read_text())
    at = body["hourly"]["time"].index("2026-09-20T16:00")
    body["hourly"]["temperature_2m"][at] = None
    result = weather_read(body, start=NOW + timedelta(minutes=30))
    assert not result.complete and len(result.gaps) == 1
    assert result.gaps[0].start == NOW + timedelta(hours=1)
    assert result.gaps[0].end == NOW + timedelta(hours=2)
    assert result.samples[1].at == NOW + timedelta(hours=2)
    for values in body["hourly"].values():
        values.clear()
    assert len(weather_read(body).gaps) == 1


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b.update(utc_offset_seconds=3600),
        lambda b: b["hourly_units"].update(temperature_2m="°C"),
        lambda b: b["hourly"]["time"].append("bad"),
        lambda b: b["hourly"]["time"].__setitem__(0, "2026-09-20T00:05"),
        lambda b: b["hourly"]["temperature_2m"].__setitem__(0, float("inf")),
        lambda b: b["hourly"]["cloud_cover"].__setitem__(0, 101),
    ],
)
def test_invalid_weather(mutate):
    body = json.loads((FIXTURES / "weather.json").read_text())
    mutate(body)
    with pytest.raises(AdapterUnavailable, match="Invalid Open-Meteo"):
        weather_read(handler=lambda request: httpx.Response(200, text=json.dumps(body)))


def test_weather_duplicate_conflict_and_missing_keys():
    body = json.loads((FIXTURES / "weather.json").read_text())
    for values in body["hourly"].values():
        values.append(values[0])
    assert weather_read(body).complete
    body["hourly"]["temperature_2m"][-1] += 1
    with pytest.raises(AdapterUnavailable):
        weather_read(body)
    with pytest.raises(AdapterUnavailable):
        weather_read({"utc_offset_seconds": 0, "hourly_units": body["hourly_units"]})


def test_lifecycle_registry_isolation_and_explicit_twin_bindings():
    async def run():
        world = demo_world()
        h = Household.model_validate(
            world.household.model_dump() | {"rate_plan": "comed_time_of_day"}
        )
        real_factory = factories(delivery_class=DELIVERY_CLASS, tariff_path=TARIFF)
        with pytest.raises(AdapterError):
            twin_factories(world)[("energy", "twin")](
                h.model_copy(update={"timezone": "UTC"})
            )
        reg = Registry(
            h,
            members=tuple(world.members.values()),
            assets=tuple(world.assets.values()),
            bindings=tuple(
                b
                for b in world.bindings.values()
                if world.assets[b.asset_id].kind in ("home_battery", "solar")
            ),
            factories=real_factory | twin_factories(world),
            sources={("energy", "real", h.id): "real"},
            config="energy:real",
        )
        other = real_factory[("energy", "real")](home("comed_time_of_day"))
        await reg.start()
        await other.start()
        try:
            real = reg.resolve("energy")
            real.clock = other.clock = lambda: NOW
            twin = reg.instances[("energy", "twin")]
            assert real.household_id != other.household_id
            row = await real.get_tariff_state()
            assert reg.stamp("energy", "real", row, at=row.observed_at) == row
            assert row.state.price_band in (
                "morning",
                "mid_day_peak",
                "evening",
                "overnight",
            )
            for b in reg.bindings.values():
                assert reg.resolve("energy", asset_id=b.asset_id) is twin
                method = (
                    twin.get_battery
                    if world.assets[b.asset_id].kind == "home_battery"
                    else twin.get_solar
                )
                observation = await method(b.entity_id)
                assert observation.source == "twin"
                assert (
                    reg.stamp("energy", "twin", observation, at=observation.observed_at)
                    == observation
                )
            assert "has_export_price" not in real.capabilities
            for name in ("get_battery", "get_solar"):
                with pytest.raises(AdapterUnavailable):
                    await getattr(real, name)("any")
            with pytest.raises(AdapterUnavailable):
                await real.dispatch_battery(None, None)
            with pytest.raises(AdapterUnavailable):
                reg.resolve("energy", capability="dispatch_battery")
            with pytest.raises(AdapterError):
                await real.start()
            with pytest.raises(AdapterError):
                reg.stamp(
                    "energy", "real", await other.get_tariff_state(), at=row.observed_at
                )
        finally:
            await reg.close()
            await other.close()
        assert real.client is None and not twin.started
        with pytest.raises(AdapterUnavailable):
            await real.get_prices(START, START + timedelta(hours=1), "day_ahead")
        await real.close()
        hourly = adapter()
        await hourly.start()
        try:
            assert "get_tariff_state" not in hourly.capabilities
            with pytest.raises(AdapterUnavailable):
                await hourly.get_tariff_state()
        finally:
            await hourly.close()

    asyncio.run(run())


def test_series_completeness_is_derived_from_coverage():
    data = read().model_dump(exclude={"complete"})
    data["slots"] = ()
    with pytest.raises(ValueError):
        PriceSeries.model_validate(data)
    data["gaps"] = (Gap(start=START, end=START + timedelta(days=1), reason="missing"),)
    assert not PriceSeries.model_validate(data).complete
    w = weather_read().model_dump(exclude={"complete"})
    w["samples"] = ()
    with pytest.raises(ValueError):
        WeatherSeries.model_validate(w)


def test_recorded_smoke(capsys):
    asyncio.run(smoke(live=False, history_month="2026-08", tariff_path=TARIFF))
    output = capsys.readouterr().out
    assert "RECORDED" in output and "export=None" in output and "count=24" in output


@pytest.mark.parametrize("day,hours", [("2026-11-01", 25), ("2027-03-14", 23)])
@pytest.mark.parametrize("kind,per_hour", [("day_ahead", 1), ("realtime", 12)])
def test_static_tariff_dst_is_complete_without_fetch(day, hours, kind, per_hour):
    start = datetime.fromisoformat(day).replace(tzinfo=CHICAGO)

    def fail(request):
        pytest.fail("Static tariffs must not fetch")

    result = read(start, kind=kind, plan="comed_time_of_day", handler=fail)
    assert len(result.slots) == hours * per_hour and result.complete
    assert sum((s.end - s.start for s in result.slots), timedelta()) == timedelta(
        hours=hours
    )


@pytest.mark.parametrize("latitude,longitude", [(91, 0), (0, -181), (float("nan"), 0)])
def test_invalid_coordinates_rejected(latitude, longitude):
    with pytest.raises(ValueError):
        Location(latitude=latitude, longitude=longitude, source="declared")


def test_daily_inclusive_duplicates_collapse_across_requests():
    midnight = START + timedelta(days=1)
    millis = int(midnight.timestamp() * 1000)
    row = {"millisUTC": str(millis), "price": "-8"}
    seen = []

    def handler(request):
        seen.append(request.url.params["datestart"])
        return httpx.Response(200, json=[row])

    result = read(START, START + timedelta(days=2), "realtime", handler=handler)
    assert seen == ["202608010000", "202608020000"]
    assert len(result.slots) == 1 and result.slots[0].start == midnight
    assert result.slots[0].import_cents_per_kwh == Decimal("-1.667")


def test_twin_series_provenance_and_unaligned_weather():
    from hirz.adapters.energy.twin import TwinEnergy
    from scripts.smoke_twin import START as twin_start

    async def run():
        twin = TwinEnergy(demo_world())
        await twin.start()
        try:
            prices = await twin.get_prices(
                twin_start, twin_start + timedelta(hours=2), "day_ahead"
            )
            weather = await twin.get_weather(
                twin_start + timedelta(minutes=17), twin_start + timedelta(hours=2)
            )
            for series in (prices, weather):
                assert series.complete and series.source == "twin"
                assert series.retrieved_at is None and series.tariff_version is None
                assert series.source_urls == ()
            assert weather.samples[0].at == twin_start + timedelta(minutes=17)
        finally:
            await twin.close()

    asyncio.run(run())


def test_unpublished_future_day_has_gaps_without_substitution():
    result = read(
        NOW + timedelta(days=3), handler=lambda request: httpx.Response(200, text="[]")
    )
    assert not result.complete and len(result.gaps) == 1 and result.kind == "day_ahead"
    assert not result.slots


def test_numeric_overflow_and_deeply_malformed_feed_fail_safely():
    body = '[{"millisUTC":"1785560400000","price":"922337203685477.5807"}]'
    with pytest.raises(AdapterUnavailable, match="numeric range"):
        read(kind="realtime", handler=lambda request: httpx.Response(200, text=body))
    with pytest.raises(AdapterUnavailable, match="Invalid ComEd"):
        read(
            kind="realtime",
            handler=lambda request: httpx.Response(200, text="[" * 2000),
        )
