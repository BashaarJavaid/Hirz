"""Item 6 evidence against real PostgreSQL, only in disposable databases."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import event
from test_database import connect, migrate
from test_database import scratch_database as scratch_database

from hirz import db
from hirz.graph.context import ContextService
from hirz.graph.models import GraphError, Observation
from hirz.graph.repository import GraphRepository, row_model
from hirz.graph.seeds import Seed, demo_id, load_seeds, read_seed

pytestmark = pytest.mark.integration
AT = datetime(2026, 9, 18, 12, tzinfo=UTC)
HOME = read_seed(Path("constitutions/quinn-home.yaml"))
PARENTS = read_seed(Path("constitutions/quinn-parents.yaml"))


def test_populated_migration_and_view_presence(scratch_database):
    async def run():
        async with connect(scratch_database) as connection:
            await migrate(connection, target="0001_initial")
            identity = uuid4()
            member = uuid4()
            await connection.execute(
                sa.text(
                    "INSERT INTO households(id,name,timezone,locale) VALUES (:id,'Existing','UTC','en-US')"
                ),
                {"id": identity},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO members(household_id,id,display_name,role) VALUES (:h,:id,'Existing member','adult')"
                ),
                {"h": identity, "id": member},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO member_accounts(household_id,provider,sub,member_id) VALUES (:h,'fixture','existing',:id)"
                ),
                {"h": identity, "id": member},
            )
            await connection.commit()
            await migrate(connection)
            await connection.run_sync(db.require_current)
            drift = await connection.run_sync(
                lambda c: compare_metadata(
                    MigrationContext.configure(
                        c, opts={"compare_server_default": True}
                    ),
                    db.metadata,
                )
            )
            assert drift == []
            repo = GraphRepository(connection, identity)
            row = await repo.get("households", {})
            assert row["rate_plan"] is None and row["valid_from"].tzinfo is not None
            assert (
                await repo.get(
                    "households",
                    {},
                    as_of=row["valid_from"] - timedelta(microseconds=1),
                )
                is None
            )
            context = await ContextService(connection).get_household_context(identity)
            assert context.policy_status == "missing"
            assert context.data["households"][0]["id"] == str(identity)
            assert context.data["members"][0]["id"] == str(member)
            await connection.rollback()
            async with connection.begin():
                await connection.execute(
                    sa.text("DROP MATERIALIZED VIEW household_context")
                )
                with pytest.raises(Exception, match="Migrations"):
                    await connection.run_sync(db.require_current)
                await connection.rollback()
            await migrate(connection, "downgrade", "0001_initial")
            assert await connection.scalar(sa.text("SELECT count(*) FROM members")) == 1
            await connection.rollback()
            await migrate(connection)

    asyncio.run(run())


def test_both_seeds_repeat_context_and_redaction(scratch_database):
    async def run():
        async with connect(scratch_database) as connection:
            await migrate(connection)
            loaded = await load_seeds(connection, [HOME, PARENTS], lambda: AT)
            assert [r["status"] for r in loaded] == ["loaded", "loaded"]
            repeated = await load_seeds(
                connection, [HOME, PARENTS], lambda: AT + timedelta(days=1)
            )
            assert [r["status"] for r in repeated] == ["unchanged", "unchanged"]
            service = ContextService(connection, lambda: AT + timedelta(days=1))
            queries = []

            def record(conn, cursor, statement, parameters, context, many):
                queries.append(statement)

            event.listen(connection.sync_connection, "before_cursor_execute", record)
            first = await service.get_household_context(HOME.household_id)
            assert len(queries) == 1
            second = await service.get_household_context(PARENTS.household_id)
            for snapshot in (first, second):
                text = snapshot.model_dump_json()
                assert not any(
                    key in text
                    for key in ('"sub"', '"provider"', "value_hash", "safe_word_hash")
                )
                assert snapshot.policy_status == "unvalidated"
                assert all(
                    r["valid_from"] == AT.isoformat()
                    for rows in snapshot.data.values()
                    for r in rows
                )
            assert len(first.data["assets"]) == 9 and len(second.data["assets"]) == 2
            assert len(second.data["trusted_contacts"]) == 1
            assert len(second.data["contact_channels"]) == 1
            for scope, count in (("energy", 4), ("environment", 5)):
                snapshot = await service.get_household_context(HOME.household_id, scope)
                assert len(snapshot.data["assets"]) == count
            mom = demo_id("quinn-home", "members", "mom")
            snapshot = await service.get_household_context(
                HOME.household_id, "member", member_id=mom
            )
            assert len(snapshot.data["preferences"]) == 1
            with pytest.raises(GraphError, match="Member not found"):
                await service.get_household_context(
                    PARENTS.household_id, "member", member_id=mom
                )
            assert (
                await connection.scalar(
                    sa.select(sa.func.count()).select_from(db.audit_log)
                )
                == 0
            )
            versions = (
                (await connection.execute(sa.select(db.constitution_versions)))
                .mappings()
                .all()
            )
            assert all(
                v["activated_at"] is None and v["compiled_cedar"] is None
                for v in versions
            )
            for history in db.HISTORY_TABLES.values():
                assert (
                    await connection.scalar(
                        sa.select(sa.func.count()).select_from(history)
                    )
                    == 0
                )

    asyncio.run(run())


def test_past_reads_updates_and_observations(scratch_database):
    async def run():
        async with connect(scratch_database) as connection:
            await migrate(connection)
            await load_seeds(connection, [HOME, PARENTS], lambda: AT)
            repo = GraphRepository(connection, HOME.household_id)
            mom = HOME.models(AT)["members"][1]
            one, two = AT + timedelta(minutes=1), AT + timedelta(minutes=2)
            observation = Observation(
                id=uuid4(),
                household_id=HOME.household_id,
                member_id=mom.id,
                domain="presence",
                observed_at=AT,
                source="twin",
                state={"present": True, "soc": 0.30000000000000004},
            )
            async with repo.write(lambda: one):
                await repo.put(
                    "members",
                    mom.model_copy(update={"display_name": "Mom revised"}),
                    expected_version=AT,
                )
                await repo.put("observations", observation)
            # Complete replacement must clear optional direct fields and JSONB attributes.
            service = ContextService(connection, lambda: two)
            before = await service.get_household_context(
                HOME.household_id, as_of=one - timedelta(microseconds=1)
            )
            boundary = await service.get_household_context(HOME.household_id, as_of=one)
            assert before.data["members"][0:] != boundary.data["members"][0:]
            assert not before.data["observations"]
            assert boundary.data["observations"][0]["staleness_seconds"] == 60
            assert boundary.data["observations"][0]["state"]["soc"] == 0.3
            current = await service.get_household_context(HOME.household_id)
            assert current.data["observations"][0]["staleness_seconds"] == 120
            historical_row = await repo.get(
                "members", {"id": mom.id}, as_of=AT, clock=lambda: two
            )
            assert row_model("members", historical_row) == mom
            await connection.rollback()
            async with repo.write(lambda: two):
                assert not await repo.put(
                    "observations",
                    Observation.model_validate(
                        observation.model_dump()
                        | {"state": {"present": True, "soc": 0.3}}
                    ),
                    expected_version=one,
                )
                await repo.put(
                    "observations",
                    observation.model_copy(
                        update={
                            "observed_at": one,
                            "state": observation.state.model_copy(
                                update={"present": False}
                            ),
                        }
                    ),
                    expected_version=one,
                )
            at_old = await service.get_household_context(HOME.household_id, as_of=one)
            assert at_old.data["observations"][0]["state"]["present"] is True
            at_new = await service.get_household_context(HOME.household_id, as_of=two)
            assert at_new.data["observations"][0]["state"]["present"] is False
            with pytest.raises(GraphError, match="not found"):
                await service.get_household_context(
                    HOME.household_id, as_of=AT - timedelta(microseconds=1)
                )
            await connection.rollback()
            for timestamp, expected, message in (
                (one, one, "version conflict"),
                (one, two, "later timestamp"),
                (two, two, "later timestamp"),
            ):
                with pytest.raises(GraphError, match=message):
                    async with repo.write(lambda: timestamp):
                        await repo.put(
                            "observations", observation, expected_version=expected
                        )
            with pytest.raises(GraphError, match="Out-of-order"):
                async with repo.write(lambda: two + timedelta(seconds=1)):
                    await repo.put("observations", observation, expected_version=two)
            with pytest.raises(GraphError, match="Future observations"):
                async with repo.write(lambda: two + timedelta(seconds=1)):
                    await repo.put(
                        "observations",
                        observation.model_copy(
                            update={"observed_at": two + timedelta(days=1)}
                        ),
                        expected_version=two,
                    )
            with pytest.raises(GraphError, match="evolved"):
                await load_seeds(connection, [HOME], lambda: two)

    asyncio.run(run())


def test_atomic_seed_and_refresh_failures(scratch_database):
    async def run():
        async with connect(scratch_database) as connection:
            await migrate(connection)
            bad_graph = dict(PARENTS.graph)
            bad_graph["asset_bindings"] = [
                dict(PARENTS.graph["asset_bindings"][0], asset_id="absent")
            ]
            bad = Seed(bad_graph, PARENTS.constitution)
            with pytest.raises(GraphError):
                await load_seeds(connection, [HOME, bad], lambda: AT)
            assert (
                await connection.scalar(
                    sa.select(sa.func.count()).select_from(db.households)
                )
                == 0
            )
            await connection.rollback()

            def fail_refresh(conn, cursor, statement, parameters, context, many):
                if statement.startswith("REFRESH MATERIALIZED VIEW"):
                    raise RuntimeError("injected refresh failure")

            event.listen(
                connection.sync_connection, "before_cursor_execute", fail_refresh
            )
            with pytest.raises(RuntimeError, match="injected"):
                await load_seeds(connection, [HOME, PARENTS], lambda: AT)
            event.remove(
                connection.sync_connection, "before_cursor_execute", fail_refresh
            )
            assert (
                await connection.scalar(
                    sa.select(sa.func.count()).select_from(db.households)
                )
                == 0
            )
            assert (
                await connection.scalar(
                    sa.text("SELECT count(*) FROM household_context")
                )
                == 0
            )
            await connection.rollback()
            await load_seeds(connection, [HOME], lambda: AT)
            changed = dict(HOME.graph)
            changed["household"] = dict(changed["household"], name="Changed")
            with pytest.raises(GraphError, match="differs"):
                await load_seeds(
                    connection, [PARENTS, Seed(changed, HOME.constitution)], lambda: AT
                )
            assert (
                await connection.scalar(
                    sa.select(sa.func.count()).select_from(db.households)
                )
                == 1
            )

    asyncio.run(run())


def test_concurrent_versions_and_cross_household_foreign_keys(scratch_database):
    async def run():
        async with connect(scratch_database) as connection:
            await migrate(connection)
            await load_seeds(connection, [HOME, PARENTS], lambda: AT)
        mom = HOME.models(AT)["members"][1]

        async def change(name, at):
            async with connect(scratch_database) as connection:
                repo = GraphRepository(connection, HOME.household_id)
                async with repo.write(lambda: at):
                    await repo.put(
                        "members",
                        mom.model_copy(update={"display_name": name}),
                        expected_version=AT,
                    )

        outcomes = await asyncio.gather(
            change("First", AT + timedelta(seconds=1)),
            change("Second", AT + timedelta(seconds=2)),
            return_exceptions=True,
        )
        assert sum(isinstance(r, GraphError) for r in outcomes) == 1
        assert sum(r is None for r in outcomes) == 1
        async with connect(scratch_database) as connection:
            history = db.HISTORY_TABLES["members"]
            assert (
                await connection.scalar(sa.select(sa.func.count()).select_from(history))
                == 1
            )
            current = await ContextService(connection).get_household_context(
                HOME.household_id
            )
            assert any(
                m["display_name"] in {"First", "Second"}
                for m in current.data["members"]
            )
            parent_repo = GraphRepository(connection, PARENTS.household_id)
            assert await parent_repo.get("members", {"id": mom.id}) is None
            await connection.rollback()
            account = PARENTS.models(AT)["member_accounts"][0]
            with pytest.raises(sa.exc.IntegrityError):
                async with parent_repo.write(lambda: AT + timedelta(seconds=3)):
                    await parent_repo.put(
                        "member_accounts",
                        account.model_copy(update={"member_id": mom.id}),
                        expected_version=AT,
                    )
            # No history or updated view escaped the rejected cross-household write.
            assert (
                await connection.scalar(
                    sa.select(sa.func.count()).select_from(
                        db.HISTORY_TABLES["member_accounts"]
                    )
                )
                == 0
            )

    asyncio.run(run())


def test_household_time_optional_clear_and_update_rollback(scratch_database):
    async def run():
        async with connect(scratch_database) as connection:
            await migrate(connection)
            await load_seeds(connection, [HOME, PARENTS], lambda: AT)
            repo = GraphRepository(connection, HOME.household_id)
            ev = HOME.models(AT)["assets"][0]
            later = AT + timedelta(minutes=2)
            async with repo.write(lambda: later):
                await repo.put(
                    "assets",
                    ev.model_copy(update={"owner_member_id": None, "physical": None}),
                    expected_version=AT,
                )
            current = await repo.get("assets", {"id": ev.id})
            assert (
                current["owner_member_id"] is None
                and "physical" not in current["attributes"]
            )
            await connection.rollback()
            # A new row at an old time would retroactively change an already-read snapshot.
            with pytest.raises(GraphError, match="Backdated"):
                async with repo.write(lambda: AT + timedelta(minutes=1)):
                    await repo.put(
                        "observations",
                        Observation(
                            id=uuid4(),
                            household_id=HOME.household_id,
                            asset_id=ev.id,
                            domain="ev",
                            observed_at=AT,
                            source="twin",
                            state={"soc": 0.34},
                        ),
                    )

            def fail_refresh(conn, cursor, statement, parameters, context, many):
                if statement.startswith("REFRESH MATERIALIZED VIEW"):
                    raise RuntimeError("refresh unavailable")

            event.listen(
                connection.sync_connection, "before_cursor_execute", fail_refresh
            )
            with pytest.raises(RuntimeError):
                async with repo.write(lambda: later + timedelta(seconds=1)):
                    await repo.put(
                        "assets",
                        ev.model_copy(update={"name": "Must roll back"}),
                        expected_version=later,
                    )
            event.remove(
                connection.sync_connection, "before_cursor_execute", fail_refresh
            )
            assert (
                await connection.scalar(
                    sa.select(sa.func.count()).select_from(db.HISTORY_TABLES["assets"])
                )
                == 1
            )
            snapshot = await ContextService(connection).get_household_context(
                HOME.household_id
            )
            assert all(a["name"] != "Must roll back" for a in snapshot.data["assets"])
            await connection.rollback()
            parent_repo = GraphRepository(connection, PARENTS.household_id)
            channel = PARENTS.models(AT)["contact_channels"][0]
            with pytest.raises(GraphError, match="Future channel"):
                async with parent_repo.write(lambda: later):
                    await parent_repo.put(
                        "contact_channels",
                        channel.model_copy(
                            update={"verified_at": later + timedelta(days=1)}
                        ),
                        expected_version=AT,
                    )
            with pytest.raises(GraphError, match="Zone"):
                async with repo.write(lambda: later):
                    await repo.put(
                        "observations",
                        Observation(
                            id=uuid4(),
                            household_id=HOME.household_id,
                            member_id=HOME.models(AT)["members"][0].id,
                            domain="presence",
                            observed_at=AT,
                            source="twin",
                            state={"zone_id": PARENTS.models(AT)["assets"][0].id},
                        ),
                    )

    asyncio.run(run())


def test_cli_historical_read_against_disposable_database(
    scratch_database, monkeypatch, capsys
):
    import json

    from hirz import cli

    mom = HOME.models(AT)["members"][1]

    async def prepare():
        async with connect(scratch_database) as connection:
            await migrate(connection)
            await load_seeds(connection, [HOME], lambda: AT)
            repo = GraphRepository(connection, HOME.household_id)
            async with repo.write(lambda: AT + timedelta(minutes=1)):
                await repo.put(
                    "members",
                    mom.model_copy(update={"display_name": "Mom updated"}),
                    expected_version=AT,
                )

    asyncio.run(prepare())
    # CLI parsing/serialization runs unchanged; only the connection targets the
    # disposable database rather than the developer's household.
    monkeypatch.setattr(cli, "connect_database", lambda _: connect(scratch_database))
    monkeypatch.setattr(cli, "read_env", lambda _: {})
    argv = [
        "hirz",
        "context",
        str(HOME.household_id),
        "--scope",
        "member",
        "--member",
        str(mom.id),
    ]
    monkeypatch.setattr("sys.argv", argv + ["--as-of", AT.isoformat()])
    assert cli.main() == 0
    historical = json.loads(capsys.readouterr().out)
    assert historical["data"]["members"][0]["display_name"] == "Mom"
    monkeypatch.setattr("sys.argv", argv)
    assert cli.main() == 0
    current = json.loads(capsys.readouterr().out)
    assert current["data"]["members"][0]["display_name"] == "Mom updated"
    assert current["data"]["preferences"][0]["value"] == 72
    print(
        "Historical CLI: at 12:00Z = Mom; current = Mom updated; preference = 72; both exit 0."
    )
