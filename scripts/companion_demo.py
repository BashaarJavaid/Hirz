"""Explicit disposable companion server: real passkeys, synthetic households, no paid calls.

Invitations are written to a private artifact directory; never printed or exposed by HTTP.
Stop with Ctrl-C to retain independently verified signed exports and drop the database.
"""

import argparse
import asyncio
import json
import os
import signal
import traceback
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import sqlalchemy as sa
import uvicorn
from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from hirz import db
from hirz.api.app import create_app
from hirz.audit import retain_export, write_export
from hirz.companion import push, twin
from hirz.companion.api import Companion
from hirz.companion.auth import Config, initial_invitation
from hirz.executor.local import compose
from hirz.executor.local import policy as reload_policy
from hirz.executor.observations import ingest
from hirz.executor.service import Executor
from hirz.executor.twin import restore
from hirz.graph.models import now
from hirz.graph.seeds import load_seeds, read_seed
from hirz.local import read_env, signing_key
from hirz.pipeline.audit import AuditWriter
from hirz.pipeline.models import Principal
from hirz.twin.clock import SimClock
from hirz.twin.disposable import disposable
from hirz.twin.scenario import LoadedScenario
from hirz.twin.world import TwinConfig, TwinWorld


def phone_world(start: datetime | None = None) -> TwinWorld:
    original = LoadedScenario(Path("scenarios/demo-evening.yaml")).world
    at = start or now()
    delta = at - original.config.start

    def shift(value: Any) -> Any:
        if isinstance(value, datetime):
            return value + delta
        if isinstance(value, dict):
            return {k: shift(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [shift(v) for v in value]
        return value

    world = TwinWorld(
        original.household,
        members=tuple(original.members.values()),
        assets=tuple(original.assets.values()),
        bindings=tuple(original.bindings.values()),
        contacts=tuple(original.contacts.values()),
        channels=original.channels,
        calendar=(),
        config=TwinConfig.model_validate(shift(original.config.model_dump())),
        clock=SimClock(at, 1),
    )
    for member, presence in world.config.presence.items():
        if presence.present and presence.zone_id is None:
            world.member_event(
                member, "arrive", world.entity("hvac.living_room", "devices")
            )
    return world


async def devices(service: Companion) -> None:
    world = service.demo_world
    assert world
    principal = Principal(provider="demo", sub="malik", surface="scheduler")
    while True:
        async with service.demo_lock:
            async with service.pipeline(world.household.id) as p:
                async with p.connection.begin():
                    active = await p.connection.scalar(
                        sa.select(db.constitution_versions.c.status).where(
                            p.scope(db.constitution_versions),
                            db.constitution_versions.c.version
                            == p.bundle.policy().version,
                        )
                    )
                if active == "active":
                    registry = await compose(
                        p, world=world, config="presence:twin,energy:twin"
                    )
                    await registry.start()
                    try:
                        await ingest(p, registry, principal)
                        await Executor(
                            p,
                            registry,
                            world=world,
                            reload_policy=lambda: reload_policy(p),
                            freeze_twin_clock=False,
                        ).sweep()
                    finally:
                        await registry.close()
        await asyncio.sleep(1)


async def background(service: Companion, households: list[Any]) -> None:
    while True:
        for home in households:
            async with service.pipeline(home["household_id"]) as p:
                if config := push.Config.environment():
                    await push.advance(p, config)
                await twin.advance(p)
                from hirz.mcp.worker import prepare_plans

                # This phone fixture supplies no whole-night planning inputs.
                # Settle requests honestly; configured workers use the existing planner.
                await prepare_plans(p, None)
        await asyncio.sleep(1)


@asynccontextmanager
async def connection(
    values: dict[str, str], resumed: dict[str, Any] | None
) -> AsyncIterator[AsyncConnection]:
    if resumed is None:
        async with disposable(values) as c:
            yield c
    else:
        database = resumed["database"]
        if not isinstance(database, str) or not database.startswith("hirz_ha_smoke_"):
            raise ValueError("Only an existing disposable demo can be resumed")
        async with db.connect_database(values, database=database) as c:
            await c.run_sync(db.require_current)
            await c.rollback()
            yield c
        print("Resumed database retained; development database unchanged", flush=True)


async def run(args: argparse.Namespace) -> None:
    if os.environ.get("HIRZ_LLM", "off") != "off":
        raise ValueError("Disposable companion verification requires HIRZ_LLM=off")
    config = Config(args.origin, args.origin.removeprefix("https://"))
    args.artifacts_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    values = read_env(Path(".env"))
    for name, value in values.items():
        if name.startswith("HIRZ_PUSH_") or name.startswith("HIRZ_VAPID_"):
            os.environ.setdefault(name, value)
    audit = AuditWriter(signing_key(values))
    resumed = (
        json.loads((args.resume_from / "runtime.json").read_text())
        if args.resume_from
        else None
    )
    if resumed and resumed["origin"] != config.origin:
        raise ValueError("Resuming cannot change the passkey origin")
    async with connection(values, resumed) as c:
        seeds = [
            read_seed(Path("constitutions") / name)
            for name in ("quinn-home.yaml", "quinn-parents.yaml")
        ]
        world = phone_world(
            datetime.fromisoformat(resumed["world_start"]) if resumed else None
        )
        for seed in seeds:
            for asset in seed.graph["assets"]:
                asset["managed_through_hirz"] = True
                asset["room_kind"] = asset.get("room_kind") or "other"
        if not resumed:
            await load_seeds(c, seeds, lambda: now() - timedelta(seconds=2))
        write_export(
            args.artifacts_dir / "runtime.json",
            {
                "database": c.engine.url.database,
                "origin": config.origin,
                "world_start": world.config.start.isoformat(),
            },
        )
        engine = create_async_engine(
            c.engine.url, hide_parameters=True, poolclass=sa.pool.NullPool
        )
        service = Companion(engine, audit, config, demo_world=world)
        if resumed:
            async with service.pipeline(world.household.id) as p:
                await restore(p, world)
            # Phone runs follow elapsed time, including downtime. Overdue durable
            # endings are swept immediately; never reset the device checkpoint.
            resumed_at = now()
            if resumed_at - world.clock() > timedelta(seconds=1):
                world.clock.jump(resumed_at)
        async with c.begin():
            members = (
                (
                    await c.execute(
                        sa.select(
                            db.members.c.household_id,
                            db.members.c.id,
                            db.members.c.display_name,
                        ).where(db.members.c.role == "owner")
                    )
                )
                .mappings()
                .all()
            )
        invitations = []
        try:
            for member in [] if resumed else members:
                async with service.pipeline(member["household_id"]) as p:
                    token = await initial_invitation(p, member["id"])
                invitations.append(
                    {
                        "household_id": str(member["household_id"]),
                        "name": member["display_name"],
                        "token": token,
                    }
                )
            write_export(
                args.artifacts_dir / "invitations.json", {"invitations": invitations}
            )
            print(
                json.dumps(
                    {
                        "status": "starting",
                        "source": "twin",
                        "origin": args.origin,
                        "port": args.port,
                        "invitations": str(args.artifacts_dir / "invitations.json"),
                    }
                ),
                flush=True,
            )
            app = create_app(port=args.port, companion=service)

            @app.exception_handler(ValueError)
            async def refused(request: Request, exc: ValueError) -> JSONResponse:
                # Private demo diagnostics identify the failing line without
                # printing request headers, credentials, SQL parameters or locals.
                frames = traceback.extract_tb(exc.__traceback__)
                print(
                    json.dumps(
                        {
                            "refused": request.url.path,
                            "frames": [
                                f"{Path(f.filename).name}:{f.lineno}" for f in frames
                            ],
                        }
                    ),
                    flush=True,
                )
                return JSONResponse({"detail": "Request refused"}, status_code=403)

            # Uvicorn re-raises a captured signal after graceful shutdown. Defer
            # process exit until signed exports and disposable cleanup finish.
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, lambda *_: None)
            tasks = [
                asyncio.create_task(devices(service)),
                asyncio.create_task(background(service, list(members))),
            ]
            server = asyncio.create_task(
                uvicorn.Server(
                    uvicorn.Config(
                        app,
                        host="127.0.0.1",
                        port=args.port,
                        access_log=False,
                        log_level="warning",
                    )
                ).serve()
            )
            try:
                done, _ = await asyncio.wait(
                    [server, *tasks], return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    task.result()  # Fail visibly and retain the database if a worker dies.
            finally:
                server.cancel()
                await asyncio.gather(server, return_exceptions=True)
                for task in tasks:
                    task.cancel()
                results = await asyncio.gather(*tasks, return_exceptions=True)
                if any(isinstance(result, Exception) for result in results):
                    print(
                        "Companion background task failed; inspect retained evidence.",
                        flush=True,
                    )

        finally:
            for member in members:
                folder = args.artifacts_dir / str(member["household_id"])
                folder.mkdir(mode=0o700)
                async with engine.connect() as export_connection:
                    summary, _ = await retain_export(
                        export_connection,
                        member["household_id"],
                        audit.key.public_key(),
                        folder,
                    )
                    print(json.dumps(summary), flush=True)
            await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--origin",
        required=True,
        help="Exact HTTPS origin; Tailscale Serve terminates TLS",
    )
    parser.add_argument(
        "--resume-from",
        type=Path,
        help="Resume a retained disposable run without issuing invitations or changing credentials",
    )
    parser.add_argument("--port", type=int, default=8002)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
