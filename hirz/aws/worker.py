"""All AWS polling and execution is awaited inside the authenticated tick."""

import asyncio
import os

import sqlalchemy as sa

from hirz import db
from hirz.aws.client import client
from hirz.aws.fixture import load
from hirz.aws.schedules import reconcile
from hirz.companion.api import Companion
from hirz.companion.drafting import advance as draft
from hirz.companion.twin import advance as advance_twin
from hirz.constitution.schema import loads
from hirz.contacts.worker import advance as contacts
from hirz.executor.local import compose, policy
from hirz.executor.refresh_worker import RefreshWorker
from hirz.executor.service import Executor
from hirz.executor.twin import restore
from hirz.explainer.core import TemplateExplainer
from hirz.graph.models import now
from hirz.mcp.trust import advance as trust
from hirz.mcp.worker import prepare_plans
from hirz.pipeline.service import Pipeline, PolicyBundle
from hirz.protect.worker import advance as protect
from hirz.twin.clock import SimClock


async def tick(service: Companion) -> None:
    async with service.engine.connect() as connection:
        async with connection.begin():
            locked = await connection.scalar(
                sa.text("SELECT pg_try_advisory_lock(360036)")
            )
        if not locked:
            return
        try:
            loaded = load()
            async with connection.begin():
                rows = (
                    (
                        await connection.execute(
                            sa.select(db.constitution_versions)
                            .join(
                                db.households,
                                sa.and_(
                                    db.households.c.id
                                    == db.constitution_versions.c.household_id,
                                    db.households.c.constitution_version
                                    == db.constitution_versions.c.version,
                                ),
                            )
                            .where(db.constitution_versions.c.status == "active")
                        )
                    )
                    .mappings()
                    .all()
                )
            for row in rows:
                if row["household_id"] != loaded.world.household.id:
                    raise ValueError(
                        "AWS acceptance only supports its explicit twin household"
                    )
                p = Pipeline(
                    connection,
                    await PolicyBundle.validate(
                        row["household_id"], loads(row["yaml"]), service.boundary
                    ),
                    service.boundary,
                    service.audit,
                    now,
                    require_active=True,
                )
                p.bundle = await policy(p)
                world = loaded.world
                await restore(p, world)
                world.clock = SimClock(now(), 1)
                registry = await compose(
                    p,
                    world=world,
                    config=",".join(
                        f"{domain}:twin" for domain in loaded.spec.adapters
                    ),
                )
                await registry.start()
                try:
                    executor = Executor(
                        p,
                        registry,
                        world=world,
                        reload_policy=lambda: policy(p),
                        refresh_polls=True,
                        freeze_twin_clock=False,
                    )
                    await executor.sweep()
                    # A separate connection keeps bounded endings runnable during preparation.
                    async with service.engine.connect() as other:
                        refresh = Pipeline(
                            other,
                            p.bundle,
                            p.boundary,
                            p.audit,
                            now,
                            require_active=True,
                        )
                        other_registry = await compose(
                            refresh,
                            world=world,
                            config=",".join(
                                f"{domain}:twin" for domain in loaded.spec.adapters
                            ),
                        )
                        await other_registry.start()
                        try:

                            async def preparation() -> None:
                                await protect(refresh)
                                await trust(refresh, world)
                                await contacts(refresh)
                                await draft(refresh)
                                await prepare_plans(refresh, loaded)
                                await RefreshWorker(
                                    refresh,
                                    other_registry,
                                    world=world,
                                    explainer=TemplateExplainer(),
                                ).batch()
                                await advance_twin(refresh)

                            task = asyncio.create_task(preparation())
                            try:
                                while not task.done():
                                    await executor.sweep(endings_only=True)
                                    await asyncio.wait({task}, timeout=0.1)
                                await task
                            finally:
                                task.cancel()
                                await asyncio.gather(task, return_exceptions=True)
                        finally:
                            await other_registry.close()
                    await executor.sweep()
                finally:
                    await registry.close()
            await reconcile(
                connection,
                client("scheduler"),
                group=os.environ["HIRZ_SCHEDULE_GROUP"],
                target=os.environ["HIRZ_TICK_ARN"],
                role=os.environ["HIRZ_SCHEDULE_ROLE"],
                at=now(),
            )
        finally:
            if connection.in_transaction():
                await connection.rollback()
            async with connection.begin():
                await connection.execute(sa.text("SELECT pg_advisory_unlock(360036)"))
