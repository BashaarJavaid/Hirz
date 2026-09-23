"""Durable local execution in a disposable database; retained signed audit export."""

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from hirz import db
from hirz.audit import (
    export_document,
    fingerprint,
    verify_database,
    verify_file,
    write_export,
)
from hirz.constitution.boundary import Dogwood
from hirz.executor.local import compose
from hirz.executor.observations import ingest
from hirz.executor.service import Executor
from hirz.graph.models import AssetPolicy
from hirz.graph.repository import row_model
from hirz.graph.seeds import load_seeds, read_seed
from hirz.local import read_env, signing_key
from hirz.pipeline.audit import AuditWriter
from hirz.pipeline.hashing import action_hash
from hirz.pipeline.models import Action, ExpectedEffect, Principal, Requester, Target
from hirz.pipeline.service import Pipeline, PolicyBundle
from hirz.twin.scenario import LoadedScenario
from hirz.twin.world import TwinWorld
from scripts.smoke_ha import disposable

SCENARIO = Path("scenarios/demo-evening.yaml")
PRINCIPAL = Principal(provider="demo", sub="malik", surface="app")


async def setup(connection: AsyncConnection) -> tuple[Pipeline, TwinWorld]:
    loaded = LoadedScenario(SCENARIO)
    world = loaded.world

    def clock() -> datetime:
        return world.clock()

    await load_seeds(
        connection,
        [read_seed(Path("constitutions/quinn-home.yaml"))],
        lambda: clock() - timedelta(seconds=2),
    )
    dogwood = Dogwood()
    p = Pipeline(
        connection,
        await PolicyBundle.validate(world.household.id, loaded.policy, dogwood),
        dogwood,
        AuditWriter(signing_key(read_env(Path(".env")))),
        clock,
    )
    # Approved synthetic bootstrap only, before execution; no grants are fabricated.
    async with p.repo.write(lambda: clock() - timedelta(seconds=1)):
        for asset in world.assets.values():
            old = await p.repo.get("assets", {"id": asset.id})
            assert old is not None
            current = row_model("assets", old)
            await p.repo.put(
                "assets",
                current.model_copy(update={"room_kind": asset.room_kind or "other"}),
                expected_version=old["valid_from"],
            )
        await p.repo.put(
            "asset_policies",
            AssetPolicy(
                id=uuid4(),
                household_id=p.household_id,
                asset_id=world.entity("ev", "ev"),
                needed_by=world.config.end,
            ),
        )
    return p, world


def action(
    world: TwinWorld, name: str = "environment.lights", *, seconds: int = 120
) -> Action:
    entity = {
        "environment.lights": "light.living_room",
        "energy.hvac_adjust": "hvac.living_room",
    }[name]
    attr, value = ("on", True) if name == "environment.lights" else ("target_f", 72)
    a = Action.model_validate(
        dict(
            action_id=uuid4().hex,
            **{"class": name},
            target=Target(
                adapter="twin",
                entity=entity,
                zone=str(world.entity(entity, "devices"))
                if name == "energy.hvac_adjust"
                else None,
            ),
            params={attr: value},
            requested_by=Requester(member_id=None, role="unknown", surface="app"),
            reason="Explicit disposable executor smoke",
            scheduled_for=world.clock(),
            expected_effect=ExpectedEffect(
                entity=entity,
                attr=attr,
                value=value,
                by=world.clock() + timedelta(seconds=seconds),
            ),
            content_hash="",
        )
    )
    return a.model_copy(update={"content_hash": action_hash(a)})


async def run(output: Path, *, subprocess_worker: bool = True) -> None:
    if output.exists() or output.is_symlink():
        raise ValueError("Audit output must be a new file")
    values = read_env(Path(".env"))
    async with disposable(values) as connection:
        p, world = await setup(connection)
        registry = await compose(p, world=world, config="presence:twin,energy:twin")
        await registry.start()
        try:
            await ingest(p, registry, PRINCIPAL)
            boundary = p.boundary
            p.boundary = AsyncMock()  # zero calls, including native authorization
            a = action(world)
            queued = await p.enqueue(a, PRINCIPAL)
            assert queued.status == "executing", queued
            p.boundary.authorize.assert_not_called()
            p.boundary = boundary
            print(
                "submission=executing; boundary_calls=0; adapter_writes=0; wording=Your request is queued."
            )
            if subprocess_worker:
                process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-c",
                    "from hirz.cli import main; raise SystemExit(main())",
                    "worker",
                    "--household",
                    str(p.household_id),
                    "--once",
                    "--database",
                    str(connection.engine.url.database),
                    env=os.environ
                    | {
                        "HIRZ_TWIN_SCENARIO": str(SCENARIO),
                        "HIRZ_ADAPTERS": "presence:twin,energy:twin",
                        "HIRZ_SIM_SPEED": "0",
                    },
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await process.communicate()
                assert process.returncode == 0, stdout.decode()
                print(stdout.decode().strip())
                async with connection.begin():
                    status = await connection.scalar(
                        sa.select(db.actions.c.execution_status).where(
                            db.actions.c.action_id == a.action_id
                        )
                    )
                assert status == "verified", status
            else:
                executor = Executor(p, registry, world=world)
                result = await executor.sweep()
                assert len(result) == 1 and result[0].status == "verified", result
            summary, rows = await verify_database(
                connection, p.household_id, p.audit.key.public_key(), collect=True
            )
            write_export(
                output, export_document(p.household_id, p.audit.key.public_key(), rows)
            )
            verified = verify_file(
                output,
                p.household_id,
                trusted_fingerprint=fingerprint(p.audit.key.public_key()),
            )
            assert summary["status"] == verified["status"] == "valid"
            print(
                f"worker=verified; signed_rows={len(rows)}; source=twin; engine=dogwood-local"
            )
        finally:
            await registry.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-output", type=Path, required=True)
    parser.add_argument("--live-demo", action="store_true")
    args = parser.parse_args()
    if args.live_demo:
        from scripts.smoke_ha import live

        asyncio.run(
            live(
                Path("config/homeassistant/adapter-demo.yaml"),
                False,
                args.audit_output,
                durable=True,
            )
        )
    else:
        asyncio.run(run(args.audit_output))


if __name__ == "__main__":
    main()
