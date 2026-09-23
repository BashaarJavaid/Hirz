"""Audited constraint transactions in uniquely named disposable databases."""

import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.util.exc import CommandError
from test_database import connect, migrate
from test_database import scratch_database as scratch_database
from test_pipeline_database import setup

from hirz import db
from hirz.audit import verify_database
from hirz.graph.context import ContextService
from hirz.graph.models import Observation, ObservationState
from hirz.pipeline.audit import PipelineError
from hirz.pipeline.models import Principal
from hirz.planner.coordinator import Coordinator
from tests.unit.test_pipeline import HOME, PRINCIPAL, ident

pytestmark = pytest.mark.integration


def test_audited_intake_replacement_permissions_and_rollback(scratch_database):
    async def run():
        async with connect(scratch_database) as connection:
            pipeline = await setup(connection, native=True)
            clock = [pipeline.clock()]
            pipeline.clock = lambda: clock[0]
            coordinator = Coordinator(pipeline)
            end = clock[0] + timedelta(hours=24)

            async def intake(text, principal=PRINCIPAL, **kwargs):
                clock[0] += timedelta(seconds=1)
                return await coordinator.intake(
                    principal,
                    action_id=kwargs.pop("action_id", uuid4().hex),
                    text=text,
                    horizon_end=end,
                    **kwargs,
                )

            # AM/PM clarification is read-only, including actions and audit rows.
            ambiguous = await intake("Dad says kitchen in use until eleven")
            assert ambiguous.clarification
            assert (
                await connection.scalar(
                    sa.select(sa.func.count()).select_from(db.actions)
                )
                == 0
            )
            await connection.rollback()
            first = await intake(
                "Dad says kitchen in use until 23:00", action_id="first"
            )
            assert first.decision.decision == "execute", first
            row = (await connection.execute(sa.select(db.constraints))).mappings().one()
            assert row["member_id"] == ident("members", "malik")
            assert row["attributes"]["provenance"]["claimed_author"] == "Dad"
            count = await connection.scalar(
                sa.select(sa.func.count()).select_from(db.audit_log)
            )
            await connection.rollback()
            repeated = await intake(
                "Dad says kitchen in use until 23:00", action_id="first"
            )
            assert repeated.decision == first.decision
            assert (
                await connection.scalar(
                    sa.select(sa.func.count()).select_from(db.audit_log)
                )
                == count
            )
            await connection.rollback()
            dad = Principal(provider="demo", sub="dad", surface="alexa")
            refused = await intake(
                "withdraw", dad, replaces=first.constraint_id, withdraw=True
            )
            assert refused.clarification and "Only" in refused.clarification
            unknown = await intake(
                "car target to 50",
                Principal(provider="demo", sub="foreign", surface="app"),
            )
            assert unknown.clarification
            own = await intake("car target to 50", dad)
            other = await intake("car target to 60", dad)
            unclear = await intake("change car target to 40", dad)
            assert unclear.clarification
            replacement = await intake(
                "car target to 40", dad, replaces=own.constraint_id
            )
            assert replacement.decision.decision == "execute"
            assert (
                await intake("withdraw", replaces=other.constraint_id, withdraw=True)
            ).decision.decision == "execute"
            context = await ContextService(
                connection, pipeline.clock
            ).get_household_context(HOME, "constraints")
            assert len(context.data["constraints"]) == 4
            assert (
                sum(
                    r.get("withdrawn_at") is not None
                    for r in context.data["constraints"]
                )
                == 2
            )
            before = await connection.scalar(
                sa.select(sa.func.count()).select_from(db.audit_log)
            )
            await connection.rollback()
            real_append = pipeline.audit.append

            async def fail_record(*args, **kwargs):
                if args[3] == "CONSTRAINT_RECORDED":
                    raise RuntimeError("simulated audit failure")
                return await real_append(*args, **kwargs)

            pipeline.audit.append = fail_record
            with pytest.raises(PipelineError):
                await intake(
                    "car target to 45", dad, replaces=replacement.constraint_id
                )
            pipeline.audit.append = real_append
            assert (
                await connection.scalar(
                    sa.select(sa.func.count()).select_from(db.audit_log)
                )
                == before
            )
            assert (
                await connection.scalar(
                    sa.select(db.constraints.c.withdrawn_seq).where(
                        db.constraints.c.id == replacement.constraint_id
                    )
                )
                is None
            )
            await connection.rollback()
            summary, rows = await verify_database(
                connection, HOME, pipeline.audit.key.public_key(), collect=True
            )
            assert summary["status"] == "valid"
            await connection.rollback()
            with pytest.raises(CommandError, match="Migration failed"):
                await migrate(connection, "downgrade", "0005_execution_attempt")
            await connection.rollback()
            assert (
                await connection.scalar(
                    sa.select(sa.func.count()).select_from(db.constraints)
                )
                == 4
            )

    asyncio.run(run())


