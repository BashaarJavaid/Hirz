"""One composition root for the explicitly configured local worker."""

import argparse
import asyncio
import json
import os
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import sqlalchemy as sa

from hirz import db
from hirz.adapters.devices.ha import HomeAssistant, load_config
from hirz.adapters.energy.real import factories as energy_factories
from hirz.adapters.registry import Registry, parse_config
from hirz.constitution.boundary import Dogwood
from hirz.constitution.schema import loads
from hirz.executor.refresh_worker import RefreshWorker
from hirz.executor.service import Executor
from hirz.explainer.bedrock import configured
from hirz.graph.models import (
    AdapterDomain,
    Asset,
    AssetBinding,
    Household,
    Member,
    Source,
    now,
)
from hirz.local import read_env, signing_key
from hirz.pipeline.audit import AuditWriter
from hirz.pipeline.models import Decision
from hirz.pipeline.service import Pipeline, PolicyBundle
from hirz.planner.coordinator import clean
from hirz.twin.adapters import factories
from hirz.twin.scenario import LoadedScenario
from hirz.twin.world import TwinWorld


async def policy(p: Pipeline) -> PolicyBundle:
    async with p.connection.begin():
        row = (
            (
                await p.connection.execute(
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
                    .where(db.households.c.id == p.household_id)
                )
            )
            .mappings()
            .one()
        )
    if row["hash"] != sha256(row["yaml"].encode()).hexdigest():
        raise ValueError("Stored local policy integrity check failed")
    value = loads(row["yaml"])
    if (
        value.version != row["version"]
        or value.household != p.bundle.policy().household
    ):
        raise ValueError("Stored local policy identity mismatch")
    return await PolicyBundle.validate(p.household_id, value, p.boundary)


async def compose(
    p: Pipeline,
    *,
    world: TwinWorld | None = None,
    config: str | None = None,
    ha_path: Path | None = None,
    scenario: bool = False,
) -> Registry:
    async with p.connection.begin():
        snap = await p.snapshot(p.clock())
    home = Household.model_validate(clean(snap.data["households"][0]))
    assets = tuple(Asset.model_validate(clean(a)) for a in snap.data["assets"])
    members = tuple(Member.model_validate(clean(m)) for m in snap.data["members"])
    bindings = tuple(
        AssetBinding.model_validate(clean(b)) for b in snap.data["asset_bindings"]
    )
    implementations = factories(world) if world else {}
    sources: dict[tuple[AdapterDomain, str, UUID], Source] = {}
    if any(b.adapter == "ha" for b in bindings):
        if ha_path is None:
            raise ValueError("HA bindings require explicit HIRZ_HA_CONFIG")
        ha = load_config(ha_path)
        implementations[("devices", "ha")] = lambda household: HomeAssistant(
            household, config=ha, assets=assets, bindings=bindings, pipeline=p
        )
        sources.update(
            {
                ("devices", "ha", b.asset_id): ha.entities[b.entity_id].source
                for b in bindings
                if b.adapter == "ha"
            }
        )
    if scenario and world is not None and home.rate_plan == "comed_time_of_day":
        from hirz.twin.scenario_energy import ScenarioEnergy

        implementations[("energy", "scenario")] = lambda household: ScenarioEnergy(
            world
        )
        sources[("energy", "scenario", home.id)] = "real"
    if parse_config(config).get("energy") == "real":
        implementations.update(
            energy_factories(
                delivery_class=os.environ["HIRZ_DELIVERY_CLASS"],
                tariff_path=Path(os.environ["HIRZ_TARIFF_FILE"]),
            )
        )
        sources[("energy", "real", home.id)] = "real"
    if world is None:
        # Without a configured world, synthetic domains cannot be read or executed.
        # A refresh requiring one will fail its required-device check.
        bindings = tuple(b for b in bindings if b.adapter != "twin")
    return Registry(
        home,
        members=members,
        assets=assets,
        bindings=bindings,
        factories=implementations,
        sources=sources,
        config=config,
        clock=p.clock,
        scenario_mode=scenario,
        fallback_bindings=tuple(
            world.bindings[b.asset_id] for b in bindings if b.adapter == "ha"
        )
        if scenario and world
        else (),
    )


async def worker(args: argparse.Namespace) -> int:
    try:
        values = read_env(Path(".env"))
        for key, value in values.items():
            if key.startswith("HIRZ_") and key not in os.environ:
                os.environ[key] = value
        scenario = os.environ.get("HIRZ_TWIN_SCENARIO")
        world = LoadedScenario(Path(scenario)).world if scenario else None
        clock = (lambda: world.clock()) if world else now
        if world:
            world.clock.set_speed(float(os.environ.get("HIRZ_SIM_SPEED", "1")))
        boundary = Dogwood()
        async with db.connect_database(values, database=args.database) as connection:
            await connection.run_sync(db.require_current)
            row = (
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
                        .where(db.households.c.id == args.household)
                    )
                )
                .mappings()
                .one()
            )
            await connection.rollback()
            initial = await PolicyBundle.validate(
                args.household, loads(row["yaml"]), boundary
            )
            p = Pipeline(
                connection, initial, boundary, AuditWriter(signing_key(values)), clock
            )
            p.bundle = await policy(p)
            if world:
                from hirz.executor.twin import restore

                await restore(p, world)
            registry = await compose(
                p,
                world=world,
                ha_path=Path(os.environ["HIRZ_HA_CONFIG"])
                if os.environ.get("HIRZ_HA_CONFIG")
                else None,
            )
            executor = Executor(
                p,
                registry,
                world=world,
                reload_policy=lambda: policy(p),
                refresh_polls=True,
            )
            await registry.start()
            try:
                async with db.connect_database(
                    values, database=args.database
                ) as refresh_connection:
                    refresh_pipeline = Pipeline(
                        refresh_connection, p.bundle, boundary, p.audit, clock
                    )
                    refresh_registry = await compose(
                        refresh_pipeline,
                        world=world,
                        ha_path=Path(os.environ["HIRZ_HA_CONFIG"])
                        if os.environ.get("HIRZ_HA_CONFIG")
                        else None,
                    )
                    await refresh_registry.start()
                    try:
                        refresh = RefreshWorker(
                            refresh_pipeline,
                            refresh_registry,
                            world=world,
                            explainer=configured(),
                        )
                        while True:
                            refresh_pipeline.bundle = await policy(refresh_pipeline)
                            task = asyncio.create_task(refresh.batch())
                            decisions: list[Decision] = []
                            try:
                                while not task.done():
                                    decisions.extend(
                                        await executor.sweep(endings_only=True)
                                    )
                                    await asyncio.wait({task}, timeout=0.1)
                                await task
                            finally:
                                if not task.done():
                                    task.cancel()
                                    await asyncio.gather(task, return_exceptions=True)
                            decisions.extend(await executor.sweep())
                            print(
                                json.dumps(
                                    {
                                        "engine": "dogwood-local",
                                        "sources": sorted(
                                            set(registry.sources.values())
                                            | ({"twin"} if world else set())
                                        ),
                                        "decisions": [
                                            d.model_dump(mode="json", by_alias=True)
                                            for d in decisions
                                        ],
                                    }
                                ),
                                flush=True,
                            )
                            if args.once:
                                return 0
                            await asyncio.sleep(1)
                    finally:
                        await refresh_registry.close()
            finally:
                await registry.close()
    except Exception:
        print(
            json.dumps(
                {
                    "engine": "dogwood-local",
                    "status": "failed",
                    "error": "Worker stopped; check local configuration, policy, database and audit. Private inputs withheld.",
                }
            ),
            flush=True,
        )
        return 1
