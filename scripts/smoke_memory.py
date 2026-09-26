"""Consent-gated memory and fresh-worker refresh in a disposable twin household."""

import argparse
import asyncio
import os
import sys
from datetime import timedelta
from pathlib import Path

import sqlalchemy as sa

from hirz import db
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
from hirz.executor.replanning import bind_result
from hirz.executor.runtime import RuntimeInputs
from hirz.local import read_env
from hirz.memory.models import Candidate, Proposal, Turn, TurnInput
from hirz.memory.service import MemoryService
from hirz.pipeline.models import Decision
from hirz.pipeline.service import Pipeline
from hirz.planner.coordinator import coordinate
from hirz.planner.models import PlannerInput, Slot, Zone, boundaries
from hirz.twin.physics import ThermalZone
from scripts.smoke_executor import PRINCIPAL, SCENARIO, setup
from scripts.smoke_ha import disposable


async def run(output: Path) -> None:
    if output.exists() or output.is_symlink():
        raise ValueError("Audit output must be a new file")
    async with disposable(read_env(Path(".env"))) as connection:
        p, world = await setup(connection)
        async with connection.begin():
            member = (await p.requester(PRINCIPAL)).member_id
        for person, presence in world.read()[1].presence.items():
            if presence.present:
                world.member_event(
                    person,
                    "arrive",
                    world.entity(
                        "hvac.living_room"
                        if str(person) == member
                        else "hvac.guest_room",
                        "devices",
                    ),
                )
        registry = await compose(p, world=world, config="presence:twin,energy:twin")
        await registry.start()
        try:
            await ingest(p, registry, PRINCIPAL)
            memory = MemoryService(p)
            recorded = await memory.record_turn(
                PRINCIPAL,
                action_id="memory-source",
                turn=TurnInput(
                    session_id="smoke", role="user", text="Mom says I prefer 74 degrees"
                ),
            )
            assert isinstance(recorded.record, Turn)
            assert str(recorded.record.session.member_id) == member
            async with connection.begin():
                before = await p.snapshot(p.clock())
                requester = await p.requester(PRINCIPAL)
            at = before.as_of
            edges = boundaries(at, at + timedelta(hours=2))
            slots = tuple(
                Slot(start=a, end=b, price=0.1, outdoor_f=70, solar_kw=0)
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
                        entity="hvac.living_room",
                        physical=ThermalZone(
                            temp_f=70,
                            target_f=70,
                            mode="off",
                            thermal_mass_kwh_per_f=50,
                            solar_gain_area_m2=0,
                        ),
                        lower=(66,) * len(slots),
                        upper=(76,) * len(slots),
                        targets=(70,) * len(slots),
                        occupants=(0,) * len(slots),
                    ),
                ),
                provenance=(
                    "Explicit synthetic memory-smoke thermal model and forecast",
                ),
            )
            baseline = await asyncio.to_thread(
                coordinate, inputs, before, p.bundle.policy()
            )
            assert baseline.inputs and baseline.result.plan and baseline.result.schedule
            pending = await memory.propose(
                PRINCIPAL,
                action_id="memory-proposal",
                source_turn=recorded.record.id,
                candidate=Candidate(value=74, confidence=1),
            )
            assert isinstance(pending.record, Proposal)
            async with connection.begin():
                snapshot = await p.snapshot(at)
            waiting = await asyncio.to_thread(
                coordinate, inputs, snapshot, p.bundle.policy()
            )
            assert waiting.inputs == baseline.inputs
            rejected = await memory.review(
                PRINCIPAL,
                action_id="memory-reject",
                proposal_id=pending.record.id,
                accept=False,
            )
            assert rejected.decision.decision == "execute"
            async with connection.begin():
                snapshot = await p.snapshot(at)
            assert (
                await asyncio.to_thread(coordinate, inputs, snapshot, p.bundle.policy())
            ).inputs == baseline.inputs
            pending = await memory.propose(
                PRINCIPAL,
                action_id="memory-reproposal",
                source_turn=recorded.record.id,
                candidate=Candidate(value=74, confidence=1),
            )
            assert isinstance(pending.record, Proposal)
            binding = next(
                b
                for b in before.data["asset_bindings"]
                if b["entity_id"] == "hvac.living_room"
            )
            result = bind_result(
                baseline.result,
                baseline.inputs,
                baseline.result.plan,
                {"hvac.living_room": binding},
                (),
            )
            assert result.plan and result.schedule
            plans = PlanService(p)
            runtime = RuntimeInputs.from_schedule(baseline.inputs, result.schedule)
            assert (
                await plans.record(
                    result.plan, result.actions, PRINCIPAL, runtime=runtime
                )
            ).decision == "execute"
            assert (
                await plans.approve(result.plan.plan_id, PRINCIPAL)
            ).decision == "execute"
            accepted = await memory.review(
                PRINCIPAL,
                action_id="memory-accept",
                proposal_id=pending.record.id,
                accept=True,
            )
            assert accepted.decision.decision == "execute", accepted
            async with connection.begin():
                status = await job(p, await get(p, result.plan.plan_id))
                assert status and status["state"] == "queued" and not status["explicit"]
                snapshot = await p.snapshot(at)
            effective = await asyncio.to_thread(
                coordinate, inputs, snapshot, p.bundle.policy()
            )
            assert effective.inputs and effective.inputs.zones[0].preferences[0] == 74
            # A new service with an empty provider reads the durable source turn.
            fresh = MemoryService(
                Pipeline(connection, p.bundle, p.boundary, p.audit, p.clock)
            )
            assert (await fresh.turns(PRINCIPAL, "smoke"))[0] == recorded.record
            env = os.environ | {
                "HIRZ_ADAPTERS": "presence:twin,energy:twin",
                "HIRZ_SIM_SPEED": "0",
                "HIRZ_TWIN_SCENARIO": str(SCENARIO),
            }
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                "from hirz.cli import main; raise SystemExit(main())",
                "worker",
                "--historical-fixture",
                "--household",
                str(p.household_id),
                "--once",
                "--database",
                str(connection.engine.url.database),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            assert process.returncode == 0, stdout.decode() + stderr.decode()
            async with connection.begin():
                status = await job(p, await get(p, result.plan.plan_id))
                assert status and status["state"] == "idle", status
                replacement = await get(p, status["plan_id"])
                assert replacement["approver"]["sub"] == "malik"
                assert replacement["document"]["status"] in {
                    "approved",
                    "active",
                    "completed",
                }
                assert any(
                    c["source"].startswith("preference:")
                    for c in replacement["document"]["constraints"]
                )
                obsolete = (
                    (
                        await connection.execute(
                            sa.select(db.actions)
                            .join(
                                db.plan_actions,
                                sa.and_(
                                    db.actions.c.household_id
                                    == db.plan_actions.c.household_id,
                                    db.actions.c.action_id
                                    == db.plan_actions.c.action_id,
                                ),
                            )
                            .where(
                                p.scope(db.actions),
                                db.plan_actions.c.plan_id == result.plan.plan_id,
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
                assert all(r["execution_attempt_seq"] is None for r in obsolete)
            from hirz.executor.twin import restore

            await restore(p, world)
            await plans.cancel(status["plan_id"], PRINCIPAL)
            summary, rows = await verify_database(
                connection, p.household_id, p.audit.key.public_key(), collect=True
            )
            attempts = [r for r in rows if r.event_type == "EXECUTION_ATTEMPTED"]
            assert attempts and accepted.decision.audit_id is not None
            for attempt in attempts:
                grant = next(r for r in rows if r.seq == attempt.payload["grant_seq"])
                assert grant.seq > accepted.decision.audit_id
                decision = Decision.model_validate(grant.payload)
                assert decision.boundary.engine == "dogwood-local"
                assert decision.boundary.result == "allow"
            assert any(r.event_type == "VERIFIED" for r in rows)
            write_export(
                output, export_document(p.household_id, p.audit.key.public_key(), rows)
            )
            checked = verify_file(
                output,
                p.household_id,
                trusted_fingerprint=fingerprint(p.audit.key.public_key()),
            )
            assert summary["status"] == checked["status"] == "valid"
            print(
                f"memory=PASS; pending/rejected=unchanged; accepted=74F; service_restart=persisted; worker_restart=published; approver=malik; device_grant=fresh; obsolete_attempts=0; source=twin; signed_rows={len(rows)}; offline=valid; export={output}"
            )
        finally:
            await registry.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-output", type=Path, required=True)
    asyncio.run(run(parser.parse_args().audit_output))


if __name__ == "__main__":
    main()
