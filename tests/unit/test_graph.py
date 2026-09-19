"""Graph contracts without a database; SQL history semantics also run on PostgreSQL."""

import argparse
import asyncio
import json
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import yaml
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import ProgrammingError

from hirz import cli, db
from hirz.constitution.conditions import attribute, number
from hirz.graph.context import ContextService, project, validate_snapshot
from hirz.graph.models import (
    AssetPolicy,
    GraphError,
    Household,
    Observation,
    ObservationState,
    Preference,
    ScheduleEvent,
    utc,
)
from hirz.graph.repository import GraphRepository, row_model, row_values, snapshot_sql
from hirz.graph.seeds import Seed, demo_id, read_seed

AT = datetime(2026, 9, 18, 12, tzinfo=UTC)
HOME = read_seed(Path("constitutions/quinn-home.yaml"))
PARENTS = read_seed(Path("constitutions/quinn-parents.yaml"))


def result(row):
    return SimpleNamespace(mappings=lambda: SimpleNamespace(one_or_none=lambda: row))


def raw_context(seed=HOME):
    data = {}
    for name, models in seed.models(AT).items():
        if name == "member_accounts":
            continue
        data[name] = []
        for model in models:
            row = model.model_dump(mode="json", exclude_none=True)
            row.pop("safe_word_hash", None)
            row.pop("value_hash", None)
            data[name].append(row | {"valid_from": AT.isoformat(), "valid_to": None})
    return data


def connection(row=None):
    conn = MagicMock()
    conn.execute = AsyncMock(return_value=result(row))
    conn.scalar = AsyncMock(return_value=None)
    conn.begin.return_value.__aenter__ = AsyncMock()
    conn.begin.return_value.__aexit__ = AsyncMock(return_value=False)
    return conn


def test_seed_facts_and_private_data():
    first, second = HOME.models(AT), PARENTS.models(AT)
    assert len(first["members"]) == 3 and len(first["assets"]) == 9
    assert len(second["members"]) == 2 and len(second["assets"]) == 2
    assert HOME.version == 7 and PARENTS.version == 1
    assert "never_for" not in HOME.constitution["autonomy"]["security"]["door_unlock"]
    assert PARENTS.constitution["autonomy"]["security"]["door_unlock"]["never_for"] == [
        "unexpected_visitor"
    ]
    assert not first["observations"] and not second["observations"]
    assert second["trusted_contacts"][0].member_id is None
    assert second["contact_channels"][0].verified_at == AT
    assert first["preferences"][0].value == 72
    arrival = first["schedule_events"][0]
    assert arrival.starts_at.hour == 18 and arrival.starts_at.minute == 45
    assert arrival.ends_at.hour == 19 and arrival.ends_at.minute == 15
    assert first["households"][0].rate_plan == "comed_time_of_day"
    assert second["households"][0].rate_plan == "twin"
    assert demo_id("quinn-home", "members", "mom") != demo_id(
        "quinn-parents", "members", "mom"
    )
    for seed in (HOME, PARENTS):
        serialized = json.dumps(validate_snapshot(raw_context(seed), seed.household_id))
        assert all(
            key not in serialized
            for key in ("value_hash", "safe_word_hash", '"sub"', '"provider"')
        )


@pytest.mark.parametrize(
    "text",
    [
        "a: 1\na: 2",
        "[]\n---\n{}",
        "{}",
        "!!python/object:evil {}",
        "[oops",
        "{}\n---\n{}\n---\n{}",
    ],
)
def test_invalid_yaml_is_safe(tmp_path, text):
    path = tmp_path / "bad.yaml"
    path.write_text(text)
    with pytest.raises(GraphError) as exc:
        read_seed(path)
    assert "evil" not in str(exc.value)


@pytest.mark.parametrize(
    "change",
    [
        lambda g: g.update(unrecognized=True),
        lambda g: g["household"].update(slug="other"),
        lambda g: g["household"].update(timezone="not/a/zone"),
        lambda g: g["members"][0].update(role="admin"),
        lambda g: g["member_accounts"][0].update(provider="amazon"),
        lambda g: g["asset_bindings"][0].update(adapter="ha"),
        lambda g: g["asset_bindings"][0].update(asset_id="absent"),
        lambda g: g["members"].append(g["members"][0].copy()),
        lambda g: g.update(observations=[{"id": "initial"}]),
        lambda g: g.update(members={}),
    ],
)
def test_seed_validation(tmp_path, change):
    graph = deepcopy(HOME.graph)
    change(graph)
    path = tmp_path / "seed.yaml"
    path.write_text(yaml.safe_dump_all([graph, HOME.constitution]))
    with pytest.raises(GraphError):
        read_seed(path)


