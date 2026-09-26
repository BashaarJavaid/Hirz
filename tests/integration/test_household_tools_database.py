"""Tool effects, retries and isolation through native policy and disposable PostgreSQL."""

import asyncio

import pytest
import sqlalchemy as sa
from test_database import connect
from test_database import scratch_database as scratch_database
from test_pipeline_database import setup

from hirz import db
from hirz.audit import verify_database
from hirz.mcp.household import HouseholdTools
from hirz.mcp.worker import prepare_plans
from hirz.pipeline.models import Principal
from tests.conftest import assert_no_identifiers
from tests.unit.test_pipeline import HOME, PRINCIPAL

pytestmark = pytest.mark.integration


def test_profiles_queue_each_device_and_preserve_retry_and_preview_boundaries(
    scratch_database,
):
    from test_executor_database import environment

    from hirz.mcp.profiles import Profile

    async def run():
        async with connect(scratch_database) as connection:
            p, world, registry, executor = await environment(connection)
            try:
                fixture = Profile.model_validate(
                    {
                        "settings": [
                            {
                                "action": "set_temperature",
                                "room": "Living room",
                                "temperature_f": 72,
                            },
                            {"action": "turn_on_light", "room": "Living room"},
                        ]
                    }
                )
                tools = HouseholdTools(p, PRINCIPAL, profiles={"night": fixture})
                args = dict(
                    action="apply_profile", profile="night", request_id="bundle"
                )
                missing = await HouseholdTools(p, PRINCIPAL).call(
                    "execute_household_action", args
                )
                assert_no_identifiers(missing.speakable)
                assert missing.data.code == "PROFILE_UNAVAILABLE"
                preview = await tools.call(
                    "evaluate_permission", args | {"request_id": "preview"}
                )
                assert_no_identifiers(preview.speakable)
                assert len(preview.data.decisions) == 2
                assert all(
                    d.audit_id is None
                    for d in (preview.data.decision, *preview.data.decisions)
                )
                answer = await tools.call(
                    "execute_household_action", args | {"request_id": "configured"}
                )
                assert_no_identifiers(answer.speakable)
                assert answer.data.status == "queued", answer
                assert len(answer.data.decisions) == 2
                retry = await HouseholdTools(p, PRINCIPAL).call(
                    "execute_household_action", args | {"request_id": "configured"}
                )
                assert_no_identifiers(retry.speakable)
                assert retry == answer
                with pytest.raises(ValueError, match="REQUEST_CONFLICT"):
                    await tools.call(
                        "execute_household_action",
                        args | {"request_id": "configured", "profile": "away"},
                    )
                assert await executor.sweep()
                async with connection.begin():
                    statuses = (
                        (
                            await connection.execute(
                                sa.select(db.actions.c.execution_status).where(
                                    p.scope(db.actions),
                                    db.actions.c.action_id.in_(
                                        [d.action_id for d in answer.data.decisions]
                                    ),
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                    assert statuses == ["verified", "verified"]
                denied = await tools.call(
                    "execute_household_action",
                    args
                    | {"request_id": "claimed", "claimed_requester": "unknown person"},
                )
                assert_no_identifiers(denied.speakable)
                assert (
                    denied.data.decision.decision == "deny"
                    and not denied.data.decisions
                )
                await tools.call(
                    "execute_household_action",
                    dict(action="pause_automation", request_id="pause-profile"),
                )
                paused = await tools.call(
                    "execute_household_action", args | {"request_id": "paused"}
                )
                assert_no_identifiers(paused.speakable)
                assert (
                    paused.data.decision.decision == "ask" and not paused.data.decisions
                )
                approval = paused.data.decision.approval
                voted = await tools.call(
                    "approve_action",
                    dict(
                        action_id=paused.data.decision.action_id,
                        approval_id=approval.approval_id,
                        approved=True,
                        request_id="approve-profile",
                    ),
                )
                assert_no_identifiers(voted.speakable)
                assert len(voted.data.decisions) == 2, voted
                assert all(d.decision == "ask" for d in voted.data.decisions)
                evidence, _ = await verify_database(
                    connection, p.household_id, p.audit.key.public_key()
                )
                assert evidence["status"] == "valid"
            finally:
                await registry.close()

    asyncio.run(run())


def test_objective_change_is_durable_and_invalidates_exact_consent(scratch_database):
    from test_refresh_database import prepared

    from hirz.executor.plans import get
    from hirz.executor.refresh import job
    from hirz.executor.refresh_worker import RefreshWorker

    async def run():
        async with connect(scratch_database) as connection:
            p, world, registry, executor, service, result, runtime = await prepared(
                connection
            )
            try:
                await service.approve(result.plan.plan_id, PRINCIPAL)
                tools = HouseholdTools(p, PRINCIPAL)
                args = dict(objective="greenest", request_id="objective")
                changed = await tools.call("get_household_plan", args)
                assert_no_identifiers(changed.speakable)
                assert changed.data.status == "preparing", changed
                replayed = await HouseholdTools(p, PRINCIPAL).call(
                    "get_household_plan", args
                )
                assert_no_identifiers(replayed.speakable)
                assert replayed == changed
                refused = await tools.call(
                    "approve_action",
                    dict(
                        plan_id=result.plan.plan_id,
                        version=result.plan.version,
                        approved=True,
                        request_id="old-consent",
                    ),
                )
                assert_no_identifiers(refused.speakable)
                assert refused.data.code == "PLAN_CHANGED"
                async with connection.begin():
                    stored = await get(p, result.plan.plan_id)
                    assert stored["runtime"]["workload"]["objective"] == "greenest"
                    queued = await job(p, stored)
                    assert queued["explicit"]
                worker = RefreshWorker(p, registry, world=world)
                await worker.batch()
                async with connection.begin():
                    state = await job(p, await get(p, result.plan.plan_id))
                    assert state["state"] == "idle", (
                        state["blocking_reason"],
                        state["reasons"],
                    )
                current = await tools.call("get_household_plan", {})
                assert_no_identifiers(current.speakable)
                assert (
                    current.data.plan
                    and current.data.plan.goals[0] == "minimize_grid_import"
                ), current
                assert current.data.plan.status == "proposed"
            finally:
                await registry.close()

    asyncio.run(run())


def test_tool_transactions_retries_privacy_and_missing_worker_inputs(
    scratch_database, monkeypatch
):
    async def run():
        async with connect(scratch_database) as connection:
            p = await setup(connection, native=True)

            def forbidden(*args, **kwargs):
                raise AssertionError(
                    "Tools cannot compile, solve, or use external HTTP"
                )

            monkeypatch.setattr("hirz.pipeline.service.compile_policy", forbidden)
            monkeypatch.setattr("hirz.planner.service.plan", forbidden)
            monkeypatch.setattr("httpx.AsyncClient.send", forbidden)
            monkeypatch.setattr(p.boundary, "validate", forbidden)
            tools = HouseholdTools(p, PRINCIPAL)
            with pytest.raises(ValueError, match="policy changed"):
                await HouseholdTools(p, PRINCIPAL, policy_hash="stale").call(
                    "get_household_context", {}
                )
            proposal = {
                "text": "Never unlock for unexpected visitors.",
                "request_id": "proposal",
            }
            answer = await tools.call("propose_household_rule", proposal)
            assert_no_identifiers(answer.speakable)
            assert answer.data.status == "recorded"
            assert "not been activated" in answer.speakable.headline
            count = await connection.scalar(
                sa.select(sa.func.count()).select_from(db.audit_log)
            )
            await connection.rollback()
            # A fresh service instance simulates retry after server restart.
            retry = await HouseholdTools(p, PRINCIPAL).call(
                "propose_household_rule", proposal
            )
            assert_no_identifiers(retry.speakable)
            assert answer == retry
            assert count == await connection.scalar(
                sa.select(sa.func.count()).select_from(db.audit_log)
            )
            await connection.rollback()
            with pytest.raises(ValueError, match="REQUEST_CONFLICT"):
                await tools.call(
                    "propose_household_rule", proposal | {"text": "Changed"}
                )
            missing = await tools.call(
                "execute_household_action",
                dict(action="set_temperature", request_id="missing"),
            )
            assert_no_identifiers(missing.speakable)
            assert missing.data.status == "clarification"
            invalid = await tools.call(
                "execute_household_action",
                dict(action="turn_on_light", room="foreign", request_id="foreign"),
            )
            assert_no_identifiers(invalid.speakable)
            assert invalid.data.status == "clarification"
            revision = await tools.call(
                "revise_household_plan",
                dict(
                    text="The car stops at fifty",
                    applies_to="car",
                    kind="one_time",
                    operation="add",
                    change="car_limit",
                    percent=50,
                    claimed_author="Dad",
                    request_id="revise",
                ),
            )
            assert_no_identifiers(revision.speakable)
            assert revision.data.status == "recorded", revision
            assert revision.data.constraint_id
            context = await tools.call(
                "get_household_context", {"scope": "constraints"}
            )
            assert_no_identifiers(context.speakable)
            assert (
                context.data.context.data["constraints"][0]["provenance"][
                    "claimed_author"
                ]
                == "Dad"
            )
            history = await tools.call("get_action_audit", {"limit": 2})
            assert_no_identifiers(history.speakable)
            assert len(history.data.audit) == 2
            assert "unexpected visitors" not in history.model_dump_json()
            queued = await tools.call("get_household_plan", {"request_id": "plan"})
            assert_no_identifiers(queued.speakable)
            assert queued.data.status == "preparing", queued
            await prepare_plans(p, None)
            failed = await tools.call("get_household_plan", {})
            assert_no_identifiers(failed.speakable)
            assert failed.data.code == "PREPARATION_FAILED", failed

            # A solver/input worker failure is durable and never fabricates a plan.
            from datetime import timedelta
            from types import SimpleNamespace

            await tools.call("get_household_plan", {"request_id": "worker-error"})

            def failed_inputs(*args, **kwargs):
                raise RuntimeError("Synthetic worker failure")

            monkeypatch.setattr("hirz.mcp.worker.workload_input", failed_inputs)
            fixture = SimpleNamespace(
                world=SimpleNamespace(
                    household=SimpleNamespace(id=HOME),
                    config=SimpleNamespace(end=p.clock() + timedelta(days=2)),
                ),
                spec=SimpleNamespace(
                    execution=SimpleNamespace(
                        plan_at="18:00",
                        member="malik",
                        ev_target=0.5,
                    )
                ),
            )
            await prepare_plans(p, fixture)
            failed_again = await tools.call("get_household_plan", {})
            assert_no_identifiers(failed_again.speakable)
            assert failed_again.data.code == "PREPARATION_FAILED"
            paused = await tools.call(
                "execute_household_action",
                dict(action="pause_automation", request_id="pause"),
            )
            assert_no_identifiers(paused.speakable)
            assert paused.data.decision.decision == "execute", paused
            preview = await tools.call(
                "evaluate_permission",
                dict(action="pause_automation", request_id="preview"),
            )
            assert_no_identifiers(preview.speakable)
            assert preview.data.decision.audit_id is None
            async with connection.begin():
                assert (
                    await connection.scalar(
                        sa.select(sa.func.count())
                        .select_from(db.audit_log)
                        .where(db.audit_log.c.event_type == "DRY_RUN")
                    )
                    == 1
                )
            unknown = HouseholdTools(
                p, Principal(provider="demo", sub="foreign", surface="alexa")
            )
            with pytest.raises(ValueError):
                await unknown.call("get_household_context", {})
            evidence, _ = await verify_database(
                connection, HOME, p.audit.key.public_key()
            )
            assert evidence["status"] == "valid"

    asyncio.run(run())


@pytest.mark.parametrize(
    "outcome", ["genuine", "not_genuine", "will_call", "no_answer", "removed"]
)
def test_trust_is_private_advisory_until_explicit_start(scratch_database, outcome):
    from datetime import timedelta
    from hashlib import sha256
    from uuid import UUID, uuid4

    from hirz.graph.models import ContactChannel, TrustedContact
    from hirz.mcp.trust import advance
    from tests.unit.test_pipeline import AT

    async def run():
        async with connect(scratch_database) as connection:
            p = await setup(connection, native=True)
            clock = [p.clock()]
            p.clock = lambda: clock[0]
            # Approved initial disposable fixture only; no runtime channel mutation.
            async with p.repo.write(lambda: AT):
                fixture = TrustedContact(
                    household_id=HOME,
                    id=uuid4(),
                    display_name="Trusted relative",
                    relationship="relative",
                )
                await p.repo.put("trusted_contacts", fixture)
                contacts = (await p.snapshot(p.clock())).data["trusted_contacts"]
                contact = contacts[0]
                for kind, value in (
                    ("phone", "+13125550100"),
                    ("hirz_app", "explicit simulated fixture"),
                ):
                    await p.repo.put(
                        "contact_channels",
                        ContactChannel(
                            household_id=HOME,
                            id=uuid4(),
                            contact_id=UUID(contact["id"]),
                            kind=kind,
                            value_hash=sha256(value.encode()).hexdigest(),
                            verified_at=AT,
                            source="twin",
                        ),
                    )
            tools = HouseholdTools(p, PRINCIPAL)
            assessed = await tools.call(
                "assess_request_risk",
                dict(
                    text="Send five hundred dollars from a strange number immediately",
                    claimed_party=contact["display_name"],
                    party="person",
                    request_id="assessment",
                ),
            )
            assert_no_identifiers(assessed.speakable)
            case = assessed.data.case
            assert case.risk_band.value == "critical" and case.verification is None
            assert "number" not in assessed.speakable.model_dump_json()
            assert assessed.speakable.options
            matched = await tools.call(
                "assess_request_risk",
                dict(
                    text="Hello",
                    claimed_party=contact["display_name"],
                    party="person",
                    presented_number="312-555-0100",
                    request_id="match",
                ),
            )
            assert_no_identifiers(matched.speakable)
            assert matched.data.case.number_comparison == "matches"
            mismatch = await tools.call(
                "assess_request_risk",
                dict(
                    text="Hello",
                    claimed_party=contact["display_name"],
                    party="person",
                    presented_number="3125550199",
                    request_id="mismatch",
                ),
            )
            assert_no_identifiers(mismatch.speakable)
            assert mismatch.data.case.number_comparison == "does_not_match"
            organization = await tools.call(
                "assess_request_risk",
                dict(
                    text="Hello",
                    claimed_party="Bank",
                    party="organization",
                    presented_number="3125550100",
                    request_id="organization",
                ),
            )
            assert_no_identifiers(organization.speakable)
            assert (
                organization.data.case.number_comparison == "insufficient_information"
            )
            unavailable = await tools.call(
                "verify_trusted_identity",
                dict(
                    operation="start",
                    case_id=organization.data.case.case_id,
                    request_id="org-start",
                ),
            )
            assert_no_identifiers(unavailable.speakable)
            assert unavailable.data.status == "unavailable"
            started = await tools.call(
                "verify_trusted_identity",
                dict(operation="start", case_id=case.case_id, request_id="start"),
            )
            assert_no_identifiers(started.speakable)
            assert started.data.case.verification.status == "pending", started
            assert started.data.source == "twin"
            second = await tools.call(
                "verify_trusted_identity",
                dict(
                    operation="start",
                    case_id=matched.data.case.case_id,
                    request_id="second",
                ),
            )
            assert_no_identifiers(second.speakable)
            assert second.data.case.verification.status == "pending"
            ambiguous = await tools.call(
                "verify_trusted_identity", dict(operation="status")
            )
            assert_no_identifiers(ambiguous.speakable)
            assert ambiguous.data.status == "clarification"
            stranger = HouseholdTools(
                p, Principal(provider="demo", sub="dad", surface="alexa")
            )
            with pytest.raises(ValueError):
                await stranger.call(
                    "verify_trusted_identity",
                    dict(operation="status", case_id=case.case_id),
                )
            history = await tools.call("get_action_audit", {})
            assert_no_identifiers(history.speakable)
            assert "five hundred" not in history.model_dump_json()
            from types import SimpleNamespace

            from hirz.twin.people import ContactScript

            script = ContactScript(
                contact_id=UUID(contact["id"]),
                requested_at=clock[0],
                deadline=clock[0] + timedelta(minutes=2),
                reply_at=None
                if outcome == "no_answer"
                else clock[0] + timedelta(seconds=10),
                reply="genuine" if outcome == "removed" else outcome,
            )
            world = SimpleNamespace(
                household=SimpleNamespace(id=HOME),
                config=SimpleNamespace(contact_scripts=(script,)),
            )
            if outcome == "removed":
                from test_companion_auth_database import enroll

                from hirz.companion import auth
                from hirz.companion import contacts as contact_management
                from tests.unit.test_companion_auth import Authenticator
                from tests.unit.test_pipeline import ident

                login = await enroll(
                    p,
                    await auth.initial_invitation(p, ident("members", "malik")),
                    Authenticator(),
                )
                async with connection.begin():
                    owner = await auth.session(connection, login["session"], p.clock())
                clock[0] += timedelta(seconds=1)
                async with p.repo.write(p.clock):
                    await contact_management.remove(
                        p, owner["principal"], UUID(contact["id"])
                    )
                async with connection.begin():
                    assert (
                        await p.repo.get(
                            "trusted_contacts", {"id": UUID(contact["id"])}
                        )
                        is None
                    )
                    assert not await connection.scalar(
                        sa.select(db.contact_channels.c.id).where(
                            db.contact_channels.c.contact_id == UUID(contact["id"])
                        )
                    )
            clock[0] += timedelta(minutes=2)
            await advance(p, world)
            status = await HouseholdTools(p, PRINCIPAL).call(
                "verify_trusted_identity",
                dict(operation="status", case_id=case.case_id),
            )
            assert_no_identifiers(status.speakable)
            assert status.data.case.verification.status == (
                "no_answer" if outcome == "removed" else outcome
            )
            if outcome == "removed":
                assert status.speakable.headline == (
                    "The contact was removed. No reply will be accepted for this check."
                )
            summary, _ = await verify_database(
                connection, HOME, p.audit.key.public_key()
            )
            assert summary["status"] == "valid"

    asyncio.run(run())


def test_exact_version_and_same_second_revision_consent(scratch_database):
    from test_refresh_database import prepared

    async def run():
        async with connect(scratch_database) as connection:
            p, world, registry, executor, service, result, runtime = await prepared(
                connection
            )
            try:
                tools = HouseholdTools(p, PRINCIPAL)
                plan = result.plan
                from jsonschema import Draft202012Validator

                from hirz.mcp.contracts import Result

                for focus in (*plan.goals, plan.actions[0], "conflicts"):
                    explained = await tools.call(
                        "explain_plan", dict(plan_id=plan.plan_id, focus=focus)
                    )
                    assert_no_identifiers(explained.speakable)
                    Draft202012Validator(Result.model_json_schema()).validate(
                        explained.model_dump(mode="json", by_alias=True)
                    )
                    assert explained.data.plan.plan_id == plan.plan_id
                wrong = await tools.call(
                    "approve_action",
                    dict(
                        plan_id=plan.plan_id,
                        version=plan.version + 1,
                        approved=True,
                        request_id="wrong",
                    ),
                )
                assert_no_identifiers(wrong.speakable)
                assert wrong.data.code == "PLAN_CHANGED"
                revision = await tools.call(
                    "revise_household_plan",
                    dict(
                        text="Keep the room at 72",
                        applies_to="Living room",
                        kind="one_time",
                        operation="add",
                        change="temperature",
                        temperature_f=72,
                        request_id="revise",
                    ),
                )
                assert_no_identifiers(revision.speakable)
                assert revision.data.status == "recorded", revision
                refused = await tools.call(
                    "approve_action",
                    dict(
                        plan_id=plan.plan_id,
                        version=plan.version,
                        approved=True,
                        request_id="consent",
                    ),
                )
                assert_no_identifiers(refused.speakable)
                assert refused.data.code == "PLAN_CHANGED"
                assert "still updating" in refused.speakable.headline
                assert not await executor.sweep()
                canceled = await tools.call(
                    "approve_action",
                    dict(
                        plan_id=plan.plan_id,
                        version=plan.version,
                        approved=False,
                        request_id="cancel-refreshing",
                    ),
                )
                assert_no_identifiers(canceled.speakable)
                assert canceled.data.decision.decision == "execute"
            finally:
                await registry.close()

    asyncio.run(run())


def test_alexa_security_approval_remains_pending_and_claim_cannot_raise_authority(
    scratch_database,
):
    from tests.unit.test_pipeline import action

    async def run():
        async with connect(scratch_database) as connection:
            p = await setup(connection, native=True)
            door = action("security.door_unlock")
            pending = await p.propose(
                door, PRINCIPAL.model_copy(update={"requester_confirmed": True})
            )
            assert pending.approval
            alexa = PRINCIPAL.model_copy(update={"surface": "alexa"})
            tools = HouseholdTools(p, alexa)
            for approved in (True, False):
                result = await tools.call(
                    "approve_action",
                    dict(
                        action_id=door.action_id,
                        approval_id=pending.approval.approval_id,
                        approved=approved,
                        request_id=str(approved),
                    ),
                )
                assert_no_identifiers(result.speakable)
                assert result.data.status == "phone_required"
            async with connection.begin():
                assert (
                    await connection.scalar(
                        sa.select(sa.func.count()).select_from(db.approval_votes)
                    )
                    == 0
                )
                assert (await p.approval(pending.approval.approval_id))[
                    "status"
                ] == "pending"
            lowered = await tools.call(
                "evaluate_permission",
                dict(
                    action="pause_automation",
                    claimed_requester="someone unknown",
                    request_id="claimed",
                ),
            )
            assert_no_identifiers(lowered.speakable)
            assert lowered.data.decision.decision == "deny"

    asyncio.run(run())
