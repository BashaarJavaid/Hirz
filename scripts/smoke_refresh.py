"""Refresh with process restart and signed evidence in a disposable database."""

import argparse
import asyncio
import os
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

from hirz.adapters.registry import Registry
from hirz.audit import (
    export_document,
    fingerprint,
    verify_database,
    verify_file,
    write_export,
)
from hirz.executor.local import compose
from hirz.executor.observations import ingest
from hirz.executor.plans import PlanService, get
from hirz.executor.refresh import job
from hirz.executor.refresh_worker import RefreshWorker
from hirz.executor.replanning import bind_result
from hirz.executor.runtime import RuntimeInputs
from hirz.local import read_env
from hirz.pipeline.service import Pipeline
from hirz.planner.models import PlannerInput, Slot, Zone, boundaries
from hirz.planner.service import plan
from hirz.twin.physics import ThermalZone
from hirz.twin.world import TwinWorld
from scripts.smoke_executor import PRINCIPAL, SCENARIO, setup
from scripts.smoke_ha import disposable


async def exercise(
    p: Pipeline, registry: Registry, *, world: TwinWorld | None = None
) -> None:
    await ingest(p, registry, PRINCIPAL)
    async with p.connection.begin():
        snapshot = await p.snapshot(p.clock())
        requester = await p.requester(PRINCIPAL)
    data: Any = snapshot.data
    entity = "hvac.living_room" if world else "climate.heatpump"
    binding = next(b for b in data["asset_bindings"] if b["entity_id"] == entity)
    obs = next(
        o
        for o in data["observations"]
        if str(o.get("asset_id")) == str(binding["asset_id"])
    )
    at = snapshot.as_of
    edges = boundaries(at, at + timedelta(hours=2))
    physical = ThermalZone(
        temp_f=obs["state"]["temp_f"],
        target_f=obs["state"]["target_f"],
        mode=obs["state"]["mode"],
        thermal_mass_kwh_per_f=50,
        solar_gain_area_m2=0,
    )
    specs: dict[str, Any] = {}
    if not world:
        facts = await RefreshWorker(p, registry).ha_facts({entity})
        specs = dict(
            control_mode=facts[entity]["mode"],
            setpoint_step_f=facts[entity]["step"],
            setpoint_origin_f=facts[entity]["origin"],
            setpoint_lower_f=66,
            setpoint_upper_f=76,
        )
    slots = tuple(
        Slot(start=a, end=b, price=0.1, outdoor_f=physical.temp_f, solar_kw=0)
        for a, b in zip(edges, edges[1:])
    )
    inputs = PlannerInput(
        household_id=p.household_id,
        requester=requester,
        slots=slots,
        ev=None,
        ev_target=0,
        ev_deadline=edges[-1],
        battery=None,
        appliance=None,
        appliance_release=at,
        appliance_deadline=edges[-1],
        base_load_kw=0.4,
        actuator_precision=True,
        zones=(
            Zone(
                entity=entity,
                physical=physical,
                lower=(66,) * len(slots),
                upper=(80 if not world else 76,) * len(slots),
                end_upper=80 if not world else 76,
                targets=(72,) * len(slots),
                occupants=(0,) * len(slots),
                **specs,
            ),
        ),
        provenance=(
            "Explicit synthetic thermal model and forecast for disposable refresh verification",
        ),
    )
    result = await asyncio.to_thread(plan, inputs)
    assert result.plan and result.schedule, result.model_dump_json()
    result = bind_result(result, inputs, result.plan, {entity: binding}, ())
    assert result.plan and result.schedule
    runtime = RuntimeInputs.from_schedule(inputs, result.schedule)
    service = PlanService(p)
    assert (
        await service.record(result.plan, result.actions, PRINCIPAL, runtime=runtime)
    ).decision == "execute"
    approved = await service.approve(result.plan.plan_id, PRINCIPAL)
    assert approved.decision == "execute", approved.model_dump_json()
    current_id = result.plan.plan_id
    try:
        for interrupted in (False, True):
            await service.request_refresh(
                current_id, PRINCIPAL, reason="Restart verification", explicit=False
            )
            if interrupted:
                async with p.repo.write(p.clock):
                    stored = await get(p, current_id)
                    queued = await job(p, stored)
                    assert queued
                    await RefreshWorker(p, registry, world=world).transition(
                        stored,
                        queued["requested_generation"],
                        PRINCIPAL.model_copy(update={"surface": "scheduler"}),
                        state="running",
                        running_generation=queued["requested_generation"],
                        attempts=1,
                    )
            env = os.environ | {
                "HIRZ_ADAPTERS": "presence:twin,energy:twin" if world else "devices:ha",
                "HIRZ_SIM_SPEED": "0",
            }
            if world:
                env["HIRZ_TWIN_SCENARIO"] = str(SCENARIO)
            else:
                env.pop("HIRZ_TWIN_SCENARIO", None)
                env["HIRZ_HA_CONFIG"] = str(
                    Path("config/homeassistant/adapter-demo.yaml").resolve()
                )
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                "from hirz.cli import main; raise SystemExit(main())",
                "worker",
                "--household",
                str(p.household_id),
                "--once",
                "--database",
                str(p.connection.engine.url.database),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()
            assert process.returncode == 0, stdout.decode()
            async with p.connection.begin():
                status = await job(p, await get(p, current_id))
                assert status and status["state"] == "idle", status
                replacement = await get(p, status["plan_id"])
                assert replacement["document"]["status"] in {
                    "approved",
                    "active",
                    "completed",
                }, replacement["document"]["status"]
                assert replacement["approver"]["sub"] == "malik"
                assert replacement["document"]["horizon"][
                    "end"
                ] == result.plan.horizon.end.isoformat().replace("+00:00", "Z")
                current_id = status["plan_id"]
            if world:
                from hirz.executor.twin import restore

                await restore(p, world)
            print(
                f"restart={'running' if interrupted else 'queued'}; replacement=published; approver=malik; per_device_evaluation=fresh"
            )
    finally:
        await service.cancel(current_id, PRINCIPAL)


async def run(output: Path) -> None:
    if output.exists() or output.is_symlink():
        raise ValueError("Audit output must be a new file")
    async with disposable(read_env(Path(".env"))) as connection:
        p, world = await setup(connection)
        for member, presence in world.read()[1].presence.items():
            if presence.present and presence.zone_id is None:
                world.member_event(
                    member, "arrive", world.entity("hvac.living_room", "devices")
                )
        registry = await compose(p, world=world, config="presence:twin,energy:twin")
        await registry.start()
        try:
            await exercise(p, registry, world=world)
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
                f"refresh=PASS; source=twin; signed_rows={len(rows)}; offline=valid; export={output}"
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
                refresh=True,
            )
        )
    else:
        asyncio.run(run(args.audit_output))


if __name__ == "__main__":
    main()
