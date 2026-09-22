"""Recorded HA smoke by default; opt-in live writes use a disposable database."""

import argparse
import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from alembic import command
from hirz import db
from hirz.adapters.base import AdapterError
from hirz.adapters.devices.ha import HAConfig, HomeAssistant, load_config
from hirz.audit import (
    export_document,
    fingerprint,
    verify_database,
    verify_file,
    write_export,
)
from hirz.constitution.boundary import Dogwood
from hirz.constitution.schema import load
from hirz.graph.models import (
    Asset,
    AssetBinding,
    Household,
    Member,
    Observation,
    ObservationState,
    now,
)
from hirz.graph.repository import GraphRepository
from hirz.graph.seeds import demo_id, load_seeds, read_seed
from hirz.local import read_env, signing_key
from hirz.pipeline.audit import AuditWriter
from hirz.pipeline.hashing import action_hash
from hirz.pipeline.models import Action, Decision, Principal
from hirz.pipeline.service import Pipeline, PolicyBundle

ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = ROOT / "constitutions/quinn-home.yaml"


def inputs(
    config: HAConfig, plug: bool = False
) -> tuple[Household, tuple[Asset, ...], tuple[AssetBinding, ...], tuple[Member, ...]]:
    rows = read_seed(SEED_PATH).models(now())
    home = cast(Household, rows["households"][0])
    assets = tuple(cast(Asset, a) for a in rows["assets"])
    # Explicit synthetic room metadata, not name-based product inference.
    light = demo_id("quinn-home", "assets", "light.living_room")
    assets = tuple(
        a.model_copy(update={"room_kind": "other"}) if a.id == light else a
        for a in assets
    )
    selected = {}
    if plug:
        if len(config.entities) != 1:
            raise AdapterError(
                "Live plug smoke requires exactly one explicitly mapped control."
            )
        entity, entry = next(iter(config.entities.items()))
        if (
            not entity.startswith(("light.", "switch."))
            or entry.source != "real"
            or entry.power_sensor is None
        ):
            raise AdapterError("Live plug requires real provenance and a power sensor.")
        selected[light] = entity
    else:
        mapping = {
            "climate.heatpump": "hvac.living_room",
            "climate.ecobee": "hvac.guest_room",
            "light.bed_light": "light.living_room",
        }
        if set(config.entities) != set(mapping) or any(
            e.source != "real API, demo devices" for e in config.entities.values()
        ):
            raise AdapterError("Live demo requires the reviewed demo mapping.")
        selected = {
            demo_id("quinn-home", "assets", asset): entity
            for entity, asset in mapping.items()
        }
    bindings = tuple(
        cast(AssetBinding, b).model_copy(
            update={
                "adapter": "ha",
                "entity_id": selected[cast(AssetBinding, b).asset_id],
            }
        )
        for b in rows["asset_bindings"]
        if cast(AssetBinding, b).asset_id in selected
    )
    return home, assets, bindings, tuple(cast(Member, m) for m in rows["members"])


def action(entity: str, asset: Asset, value: float | bool) -> Action:
    climate = entity.startswith("climate.")
    a = Action.model_validate(
        {
            "action_id": "act_" + uuid4().hex,
            "class": "energy.hvac_adjust" if climate else "environment.lights",
            "target": {
                "adapter": "ha",
                "entity": entity,
                **({"zone": str(asset.id)} if climate else {}),
            },
            "params": {"target_f": value} if climate else {"on": value},
            "requested_by": {"member_id": None, "role": "unknown", "surface": "app"},
            "reason": "Explicit local HA adapter smoke",
            "content_hash": "",
        }
    )
    return a.model_copy(update={"content_hash": action_hash(a)})


