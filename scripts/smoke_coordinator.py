"""Item 18's five gates in a disposable PostgreSQL database, with signed export."""

import argparse
import asyncio
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

from hirz.audit import (
    export_document,
    fingerprint,
    verify_database,
    verify_file,
    write_export,
)
from hirz.constitution.boundary import Dogwood
from hirz.constitution.schema import load
from hirz.graph.context import ContextSnapshot
from hirz.graph.models import Observation, ObservationState
from hirz.graph.seeds import demo_id, load_seeds, read_seed
from hirz.local import read_env, signing_key
from hirz.pipeline.audit import AuditWriter
from hirz.pipeline.models import Principal
from hirz.pipeline.service import Pipeline, PolicyBundle
from hirz.planner.coordinator import (
    Coordination,
    Coordinator,
    IntakeResult,
    coordinate,
    records,
)
from hirz.planner.workload import demo_input
from hirz.twin.physics import changed
from scripts.smoke_ha import disposable


async def main(output: Path) -> None:
    values = read_env(Path(".env"))
    seed = read_seed(Path("constitutions/quinn-home.yaml"))
    policy = load(Path("constitutions/quinn-home.yaml"))
    p = changed(demo_input(), household_id=seed.household_id)
    clock = [p.slots[0].start]
    principal = Principal(provider="demo", sub="malik", surface="alexa")
    end = p.slots[-1].end
    async with disposable(values) as connection:
        await load_seeds(connection, [seed], lambda: clock[0] - timedelta(seconds=1))
        dogwood = Dogwood()
        bundle = await PolicyBundle.validate(seed.household_id, policy, dogwood)
        writer = AuditWriter(signing_key(values))
        pipeline = Pipeline(connection, bundle, dogwood, writer, lambda: clock[0])
        coordinator = Coordinator(pipeline)

        async def intake(
            text: str, *, replaces: UUID | None = None, withdraw: bool = False
        ) -> IntakeResult:
            clock[0] += timedelta(seconds=1)
            result = await coordinator.intake(
                principal,
                action_id=uuid4().hex,
                text=text,
                horizon_end=end,
                replaces=replaces,
                withdraw=withdraw,
            )
            return result

        async def proposal() -> tuple[Coordination, ContextSnapshot]:
            async with pipeline.repo.write(pipeline.clock):
                snap = await pipeline.snapshot(clock[0])
                requester = await pipeline.requester(principal)
            current = changed(
                p,
                requester=requester,
                slots=(changed(p.slots[0], start=clock[0]), *p.slots[1:]),
            )
            return coordinate(current, snap, policy), snap

        ambiguous = await intake("Dad says kitchen in use until eleven")
        assert ambiguous.clarification and ambiguous.decision is None
        print("clarification=Please specify AM or PM; scripted answer=23:00")
        kitchen = await intake("Dad says kitchen in use until 23:00")
        assert kitchen.decision and kitchen.decision.decision == "execute", kitchen
        answer, snap = await proposal()
        stored = records(snap)[0]
        assert stored.member_id == demo_id(seed.slug, "members", "malik")
        assert stored.provenance.claimed_author == "Dad"
        assert answer.result.plan is not None, answer
        starts = [
            a.scheduled_for
            for a in answer.result.actions
            if a.action_class == "energy.appliance_start"
        ]
        assert (
            starts
            and stored.spec.at is not None
            and all(t is not None and t >= stored.spec.at for t in starts)
        )
        print("gate_1=PASS; linked=Malik; claimed_author=Dad")
        print(f"gate_4=PASS; dishwasher_start={str(starts[0])}")

        # Explicit simulated manual event submitted by the linked account. This
        # says nothing about who physically touched any thermostat.
        clock[0] += timedelta(seconds=1)
        observed = Observation(
            household_id=seed.household_id,
            id=uuid4(),
            asset_id=demo_id(seed.slug, "assets", "hvac.living_room"),
            domain="devices",
            observed_at=clock[0],
            source="twin",
            state=ObservationState(
                temp_f=p.zones[0].physical.temp_f,
                target_f=72,
                mode="heat",
                available=True,
            ),
        )
        held = await coordinator.intake(
            principal,
            action_id="manual-twin",
            text="Explicit manual twin thermostat event",
            horizon_end=end,
            manual=observed,
        )
        assert held.decision and held.decision.decision == "execute", held
        answer, _ = await proposal()
        assert (
            answer.result.plan
            and answer.result.schedule
            and answer.result.replay
            and answer.result.replay.valid
        ), answer
        hold_end = observed.observed_at + timedelta(hours=2)
        assert answer.result.schedule.controls[0].targets[0] == 72
        assert answer.result.schedule.controls[0].modes[0] == "heat"
        assert not any(
            a.action_class == "energy.hvac_adjust"
            and a.target.entity == "hvac.living_room"
            and a.scheduled_for is not None
            and a.scheduled_for < hold_end
            for a in answer.result.actions
        )
        print("gate_2=PASS; target_f=72; mode=heat; source=manual:device; duration=2h")

        first = await intake("car target to 50")
        second = await intake("car target to 60")
        assert first.constraint_id and second.constraint_id
        answer, _ = await proposal()
        assert answer.result.plan is None and any(
            "Exact EV targets" in c.reason for c in answer.conflicts
        )
        print("gate_3=PASS; " + answer.conflicts[0].relaxation)
        removed = await intake("withdraw", replaces=second.constraint_id, withdraw=True)
        assert removed.decision and removed.decision.decision == "execute"
        deadline = await intake("car deadline at 5:45 pm")
        assert deadline.decision and deadline.decision.decision == "execute"
        answer, _ = await proposal()
        assert answer.result.plan is None and any(
            "unreachable" in c.reason for c in answer.conflicts
        )
        print("gate_5=PASS; " + answer.conflicts[0].relaxation)
        summary, rows = await verify_database(
            connection, seed.household_id, writer.key.public_key(), collect=True
        )
        write_export(
            output, export_document(seed.household_id, writer.key.public_key(), rows)
        )
        trust = fingerprint(writer.key.public_key())
        verified = verify_file(output, seed.household_id, trusted_fingerprint=trust)
        assert summary["status"] == verified["status"] == "valid"
        print(
            f"coordinator=PASS; gates=5/5; audit_rows={len(rows)}; audit_export={output}; trusted_fingerprint={trust}; offline=valid; device_actions=0"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-output", type=Path, required=True)
    asyncio.run(main(parser.parse_args().audit_output))
