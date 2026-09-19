"""Item 12 migration and observation writes in disposable PostgreSQL databases."""

import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.util import CommandError
from test_database import connect, migrate, rejected
from test_database import scratch_database as scratch_database

from hirz import db
from hirz.graph.context import ContextService
from hirz.graph.models import GraphError, Observation
from hirz.graph.repository import GraphRepository, row_values
from hirz.graph.seeds import load_seeds
from tests.unit.test_pipeline import AT, HOME, SEED, ident

pytestmark = pytest.mark.integration


def test_legacy_migration_domain_coexistence_and_guarded_rollback(scratch_database):
    async def run():
        async with connect(scratch_database) as connection:
            await migrate(connection)
            await load_seeds(connection, [SEED], lambda: AT)
            await migrate(connection, "downgrade", "0003_pipeline")
            legacy = Observation(
                id=uuid4(),
                household_id=HOME,
                member_id=ident("members", "mom"),
                observed_at=AT,
                source="twin",
                state={"present": True},
            )
            values = row_values("observations", legacy)
            await connection.execute(
                db.observations.insert().values(
                    **values, valid_from=AT + timedelta(seconds=1)
                )
            )
            await connection.execute(
                db.HISTORY_TABLES["observations"]
                .insert()
                .values(**values, valid_from=AT, valid_to=AT + timedelta(seconds=1))
            )
            await connection.execute(
                sa.text("REFRESH MATERIALIZED VIEW household_context")
            )
            await connection.commit()
            service = ContextService(connection, lambda: AT + timedelta(seconds=2))
            before = await service.get_household_context(HOME)
            past = await service.get_household_context(HOME, as_of=AT)
            await connection.rollback()
            await migrate(connection)
            assert await service.get_household_context(HOME) == before
            assert await service.get_household_context(HOME, as_of=AT) == past
            await connection.rollback()
            await migrate(connection, "downgrade", "0003_pipeline")
            await migrate(connection)

            repo = GraphRepository(connection, HOME)
            at = AT + timedelta(seconds=2)
            presence = Observation.model_validate(
                legacy.model_dump()
                | {"id": uuid4(), "domain": "presence", "observed_at": at}
            )
            wearable = Observation.model_validate(
                presence.model_dump()
                | {"id": uuid4(), "domain": "wearable", "state": {"recovery_score": 85}}
            )
            tariff = Observation(
                id=uuid4(),
                household_id=HOME,
                domain="energy",
                observed_at=at,
                source="real",
                state={"price_band": "low"},
            )
            async with repo.write(lambda: at):
                for row in (presence, wearable, tariff):
                    await repo.put("observations", row)
            current = await service.get_household_context(HOME)
            assert len(current.data["observations"]) == 4
            energy = await service.get_household_context(HOME, scope="energy")
            assert energy.data["observations"][0]["state"]["price_band"] == "low"
            people = await service.get_household_context(HOME, scope="people")
            assert len(people.data["observations"]) == 3
            assert await service.get_household_context(HOME, as_of=AT) == past
            await connection.rollback()
            # Database uniqueness also holds for callers bypassing model validation.
            await rejected(
                connection,
                db.observations.insert().values(
                    **row_values(
                        "observations", presence.model_copy(update={"id": uuid4()})
                    ),
                    valid_from=at,
                ),
            )
            await connection.rollback()
            for changed, message in (
                (
                    presence.model_copy(
                        update={"domain": "wearable", "state": wearable.state}
                    ),
                    "domain cannot change",
                ),
                (
                    presence.model_copy(update={"member_id": ident("members", "dad")}),
                    "subject cannot change",
                ),
                (presence.model_copy(update={"domain": None}), "require a domain"),
            ):
                with pytest.raises(GraphError, match=message):
                    async with repo.write(lambda: at + timedelta(seconds=1)):
                        await repo.put("observations", changed, expected_version=at)
            with pytest.raises(CommandError):
                await migrate(connection, "downgrade", "0003_pipeline")
            await connection.rollback()
            await connection.run_sync(db.require_current)
            await connection.rollback()
            # Tagged history alone also forbids rollback; never erase it to fit old code.
            async with repo.write(lambda: at + timedelta(seconds=1)):
                await repo.put(
                    "observations",
                    presence.model_copy(
                        update={"observed_at": at + timedelta(seconds=1)}
                    ),
                    expected_version=at,
                )
            await connection.execute(
                db.observations.delete().where(
                    db.observations.c.attributes["domain"].astext.is_not(None)
                )
            )
            await connection.commit()
            with pytest.raises(CommandError):
                await migrate(connection, "downgrade", "0003_pipeline")
            await connection.rollback()
            assert (
                await connection.scalar(
                    sa.select(sa.func.count()).select_from(
                        db.HISTORY_TABLES["observations"]
                    )
                )
                == 2
            )
            print(
                "Migration: legacy current/history preserved; presence+wearable coexist; duplicate rejected; tagged current/history downgrade refused"
            )

    asyncio.run(run())


def test_observation_scope_and_domain_validation_on_write(scratch_database):
    async def run():
        async with connect(scratch_database) as connection:
            await migrate(connection)
            await load_seeds(connection, [SEED], lambda: AT)
            repo = GraphRepository(connection, HOME)
            for changes in (
                {"asset_id": ident("assets", "light.living_room"), "domain": "ev"},
                {"asset_id": uuid4(), "domain": "devices"},
                {"member_id": uuid4(), "domain": "presence"},
                {"domain": "devices"},
            ):
                observation = Observation.model_validate(
                    dict(
                        id=uuid4(),
                        household_id=HOME,
                        observed_at=AT,
                        source="twin",
                        state={"available": True},
                    )
                    | changes
                )
                with pytest.raises(GraphError):
                    async with repo.write(lambda: AT + timedelta(seconds=1)):
                        await repo.put("observations", observation)
            assert (
                await connection.scalar(
                    sa.select(sa.func.count()).select_from(db.observations)
                )
                == 0
            )

    asyncio.run(run())
