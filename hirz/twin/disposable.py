"""Isolated local scenario/smoke databases, retained on failure."""

import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from alembic import command
from hirz import db


@asynccontextmanager
async def disposable(values: dict[str, str]) -> AsyncIterator[AsyncConnection]:
    url = db.database_url(values)
    name = "hirz_ha_smoke_" + uuid4().hex
    admin = create_async_engine(
        url,
        isolation_level="AUTOCOMMIT",
        poolclass=sa.pool.NullPool,
        hide_parameters=True,
    )
    engine = create_async_engine(
        url.set(database=name), poolclass=sa.pool.NullPool, hide_parameters=True
    )
    created = False
    try:
        async with admin.connect() as c:
            await c.exec_driver_sql(f'CREATE DATABASE "{name}"')
            created = True
        async with engine.connect() as c:

            def migrate(sync: sa.Connection) -> None:
                cfg = db.migration_config()
                cfg.attributes["connection"] = sync
                command.upgrade(cfg, "head")

            await c.run_sync(migrate)
            await c.commit()
            yield c
    except BaseException:
        # Preserve evidence on every failure, including failed export/restoration.
        if created:
            print(f"disposable_database_retained={name}", file=sys.stderr)
        raise
    else:
        await engine.dispose()
        async with admin.connect() as c:
            await c.exec_driver_sql(f'DROP DATABASE "{name}"')
        print(
            "disposable_database=dropped; development_database=unchanged",
            file=sys.stderr,
        )
    finally:
        await engine.dispose()
        await admin.dispose()