@pytest.mark.parametrize(
    "rules",
    [
        {"household": "wrong", "version": 7},
        {"household": "quinn-home", "version": True},
    ],
)
def test_bad_constitution_envelope(rules):
    with pytest.raises(GraphError):
        Seed(HOME.graph, rules)


def test_model_time_and_bounds():
    with pytest.raises(GraphError):
        utc(datetime(2026, 9, 18))
    home = HOME.models(AT)["households"][0]
    for changes in (
        {"rate_plan": "invented"},
        {"timezone": "not/a/zone"},
        {"unexpected": 1},
    ):
        with pytest.raises(ValidationError):
            Household.model_validate(home.model_dump() | changes)
    event = HOME.models(AT)["schedule_events"][0].model_dump()
    for changes in ({"ends_at": event["starts_at"]}, {"expected_at": event["ends_at"]}):
        with pytest.raises(ValidationError):
            ScheduleEvent.model_validate(event | changes)
    pref = HOME.models(AT)["preferences"][0].model_dump()
    with pytest.raises(ValidationError):
        Preference.model_validate(pref | {"value": True})
    with pytest.raises(ValidationError):
        Observation(
            id=uuid4(),
            household_id=HOME.household_id,
            member_id=uuid4(),
            asset_id=uuid4(),
            observed_at=AT,
            source="twin",
            state={},
        )


def test_policy_fact_quantization():
    state = ObservationState(
        soc=0.1 + 0.2, temp_f=71.123456, target_f=72.123456, power_kw=1.123456
    )
    assert state.soc == 0.3
    assert state.temp_f == 71.1235
    assert state.target_f == 72.1235
    assert state.power_kw == 1.1235
    policy = AssetPolicy(
        household_id=HOME.household_id, id=uuid4(), asset_id=uuid4(), soc_min=0.1 + 0.2
    )
    assert policy.soc_min == 0.3
    pref = HOME.models(AT)["preferences"][0].model_dump()
    assert Preference.model_validate(pref | {"value": 71.123456}).value == 71.1235
    assert Preference.model_validate(pref | {"value": 72}).value == 72.0
    assert (
        Preference.model_validate(pref | {"key": "other", "value": 71.123456}).value
        == 71.123456
    )
    with pytest.raises(ValueError):
        number(71.123456)


@pytest.mark.parametrize("value", [1e15, -1e15, float("inf"), float("nan"), True])
def test_policy_fact_rejects_invalid_numbers(value):
    for field in ("soc", "temp_f", "target_f", "power_kw"):
        with pytest.raises(ValidationError):
            ObservationState.model_validate({field: value})
    pref = HOME.models(AT)["preferences"][0].model_dump()
    with pytest.raises(ValidationError):
        Preference.model_validate(pref | {"value": value})


@given(
    st.floats(min_value=-1000, max_value=1000, allow_nan=False, allow_infinity=False)
)
def test_stored_temperature_is_a_policy_fact(value):
    stored = ObservationState(temp_f=value).temp_f
    assert attribute(
        {"asset": {"state": {"temp_f": stored}}}, "asset.state.temp_f"
    ) == number(stored)


def test_quantized_observation_write_is_noop():
    async def run():
        conn = connection()
        repository = GraphRepository(conn, HOME.household_id)
        observation = Observation(
            id=uuid4(),
            household_id=HOME.household_id,
            observed_at=AT,
            source="twin",
            domain="energy",
            state={"soc": 0.30000000000000004},
        )
        async with repository.write(lambda: AT):
            assert await repository.put("observations", observation)
        stored = row_values("observations", observation) | {"valid_from": AT}
        assert stored["attributes"]["state"]["soc"] == 0.3
        conn.execute.return_value = result(stored)
        conn.execute.reset_mock()
        async with repository.write(lambda: AT + timedelta(seconds=1)):
            assert not await repository.put(
                "observations",
                Observation.model_validate(
                    observation.model_dump() | {"state": {"soc": 0.3}}
                ),
                expected_version=AT,
            )
        assert conn.execute.await_count == 2  # Lock and read, no write or refresh.

    asyncio.run(run())