async def recorded() -> None:
    config = load_config(ROOT / "config/homeassistant/adapter-demo.yaml")
    home, assets, bindings, _ = inputs(config)
    # Deliberately recorded protocol messages; no network or real credentials.
    at = (now() - timedelta(seconds=1)).isoformat()
    states = {
        e: {
            "entity_id": e,
            "state": "heat" if e.startswith("climate.") else "off",
            "last_updated": at,
            "attributes": {
                "current_temperature": 73,
                "temperature": 68,
                "min_temp": 45,
                "max_temp": 95,
                "supported_features": 1,
            }
            if e.startswith("climate.")
            else {},
        }
        for e in config.entities
    }

    def transport(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        if request.url.path == "/api/config":
            return httpx.Response(200, json={"unit_system": {"temperature": "°F"}})
        return httpx.Response(200, json=states[request.url.path.rsplit("/", 1)[-1]])

    socket = AsyncMock()
    socket.recv.side_effect = [
        json.dumps(m)
        for m in [
            {"type": "auth_required"},
            {"type": "auth_ok"},
            {"id": 1, "type": "result", "success": True},
            {
                "id": 1,
                "type": "event",
                "event": {
                    "event_type": "state_changed",
                    "data": {"entity_id": "light.unbound"},
                },
            },
            {
                "id": 1,
                "type": "event",
                "event": {
                    "event_type": "state_changed",
                    "data": {"entity_id": "light.bed_light"},
                },
            },
        ]
    ]
    socket.__aenter__.return_value = socket
    with TemporaryDirectory(prefix="hirz_ha_recorded_") as directory:
        env = Path(directory) / ".env"
        env.write_text("HA_TOKEN=recorded-placeholder\n")
        env.chmod(0o600)
        adapter = HomeAssistant(
            home,
            config=config,
            assets=assets,
            bindings=bindings,
            env_path=env,
            transport=httpx.MockTransport(transport),
        )
        await adapter.start()
        try:
            assert len(await adapter.list_entities()) == 3
            row = await adapter.get_state("climate.heatpump")
            assert row.state.target_f == 68
            with patch("hirz.adapters.devices.ha.connect", return_value=socket):
                stream = adapter.subscribe()
                observed = await anext(stream)
                assert (
                    observed.source == "real API, demo devices"
                    and observed.state.on is False
                )
                await stream.aclose()
            x = action(
                "light.bed_light", next(a for a in assets if a.kind == "light"), True
            )
            d = Decision.model_validate(
                {
                    "decision": "execute",
                    "event_type": "EXECUTE",
                    "action_id": x.action_id,
                    "constitution": {
                        "version": 1,
                        "rule": "test",
                        "mode": "auto",
                        "conditions_met": True,
                    },
                }
            )
            try:
                await adapter.set_light(x, d)
            except AdapterError:
                pass
            else:
                raise AssertionError("Read-only adapter dispatched")
            print(
                "recorded=PASS; reads=3; subscription=acknowledged,filtered; read_only_write=refused; network_requests=0"
            )
        finally:
            await adapter.close()


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
            print(f"disposable_database_retained={name}")
        raise
    else:
        await engine.dispose()
        async with admin.connect() as c:
            await c.exec_driver_sql(f'DROP DATABASE "{name}"')
        print("disposable_database=dropped; development_database=unchanged")
    finally:
        await engine.dispose()
        await admin.dispose()


async def live(
    config_path: Path, plug: bool, audit_output: Path, *, durable: bool = False
) -> None:
    if audit_output.exists() or audit_output.is_symlink():
        raise AdapterError("Audit output must be a new file.")
    config = load_config(config_path)
    home, assets, bindings, members = inputs(config, plug)
    values = read_env(ROOT / ".env")
    writer = AuditWriter(signing_key(values))
    boundary = Dogwood(str(ROOT / ".tools/dogwood"))
    bundle = await PolicyBundle.validate(home.id, load(SEED_PATH), boundary)
    async with disposable(values) as connection:
        await load_seeds(connection, [read_seed(SEED_PATH)])
        pipeline = Pipeline(connection, bundle, boundary, writer)
        adapter = HomeAssistant(
            home,
            config=config,
            assets=assets,
            bindings=bindings,
            pipeline=pipeline,
            env_path=ROOT / ".env",
        )
        await adapter.start()
        originals: dict[str, float | bool] = {}
        changed: list[str] = []
        observations: list[Observation] = []
        task: asyncio.Task[None] | None = None
        executor_registry = None
        executor = None
        try:
            for entity in config.entities:
                row = await adapter.get_state(entity)
                value = (
                    row.state.target_f
                    if entity.startswith("climate.")
                    else row.state.on
                )
                if entity != "climate.ecobee":
                    if value is None:
                        raise AdapterError(
                            "Cannot safely restore an unknown original state."
                        )
                    originals[entity] = value
                observations.append(row)
                print(
                    f"read={entity}; source={row.source}; target_f={row.state.target_f}; on={row.state.on}; power_kw={row.state.power_kw}"
                )
            # Approved isolated-test bootstrap only: real bindings, explicit room
            # metadata and one-time observations, before any action or audit row.
            repo = GraphRepository(connection, home.id)
            bootstrap_at = now()
            async with repo.write(lambda: bootstrap_at):
                for binding in bindings:
                    old = await repo.get("asset_bindings", {"id": binding.id})
                    assert old
                    await repo.put(
                        "asset_bindings", binding, expected_version=old["valid_from"]
                    )
                for asset in assets:
                    if asset.kind == "light":
                        old = await repo.get("assets", {"id": asset.id})
                        assert old
                        await repo.put(
                            "assets", asset, expected_version=old["valid_from"]
                        )
                for row in observations:
                    await repo.put("observations", row)
                for member in members:
                    await repo.put(
                        "observations",
                        Observation(
                            id=uuid4(),
                            household_id=home.id,
                            member_id=member.id,
                            domain="presence",
                            source="twin",
                            observed_at=bootstrap_at,
                            state=ObservationState(present=False, available=True),
                        ),
                    )
            received: dict[str, Observation] = {}

            async def collect() -> None:
                async for row in adapter.subscribe():
                    received[str(row.asset_id)] = row

            task = asyncio.create_task(collect())
            ready = asyncio.create_task(adapter.subscription_ready.wait())
            try:
                done, _ = await asyncio.wait(
                    {task, ready}, timeout=12, return_when=asyncio.FIRST_COMPLETED
                )
                if task in done:
                    await task
                if not adapter.subscription_ready.is_set():
                    raise AdapterError("Subscription did not become ready.")
            finally:
                ready.cancel()
                with suppress(asyncio.CancelledError):
                    await ready
            asset_by_entity = {
                b.entity_id: next(a for a in assets if a.id == b.asset_id)
                for b in bindings
            }
            principal = Principal(provider="demo", sub="malik", surface="app")

            if durable:
                from hirz.adapters.registry import Registry
                from hirz.executor.service import Executor

                executor_registry = Registry(
                    home,
                    members=members,
                    assets=assets,
                    bindings=bindings,
                    factories={
                        ("devices", "ha"): lambda h: HomeAssistant(
                            h,
                            config=config,
                            assets=assets,
                            bindings=bindings,
                            pipeline=pipeline,
                            env_path=ROOT / ".env",
                        )
                    },
                    sources={
                        ("devices", "ha", b.asset_id): config.entities[
                            b.entity_id
                        ].source
                        for b in bindings
                    },
                    config="devices:ha",
                )
                await executor_registry.start()
                executor = Executor(pipeline, executor_registry)

            async def write(entity: str, value: float | bool) -> None:
                x = action(entity, asset_by_entity[entity], value)
                if executor is not None:
                    from datetime import timedelta

                    from hirz.pipeline.models import ExpectedEffect

                    at = now()
                    attr = "target_f" if entity.startswith("climate.") else "on"
                    x = x.model_copy(
                        update={
                            "scheduled_for": at,
                            "expected_effect": ExpectedEffect(
                                entity=entity,
                                attr=attr,
                                value=value,
                                by=at + timedelta(seconds=60),
                            ),
                        }
                    )
                    x = x.model_copy(update={"content_hash": action_hash(x)})
                    d = await pipeline.enqueue(x, principal)
                    if d.decision == "ask" and d.approval:
                        await pipeline.vote(
                            d.approval.approval_id, principal, approved=True
                        )
                        d = await pipeline.enqueue(
                            x, principal, approval_id=d.approval.approval_id
                        )
                    if d.status != "executing":
                        raise AdapterError(
                            f"Pipeline refused queued smoke action: {d.event_type}."
                        )
                    results = await executor.sweep()
                    if len(results) != 1 or results[0].status != "verified":
                        raise AdapterError("Durable smoke action was not verified.")
                    print(f"queued={entity}; worker=verified; engine=dogwood-local")
                    return
                d = await pipeline.redeem(x, principal)
                if d.decision == "ask" and d.approval is not None:
                    await pipeline.vote(
                        d.approval.approval_id, principal, approved=True
                    )
                    d = await pipeline.redeem(
                        x, principal, approval_id=d.approval.approval_id
                    )
                if d.decision != "execute":
                    raise AdapterError(
                        f"Pipeline refused smoke action: {d.event_type}."
                    )
                if entity.startswith("climate."):
                    await adapter.set_climate(x, d)
                else:
                    await adapter.set_light(x, d)
                print(
                    f"write={entity}; grant={d.audit_id}; boundary={d.boundary.engine}; verified=True"
                )

            failure: Exception | None = None
            try:
                for entity in originals:
                    changed.append(
                        entity
                    )  # Includes an uncertain request needing restoration.
                    await write(entity, 72.0 if entity.startswith("climate.") else True)
                    async with asyncio.timeout(12):
                        while True:
                            observed = received.get(str(asset_by_entity[entity].id))
                            if observed is not None and (
                                observed.state.target_f == 72
                                if entity.startswith("climate.")
                                else observed.state.on is True
                                and (not plug or observed.state.power_kw is not None)
                            ):
                                break
                            if task.done():
                                await task
                            await asyncio.sleep(0.1)
                    row = received[str(asset_by_entity[entity].id)]
                    expected = "real" if plug else "real API, demo devices"
                    assert row.source == expected
                    direct = await adapter.get_state(entity)
                    if plug and (
                        direct.state.on is not True or direct.state.power_kw is None
                    ):
                        raise AdapterError(
                            "Physical plug did not return an on state and measured power."
                        )
                    print(
                        f"subscription={entity}; source={row.source}; power_kw={row.state.power_kw}; direct_power_kw={direct.state.power_kw}"
                    )
            except Exception as exc:
                failure = exc
            finally:
                for entity in reversed(changed):
                    try:
                        await write(entity, originals[entity])
                        print(f"restoration={entity}; verified=True")
                    except Exception:
                        print(f"restoration={entity}; FAILED; actual state unknown")
                        failure = AdapterError(
                            "Restoration failed; inspect Home Assistant."
                        )
            summary, rows = await verify_database(
                connection, home.id, writer.key.public_key(), collect=True
            )
            write_export(
                audit_output, export_document(home.id, writer.key.public_key(), rows)
            )
            verified = verify_file(
                audit_output,
                home.id,
                trusted_fingerprint=fingerprint(writer.key.public_key()),
            )
            print(
                f"audit={summary['status']}; rows={len(rows)}; export={audit_output}; offline={verified['status']}"
            )
            if failure is not None:
                raise failure
            print("live_plug=PASS" if plug else "live_demo=PASS; ecobee=read_only")
        finally:
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError, AdapterError):
                    await task
            if executor_registry is not None:
                await executor_registry.close()
            await adapter.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--live-demo", action="store_true")
    modes.add_argument("--live-plug", action="store_true")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--audit-output", type=Path)
    args = parser.parse_args()
    if args.live_demo or args.live_plug:
        if args.audit_output is None or args.live_plug and args.config is None:
            parser.error(
                "Live checks require --audit-output NEW_FILE; --live-plug also requires --config PATH."
            )
        asyncio.run(
            live(
                args.config or ROOT / "config/homeassistant/adapter-demo.yaml",
                args.live_plug,
                args.audit_output,
            )
        )
    else:
        asyncio.run(recorded())


if __name__ == "__main__":
    main()