def test_manual_hold_renewal_release_and_history(scratch_database):
    async def run():
        async with connect(scratch_database) as connection:
            pipeline = await setup(connection, native=True)
            at = pipeline.clock()
            clock = [at]
            pipeline.clock = lambda: clock[0]
            coordinator = Coordinator(pipeline)
            end = at + timedelta(hours=24)
            asset = ident("assets", "hvac.living_room")
            # Bootstrap already has this observation id; the manual mutation must
            # version it through the pipeline together with its hold.
            existing = (
                await connection.execute(
                    sa.select(db.observations.c.id).where(
                        db.observations.c.asset_id == asset
                    )
                )
            ).scalar_one()
            await connection.rollback()

            async def manual(target):
                event = Observation(
                    household_id=HOME,
                    id=existing,
                    asset_id=asset,
                    domain="devices",
                    source="twin",
                    observed_at=clock[0],
                    state=ObservationState(
                        temp_f=70, target_f=target, mode="heat", available=True
                    ),
                )
                return await coordinator.intake(
                    PRINCIPAL,
                    action_id=uuid4().hex,
                    text="Explicit manual twin thermostat event",
                    horizon_end=end,
                    manual=event,
                )

            first = await manual(71)
            assert first.decision.decision == "execute"
            clock[0] += timedelta(minutes=30)
            renewed = await manual(72)
            assert renewed.decision.decision == "execute"
            context = await ContextService(
                connection, pipeline.clock
            ).get_household_context(HOME, "constraints")
            current = [
                r for r in context.data["constraints"] if not r.get("withdrawn_at")
            ]
            assert (
                len(current) == 1
                and current[0]["provenance"]["source"] == "manual:device"
            )
            assert current[0]["provenance"]["encoded"]["ends_at"] == (
                clock[0] + timedelta(hours=2)
            ).isoformat().replace("+00:00", "Z")
            await connection.rollback()
            clock[0] += timedelta(seconds=1)
            dad = Principal(provider="demo", sub="dad", surface="alexa")
            release = await coordinator.intake(
                dad,
                action_id="release",
                text="release living room hold",
                horizon_end=end,
            )
            assert release.decision.decision == "execute"
            history = await ContextService(
                connection, pipeline.clock
            ).get_household_context(
                HOME, "constraints", as_of=at + timedelta(minutes=1)
            )
            assert len(history.data["constraints"]) == 1 and not history.data[
                "constraints"
            ][0].get("withdrawn_at")
            await connection.rollback()
            assert (
                await coordinator.intake(
                    dad,
                    action_id="second-release",
                    text="release living room hold",
                    horizon_end=end,
                )
            ).clarification

    asyncio.run(run())


def test_household_isolation_claimed_role_and_explicit_revision(scratch_database):
    from pathlib import Path

    from hirz.constitution.schema import load
    from hirz.graph.seeds import load_seeds, read_seed
    from hirz.pipeline.service import Pipeline, PolicyBundle
    from tests.unit.test_coordinator import workload
    from tests.unit.test_pipeline import action

    async def run():
        async with connect(scratch_database) as connection:
            pipeline = await setup(connection, native=True)
            clock = [pipeline.clock()]
            pipeline.clock = lambda: clock[0]
            c = Coordinator(pipeline)
            end = clock[0] + timedelta(hours=24)
            dad = Principal(provider="demo", sub="dad", surface="alexa")
            first = await c.intake(
                dad, action_id="dad-target", text="car target to 50", horizon_end=end
            )
            clock[0] += timedelta(seconds=1)
            revised = await c.intake(
                dad,
                action_id="dad-revision",
                text="change car target to 60",
                horizon_end=end,
            )
            assert revised.decision.decision == "execute"
            record = (
                (
                    await connection.execute(
                        sa.select(db.constraints).where(
                            db.constraints.c.id == revised.constraint_id
                        )
                    )
                )
                .mappings()
                .one()
            )
            assert record["attributes"]["replaces"] == str(first.constraint_id)
            await connection.rollback()
            denied = await c.intake(
                PRINCIPAL.model_copy(update={"claimed_role": "child"}),
                action_id="lower-authority",
                text="withdraw",
                horizon_end=end,
                replaces=revised.constraint_id,
                withdraw=True,
            )
            assert denied.clarification
            direct = action(
                "governance.withdraw_constraint",
                params={
                    "text": "withdraw",
                    "horizon_end": end.isoformat(),
                    "replaces": str(revised.constraint_id),
                    "manual": None,
                },
            )
            assert (
                await pipeline.evaluate(
                    direct, PRINCIPAL.model_copy(update={"claimed_role": "child"})
                )
            ).decision == "deny"
            assert (
                await pipeline.propose(direct, dad.model_copy(update={"sub": "mom"}))
            ).decision == "deny"
            spoof = await c.intake(
                PRINCIPAL,
                action_id="dad-target",
                text="car target to 50",
                horizon_end=end,
            )
            assert spoof.decision.event_type == "DENY_APPROVAL_MISMATCH"
            # Constraint operations must never clear a paused household.
            clock[0] += timedelta(seconds=1)
            assert (
                await pipeline.redeem(action("governance.pause_automation"), PRINCIPAL)
            ).decision == "execute"
            clock[0] += timedelta(seconds=1)
            assert (
                await c.intake(
                    dad,
                    action_id="while-paused",
                    text="car target to 70",
                    horizon_end=end,
                )
            ).decision.decision == "execute"
            assert (await pipeline.repo.get("households", {}))["attributes"][
                "autonomy_paused"
            ]
            await connection.rollback()
            parents = read_seed(Path("constitutions/quinn-parents.yaml"))
            await load_seeds(connection, [parents], lambda: clock[0])
            bundle = await PolicyBundle.validate(
                parents.household_id,
                load(Path("constitutions/quinn-parents.yaml")),
                pipeline.boundary,
            )
            other = Coordinator(
                Pipeline(
                    connection,
                    bundle,
                    pipeline.boundary,
                    pipeline.audit,
                    pipeline.clock,
                )
            )
            failed = await other.intake(
                dad,
                action_id="cross-house",
                text="withdraw",
                horizon_end=end,
                replaces=revised.constraint_id,
                withdraw=True,
            )
            assert failed.clarification
            assert not (
                await ContextService(connection, pipeline.clock).get_household_context(
                    parents.household_id, "constraints"
                )
            ).data["constraints"]
            await connection.rollback()
            with pytest.raises(ValueError, match="another household"):
                await other.plan(dad, workload())

    asyncio.run(run())
