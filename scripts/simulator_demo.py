"""Explicit disposable simulator. Real passkeys, PKCE consent, no active-policy bootstrap.

The HTTPS origin must forward to --port. Ctrl-C verifies signed exports before
cleanup. Invitations are written privately, never printed. Restart starts fresh.
"""

import argparse
import asyncio
import json
import os
import signal
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import sqlalchemy as sa
import uvicorn
from sqlalchemy.ext.asyncio import create_async_engine

from hirz import db
from hirz.api.app import create_app
from hirz.audit import retain_export, write_export
from hirz.companion.api import Companion
from hirz.companion.auth import Config, initial_invitation
from hirz.graph.models import ContactChannel, now
from hirz.graph.seeds import load_seeds, read_seed
from hirz.host.scenarios import Scenarios
from hirz.host.simulator import Simulator
from hirz.local import read_env, signing_key
from hirz.mcp.auth import KeyCache, identity_context
from hirz.mcp.dev_oauth import DevProvider, create_issuer
from hirz.mcp.dev_oauth import signing_key as oauth_key
from hirz.mcp.runtime import HouseholdRuntime
from hirz.pipeline.audit import AuditWriter
from hirz.twin.disposable import disposable
from hirz.twin.execution import bootstrap
from hirz.twin.scenario import LoadedScenario