def test_scope_projection():
    data = validate_snapshot(raw_context(), HOME.household_id)
    member = demo_id("quinn-home", "members", "mom")
    assert len(project(data, "member", member)["preferences"]) == 1
    assert len(project(data, "people", None)["members"]) == 3
    assert len(project(data, "energy", None)["assets"]) == 4
    assert len(project(data, "environment", None)["assets"]) == 5
    assert project(data, "all", None) == data
    with pytest.raises(GraphError, match="Member not found"):
        project(data, "member", uuid4())
    copy = project(data, "all", None)
    copy["households"][0]["name"] = "mutated"
    assert data["households"][0]["name"] != "mutated"


def test_context_cache_and_history_contract():
    async def run():
        clock = AT + timedelta(hours=1)
        raw = raw_context()
        raw["observations"].append(
            {
                "id": str(uuid4()),
                "household_id": str(HOME.household_id),
                "member_id": str(demo_id("quinn-home", "members", "mom")),
                "source": "twin",
                "observed_at": AT.isoformat(),
                "state": {"present": True},
                "valid_from": AT.isoformat(),
                "valid_to": None,
            }
        )
        conn = connection({"data": raw})
        service = ContextService(conn, lambda: clock)
        first = await service.get_household_context(HOME.household_id)
        assert first.data["observations"][0]["staleness_seconds"] == 3600
        assert not first.stale and conn.execute.await_count == 1
        first.data["households"][0]["name"] = "cannot poison cache"
        conn.execute.side_effect = OSError("unavailable")
        clock += timedelta(seconds=12)
        stale = await service.get_household_context(HOME.household_id, allow_stale=True)
        assert stale.stale and stale.staleness_seconds == 12
        assert stale.data["households"][0]["name"] != "cannot poison cache"
        assert stale.data["observations"][0]["staleness_seconds"] == 3612
        for kwargs in ({}, {"as_of": AT, "allow_stale": True}):
            with pytest.raises(OSError):
                await service.get_household_context(HOME.household_id, **kwargs)
        with pytest.raises(OSError):
            await service.get_household_context(PARENTS.household_id, allow_stale=True)
        conn.execute.side_effect = ProgrammingError("private", {}, Exception("bad SQL"))
        with pytest.raises(ProgrammingError):
            await service.get_household_context(HOME.household_id, allow_stale=True)
        conn.execute.side_effect = None
        conn.execute.return_value = result({"data": raw})
        historical = await service.get_household_context(HOME.household_id, as_of=AT)
        query, params = conn.execute.call_args.args
        assert "UNION ALL" in str(query) and ":as_of < valid_to" in str(query)
        assert (
            params["as_of"] == AT
            and historical.data["observations"][0]["staleness_seconds"] == 0
        )
        for kwargs in (
            {"as_of": clock + timedelta(seconds=1)},
            {"scope": "member"},
            {"member_id": uuid4()},
            {"scope": "plan"},
        ):
            with pytest.raises(GraphError):
                await service.get_household_context(HOME.household_id, **kwargs)
        conn.execute.return_value = result(None)
        with pytest.raises(GraphError, match="not found"):
            await service.get_household_context(HOME.household_id)
        assert HOME.household_id not in service._cache

    asyncio.run(run())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(member_accounts=[]),
        lambda d: d.update(members={}),
        lambda d: d["members"][0].update(sub="secret"),
        lambda d: d["members"][0].update(household_id=str(uuid4())),
        lambda d: d["members"][0].pop("valid_from"),
        lambda d: d["members"][0].update(valid_to=AT.isoformat()),
        lambda d: d.update(households=[]),
    ],
)
def test_malformed_snapshot_never_qualifies_for_fallback(mutate):
    async def run():
        conn = connection({"data": raw_context()})
        service = ContextService(conn, lambda: AT)
        await service.get_household_context(HOME.household_id)
        broken = raw_context()
        mutate(broken)
        conn.execute.return_value = result({"data": broken})
        with pytest.raises((GraphError, ValidationError)):
            await service.get_household_context(HOME.household_id, allow_stale=True)

    asyncio.run(run())


