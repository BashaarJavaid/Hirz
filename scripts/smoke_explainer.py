"""Offline narration; optional disposable PostgreSQL publication and signed export."""

import argparse
import asyncio
from pathlib import Path

from hirz.explainer.core import Context, TemplateExplainer, attach, enriched, prepared
from hirz.explainer.models import Details
from hirz.pipeline.models import Plan
from hirz.planner.service import plan
from hirz.planner.workload import demo_input


async def offline() -> None:
    inputs = demo_input()
    result = plan(inputs)
    assert result.plan is not None
    before = result.plan.model_dump(exclude={"speakable", "narration"})
    ctx = Context(inputs.household_id)
    n = await TemplateExplainer().narrate(result.plan, ctx)
    try:
        enriched(
            result.plan,
            ctx,
            Details(details=("Save $999999.99.",), screen_summary="Fabricated figure."),
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Fabricated figure accepted")
    restored = Plan.model_validate_json(attach(result.plan, n).model_dump_json())
    assert prepared(restored, ctx) == restored
    assert before == restored.model_dump(exclude={"speakable", "narration"})
    print(
        f"offline=PASS; fabricated_figure=rejected; canonical_plan=unchanged; actions={len(result.actions)}; cached=valid"
    )
    print(restored.speakable)


async def integration(output: Path) -> None:
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
    from hirz.explainer.core import context
    from hirz.local import read_env
    from hirz.pipeline.service import Pipeline
    from hirz.planner.coordinator import Coordinator
    from scripts.smoke_executor import PRINCIPAL, action, setup
    from scripts.smoke_ha import disposable

    if output.exists() or output.is_symlink():
        raise ValueError("Audit output must be a new file")
    async with disposable(read_env(Path(".env"))) as connection:
        p, world = await setup(connection)
        inputs = demo_input().model_copy(update={"household_id": p.household_id})
        world.clock.jump(inputs.slots[0].start)
        registry = await compose(p, world=world, config="presence:twin,energy:twin")
        await registry.start()
        try:
            for member, presence in world.read()[1].presence.items():
                if presence.present and presence.zone_id is None:
                    world.member_event(
                        member, "arrive", world.entity("hvac.living_room", "devices")
                    )
            await ingest(p, registry, PRINCIPAL)
            a = action(world)
            preview = await p.evaluate(a, PRINCIPAL)
            queued = await p.enqueue(a, PRINCIPAL)
            assert preview.narration and queued.narration
            assert (
                queued.speakable
                and queued.speakable["headline"] == "Your request is queued."
            )
            coordinated = await Coordinator(p).plan(PRINCIPAL, inputs)
            result = coordinated.result
            assert result.plan is not None
            recorded = await PlanService(p).record(
                result.plan, result.actions, PRINCIPAL
            )
            assert recorded.decision == "execute", recorded
            async with connection.begin():
                stored = await get(p, result.plan.plan_id)
                original = Plan.model_validate(stored["document"])
            restart = Pipeline(connection, p.bundle, p.boundary, p.audit, p.clock)
            async with connection.begin():
                reloaded = Plan.model_validate(
                    (await get(restart, original.plan_id))["document"]
                )
                ctx = context(await restart.snapshot(restart.clock()))
            assert prepared(reloaded, ctx) == original
            summary, rows = await verify_database(
                connection, p.household_id, p.audit.key.public_key(), collect=True
            )
            publications = [
                r
                for r in rows
                if r.event_type == "PLAN_CREATED" and "mutation" in r.payload
            ]
            assert publications
            for row in publications:
                mutation = row.payload["mutation"]
                assert isinstance(mutation, dict)
                document = mutation["plan"]
                assert isinstance(document, dict) and document["narration"]
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
                f"integration=PASS; decision=audited; plan=audited; restart=reused; source=twin; signed_rows={len(rows)}; offline=valid; export={output}"
            )
        finally:
            await registry.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--integration", action="store_true")
    parser.add_argument("--audit-output", type=Path)
    args = parser.parse_args()
    if args.integration != bool(args.audit_output):
        parser.error("--integration requires --audit-output <new-file>")
    asyncio.run(integration(args.audit_output) if args.integration else offline())


if __name__ == "__main__":
    main()