async def run(args: argparse.Namespace) -> None:
    if args.budget_ledger and os.environ.get("HIRZ_LLM", "off") != "bedrock":
        raise ValueError(
            "Paid host requires explicit HIRZ_LLM=bedrock; off is scripted only"
        )
    args.artifacts_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    values = read_env(Path(".env"))
    audit = AuditWriter(signing_key(values))
    config = Config(args.origin, urlsplit(args.origin).hostname or "")
    issuer = f"http://127.0.0.1:{args.issuer_port}"
    resource = f"http://127.0.0.1:{args.port}/mcp"
    provider = DevProvider(
        oauth_key(values),
        issuer=issuer,
        resource=resource,
        callback=args.origin + "/api/simulator/callback",
    )
    loaded = {
        name: LoadedScenario(Path("scenarios") / (name + ".yaml"))
        for name in ("demo-evening", "parents-scam-check")
    }
    evening = loaded["demo-evening"]
    evening.world.config = evening.world.config.model_copy(
        update={"end": evening.world.config.end + timedelta(hours=1)}
    )
    async with disposable(values) as connection:
        await bootstrap(loaded["demo-evening"], connection)
        parents = loaded["parents-scam-check"]
        await load_seeds(
            connection,
            [read_seed(parents.seed_path)],
            lambda: parents.world.clock() - timedelta(seconds=2),
        )
        engine = create_async_engine(
            connection.engine.url, hide_parameters=True, poolclass=sa.pool.NullPool
        )
        worlds = {item.world.household.id: item.world for item in loaded.values()}
        companion = Companion(
            engine,
            audit,
            config,
            demo_world=loaded["demo-evening"].world,
            demo_worlds=worlds,
        )
        simulator = Simulator(
            origin=args.origin,
            mcp_url=resource,
            issuer=issuer,
            ledger=args.budget_ledger,
        )
        scenarios = Scenarios(companion, loaded, simulator)
        invitations = []
        for item in loaded.values():
            # Remove prerecorded replies; only authenticated human selections finish cases.
            item.world.config = item.world.config.model_copy(
                update={"contact_scripts": ()}
            )
            async with companion.pipeline(item.world.household.id) as p:
                async with p.repo.write(
                    lambda: item.world.clock() - timedelta(seconds=1)
                ):
                    snapshot = await p.snapshot(p.clock())
                    for contact in snapshot.data["trusted_contacts"]:
                        await p.repo.put(
                            "contact_channels",
                            ContactChannel(
                                id=uuid4(),
                                household_id=p.household_id,
                                contact_id=UUID(str(contact["id"])),
                                kind="hirz_app",
                                value_hash=sha256(
                                    b"explicit item29 simulated verified-channel fixture"
                                ).hexdigest(),
                                verified_at=p.clock() - timedelta(seconds=1),
                                source="twin",
                            ),
                        )
                async with p.connection.begin():
                    member = await p.connection.scalar(
                        sa.select(db.members.c.id).where(
                            p.scope(db.members), db.members.c.role == "owner"
                        )
                    )
                assert member
                invitations.append(
                    {
                        "household": str(p.household_id),
                        "token": await initial_invitation(p, member, at=now()),
                    }
                )
        write_export(
            args.artifacts_dir / "invitations.json", {"invitations": invitations}
        )

        def clock() -> datetime:
            identity = identity_context.get()
            if identity is None:
                raise ValueError("A household clock requires authenticated identity")
            return worlds[identity.household_id].clock()

        runtime = HouseholdRuntime(engine, audit, clock=clock)
        app = create_app(
            port=args.port,
            cache=KeyCache(issuer, resource),
            engine=engine,
            household=runtime,
            companion=companion,
            simulator=simulator,
        )
        # Insert before the root MCP mount, which intentionally catches all remaining paths.
        extra = scenarios.router()
        app.router.routes[-1:-1] = extra.routes
        servers = [
            uvicorn.Server(
                uvicorn.Config(
                    app,
                    host="127.0.0.1",
                    port=args.port,
                    access_log=False,
                    log_level="warning",
                )
            ),
            uvicorn.Server(
                uvicorn.Config(
                    create_issuer(provider, port=args.issuer_port),
                    host="127.0.0.1",
                    port=args.issuer_port,
                    access_log=False,
                    log_level="warning",
                )
            ),
        ]
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: None)
        tasks = [asyncio.create_task(server.serve()) for server in servers]

        async def work() -> None:
            while not all(server.started for server in servers):
                await asyncio.sleep(0.1)
            await scenarios.run()

        tasks.append(asyncio.create_task(work()))
        if args.browser_test:

            async def browser_check() -> None:
                while not all(server.started for server in servers):
                    await asyncio.sleep(0.1)
                process = await asyncio.create_subprocess_exec(
                    "pnpm",
                    "--filter",
                    "web",
                    "exec",
                    "playwright",
                    "test",
                    "tests/simulator.spec.ts",
                    env=os.environ
                    | {
                        "HIRZ_SIMULATOR_ARTIFACTS": str(args.artifacts_dir.resolve()),
                        "HIRZ_BROWSER_BACKEND": f"http://127.0.0.1:{args.port}",
                    },
                )
                if await process.wait():
                    raise ValueError("Simulator browser acceptance failed")

            tasks.append(asyncio.create_task(browser_check()))
        print(
            f"Simulator: {args.origin}/simulator; enroll both owners using private invitations.json, activate their seed policies, then link each Echo with consent.",
            flush=True,
        )
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            for browser in simulator.browsers.values():
                for account in browser.echoes:
                    browser.account = account
                    browser.cancel()
            pending = [task for task in simulator.active.values() if not task.done()]
            try:
                async with asyncio.timeout(45):
                    await asyncio.gather(*pending, return_exceptions=True)
            except TimeoutError:
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
            for server in servers:
                server.should_exit = True
            for task in tasks[2:]:
                task.cancel()
            await asyncio.gather(*tasks[2:], return_exceptions=True)
            try:
                async with asyncio.timeout(15):
                    await asyncio.gather(*tasks[:2], return_exceptions=True)
            except TimeoutError:
                for task in tasks[:2]:
                    task.cancel()
                await asyncio.gather(*tasks[:2], return_exceptions=True)
            for household in worlds:
                folder = args.artifacts_dir / str(household)
                folder.mkdir(mode=0o700)
                async with engine.connect() as c:
                    await retain_export(c, household, audit.key.public_key(), folder)
            write_export(args.artifacts_dir / "playback.json", scenarios.view())
            evidence = {}
            for name, item in loaded.items():
                rows = json.loads(
                    (
                        args.artifacts_dir / str(item.world.household.id) / "audit.json"
                    ).read_text()
                )["rows"]
                verified = {
                    r["payload"].get("action_id"): r
                    for r in rows
                    if r["event_type"] == "VERIFIED"
                }
                endings = [
                    r["payload"]
                    for r in rows
                    if r["event_type"] == "ENDING_AUTHORIZED"
                    and r["payload"]["ending"]["class"] == "security.door_unlock"
                ]
                bounded = [
                    e
                    for e in endings
                    if e["opening"] in verified
                    and e["ending"]["action_id"] in verified
                    and datetime.fromisoformat(
                        verified[e["ending"]["action_id"]]["created_at"]
                    )
                    <= datetime.fromisoformat(e["ending"]["expected_effect"]["by"])
                ]
                evidence[name] = {
                    "timeline_complete": scenarios.index[name] == len(item.times),
                    "signed_rows": len(rows),
                    "verified_bounded_unlocks": len(bounded),
                    "source": "twin",
                    "checkpoints": scenarios.checkpoints[name],
                    "final_state": item.world.read()[1].model_dump(mode="json"),
                    "source_deferred_assertions": [
                        d.model_dump(mode="json") for d in item.spec.assertions.deferred
                    ],
                }
            write_export(args.artifacts_dir / "verification.json", evidence)
            selected = (
                os.environ.get("HIRZ_SIMULATOR_SCENARIO") if args.browser_test else None
            )
            if selected:
                assert evidence[selected]["timeline_complete"], (
                    "Playback did not finish"
                )
                if selected == "demo-evening":
                    assert evidence[selected]["verified_bounded_unlocks"] == 1, (
                        "Signed opening and bounded relock verification are required"
                    )
                    assert (
                        abs(
                            scenarios.checkpoints[selected]["ev_at_needed_by"]["soc"]
                            - 0.5
                        )
                        < 1e-6
                    ), "The car must reach exactly 50% by 06:30"
                    state = loaded[selected].world.read()[1]
                    assert next(iter(state.appliances.values())).completions == 1, (
                        "The dishwasher must complete its cycle"
                    )

            await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--browser-test", action="store_true")
    parser.add_argument("--port", type=int, default=8002)
    parser.add_argument("--issuer-port", type=int, default=8003)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument(
        "--budget-ledger",
        type=Path,
        help="Separate durable item29-host ledger, aggregate ceiling $5; enables live host models only",
    )
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