def test_repository_past_query_and_transactions():
    async def run():
        conn = connection()
        repository = GraphRepository(conn, HOME.household_id)
        model = HOME.models(AT)["members"][0]
        stored = row_values("members", model) | {"valid_from": AT, "valid_to": None}
        conn.execute.return_value = result(stored)
        assert (
            await repository.get(
                "members", {"id": model.id}, as_of=AT, clock=lambda: AT
            )
            == stored
        )
        query = conn.execute.call_args.args[0].compile(dialect=postgresql.dialect())
        assert "UNION ALL" in str(query) and "members_history.valid_to >" in str(query)
        assert HOME.household_id in query.params.values()
        assert row_model("members", stored) == model
        for name, key in (("unknown", {}), ("members", {})):
            with pytest.raises(GraphError):
                await repository.get(name, key)
        with pytest.raises(GraphError):
            await repository.get(
                "members",
                {"id": model.id},
                as_of=AT + timedelta(seconds=1),
                clock=lambda: AT,
            )
        with pytest.raises(GraphError):
            await repository.put("members", model)
        repository.get = AsyncMock(return_value=None)
        async with repository.write(lambda: AT):
            assert await repository.put("members", model)
            with pytest.raises(GraphError, match="Nested"):
                async with repository.write(lambda: AT):
                    pass
        assert "REFRESH MATERIALIZED VIEW" in str(conn.execute.call_args.args[0])
        repository.get.return_value = stored
        async with repository.write(lambda: AT + timedelta(seconds=1)):
            assert not await repository.put("members", model, expected_version=AT)
            changed = model.model_copy(update={"display_name": "New name"})
            assert await repository.put("members", changed, expected_version=AT)
            with pytest.raises(GraphError, match="version conflict"):
                await repository.put("members", changed)
        async with repository.write(lambda: AT):
            with pytest.raises(GraphError, match="later timestamp"):
                await repository.put("members", changed, expected_version=AT)
            with pytest.raises(GraphError, match="belong"):
                await repository.put(
                    "members", model.model_copy(update={"household_id": uuid4()})
                )
            with pytest.raises(GraphError, match="Wrong graph model"):
                await repository.put("assets", model)
        assert repository._at is None

    asyncio.run(run())


def test_snapshot_sql_projection():
    public = snapshot_sql()
    assert "FROM member_accounts x" not in public
    assert "- 'safe_word_hash' - 'value_hash'" in public
    assert "FROM member_accounts x" in snapshot_sql(private=True)
    assert set(db.GRAPH_TABLES) == set(db.HISTORY_TABLES)


def test_graph_cli_arguments_and_safe_errors(monkeypatch, capsys):
    for argv in (
        ["hirz", "context", str(HOME.household_id), "--scope", "member"],
        ["hirz", "context", str(HOME.household_id), "--as-of", "2026-09-18"],
    ):
        monkeypatch.setattr("sys.argv", argv)
        with pytest.raises(SystemExit) as error:
            cli.main()
        assert error.value.code == 2
    assert cli.aware_timestamp("2026-09-18T00:00:00Z").tzinfo == UTC
    monkeypatch.setattr(cli, "read_env", lambda _: {})

    @asynccontextmanager
    async def connect(_):
        yield connection({"data": raw_context()})

    monkeypatch.setattr(cli, "connect_database", connect)
    monkeypatch.setattr("sys.argv", ["hirz", "context", str(HOME.household_id)])
    assert cli.main() == 0
    assert json.loads(capsys.readouterr().out)["policy_status"] == "unvalidated"
    monkeypatch.setattr(
        cli, "load_seeds", AsyncMock(return_value=[{"status": "loaded"}])
    )
    monkeypatch.setattr("sys.argv", ["hirz", "seed", "constitutions/quinn-home.yaml"])
    assert cli.main() == 0
    monkeypatch.setattr(
        cli, "load_seeds", AsyncMock(side_effect=RuntimeError("SECRET"))
    )
    assert cli.main() == 1
    assert "SECRET" not in capsys.readouterr().err
    args = argparse.Namespace(command="seed", paths=[Path("missing-file")])
    assert asyncio.run(cli.graph_command(args)) == 1
