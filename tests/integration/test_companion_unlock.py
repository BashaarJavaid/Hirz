"""Real passkey assertion -> approved twin unlock -> durable verified relock."""

import asyncio
from datetime import timedelta

import pytest
import sqlalchemy as sa
from test_companion_auth_database import consume, enroll, start
from test_database import connect
from test_database import scratch_database as scratch_database
from test_executor_database import environment
from webauthn.helpers import base64url_to_bytes

from hirz import db
from hirz.companion import auth, policy
from hirz.constitution.schema import dump
from hirz.executor.local import policy as reload_policy
from hirz.executor.observations import ingest
from hirz.executor.service import Executor
from hirz.executor.twin import state
from hirz.mcp.contracts import ApprovalInput
from hirz.mcp.household import HouseholdTools
from hirz.pipeline.models import Action
from tests.unit.test_companion_auth import CONFIG, Authenticator
from tests.unit.test_pipeline import PRINCIPAL, ident

pytestmark = pytest.mark.integration


def test_observations_reload_policy_after_activation_race(scratch_database):
    async def run():
        async with connect(scratch_database) as c:
            p, world, registry, _ = await environment(c)
            try:
                login = await enroll(
                    p,
                    await auth.initial_invitation(p, ident("members", "malik")),
                    Authenticator(),
                )
                async with c.begin():
                    member = await auth.session(c, login["session"], p.clock())
                principal = member["principal"].model_copy(
                    update={"passkey_verified": True}
                )
                for version in (7, 8):
                    async with p.repo.write(p.clock):
                        draft = await policy.draft(
                            p, principal, dump(p.bundle.policy())
                        )
                        assert (
                            await policy.activate(
                                p,
                                principal,
                                draft["id"],
                                draft["candidate_hash"],
                                member["digest"],
                            )
                            == version
                        )
                    if version == 7:
                        p.bundle = await reload_policy(p)
                    world.clock.jump(world.clock() + timedelta(seconds=1))
                p.require_active = True
                assert p.bundle.policy().version == 7
                decision = await ingest(p, registry, PRINCIPAL)
                assert decision.decision == "execute"
                assert p.bundle.policy().version == 8
                async with c.begin():
                    events = (
                        (
                            await c.execute(
                                sa.select(db.audit_log.c.event_type)
                                .where(db.audit_log.c.household_id == p.household_id)
                                .order_by(db.audit_log.c.seq)
                            )
                        )
                        .scalars()
                        .all()
                    )
                assert "DENY_CONSTITUTION" in events
                assert events[-2:] == ["OBSERVATIONS_RECORDED", "TWIN_CHECKPOINT"]
            finally:
                await registry.close()

    asyncio.run(run())


@pytest.mark.parametrize("revoke_before_dispatch", [False, True])
@pytest.mark.parametrize("moving_clock", [False, True])
def test_phone_passkey_unlock_and_relock(
    scratch_database, revoke_before_dispatch, moving_clock
):
    async def run():
        async with connect(scratch_database) as c:
            p, world, registry, executor = await environment(c)
            try:
                key = Authenticator()
                login = await enroll(
                    p, await auth.initial_invitation(p, ident("members", "malik")), key
                )
                async with c.begin():
                    member = await auth.session(c, login["session"], p.clock())
                principal = member["principal"]
                async with p.repo.write(p.clock):
                    draft = await policy.draft(p, principal, dump(p.bundle.policy()))
                    await policy.activate(
                        p,
                        principal.model_copy(update={"passkey_verified": True}),
                        draft["id"],
                        draft["candidate_hash"],
                        member["digest"],
                    )
                p.bundle = await reload_policy(p)
                p.require_active = True
                world.clock.jump(world.clock() + timedelta(seconds=1))
                world.doorbell_event("doorbell.front_door", p.clock(), "press", None)
                await ingest(p, registry, PRINCIPAL)
                result = await HouseholdTools(
                    p, PRINCIPAL.model_copy(update={"surface": "alexa"})
                ).call(
                    "execute_household_action",
                    {
                        "action": "request_door_unlock",
                        "minutes": 1,
                        "request_id": "unlock-test",
                    },
                )
                assert result.data.decision.decision == "ask", result.model_dump_json()
                pending = result.data.decision.approval
                assert pending, result.model_dump_json()
                async with c.begin():
                    proposal = await c.scalar(
                        sa.select(db.actions.c.proposal).where(
                            db.actions.c.action_id == result.data.decision.action_id
                        )
                    )
                action = Action.model_validate(proposal)
                if not moving_clock and not revoke_before_dispatch:
                    # An unrelated policy edit replaces the approval session but
                    # preserves its original deadline and the pending action.
                    unrelated = p.bundle.policy().model_copy(deep=True)
                    unrelated.autonomy["energy"]["hvac_adjust"] = unrelated.autonomy[
                        "energy"
                    ]["hvac_adjust"].model_copy(update={"approval_ttl_minutes": 1})
                    async with p.repo.write(p.clock):
                        edited = await policy.draft(p, principal, dump(unrelated))
                        await policy.review_complete(
                            p, principal, edited["id"], member["digest"]
                        )
                        await policy.activate(
                            p,
                            principal.model_copy(update={"passkey_verified": True}),
                            edited["id"],
                            edited["candidate_hash"],
                            member["digest"],
                        )
                    p.bundle = await reload_policy(p)
                    async with c.begin():
                        old = await p.approval(pending.approval_id)
                        replacement = (
                            (
                                await c.execute(
                                    sa.select(db.approvals).where(
                                        db.approvals.c.action_id == action.action_id,
                                        db.approvals.c.status == "pending",
                                    )
                                )
                            )
                            .mappings()
                            .one()
                        )
                        assert old["status"] == "expired"
                        assert replacement["expires_at"] == old["expires_at"]
                        pending = pending.model_copy(
                            update={"approval_id": replacement["approval_id"]}
                        )
                if not revoke_before_dispatch:
                    changed = p.bundle.policy().model_copy(deep=True)
                    changed.autonomy["security"]["door_unlock"] = changed.autonomy[
                        "security"
                    ]["door_unlock"].model_copy(
                        update={"never_for": ("unexpected_visitor",)}
                    )
                    async with p.repo.write(p.clock):
                        blocked = await policy.draft(p, principal, dump(changed))
                    with pytest.raises(
                        policy.ReviewError, match="Pending approvals block"
                    ):
                        async with p.repo.write(p.clock):
                            await policy.activate(
                                p,
                                principal.model_copy(update={"passkey_verified": True}),
                                blocked["id"],
                                blocked["candidate_hash"],
                                member["digest"],
                            )
                options = await start(
                    p,
                    session=login["session"],
                    binding={
                        "operation": "approve",
                        "approval_id": pending.approval_id,
                        "action_hash": action.content_hash,
                        "approved": True,
                    },
                )
                record = await consume(p, options, login["session"])
                async with p.repo.write(p.clock):
                    await auth.assertion(
                        c,
                        CONFIG,
                        record,
                        key.response(
                            base64url_to_bytes(options["publicKey"]["challenge"])
                        ),
                        p.clock(),
                    )
                    voted = await HouseholdTools(
                        p,
                        principal.model_copy(
                            update={
                                "passkey_verified": True,
                                "verified_action_hash": action.content_hash,
                                "requester_confirmed": True,
                            }
                        ),
                    ).approve(
                        ApprovalInput(
                            action_id=action.action_id,
                            approval_id=pending.approval_id,
                            approved=True,
                            request_id="phone-test",
                        )
                    )
                    assert voted.data.decision.decision == "execute", (
                        voted.model_dump_json()
                    )
                if revoke_before_dispatch:
                    async with p.repo.write(p.clock):
                        await auth.revoke(
                            p,
                            principal.model_copy(update={"passkey_verified": True}),
                            principal.credential_id,
                            True,
                        )
                    await executor.sweep()
                    assert state(world, action)["locked"] is True
                    return
                if moving_clock:
                    world.clock.set_speed(1)
                    executor.freeze_twin_clock = False
                await executor.sweep()
                assert state(world, action)["locked"] is False
                async with c.begin():
                    end = (
                        (
                            await c.execute(
                                sa.select(db.actions).where(
                                    db.actions.c.action_id
                                    == action.action_id + ":ending"
                                )
                            )
                        )
                        .mappings()
                        .one()
                    )
                    assert end["grant_seq"] and end["execution_status"] == "scheduled"
                if moving_clock:
                    from hirz.executor.local import compose
                    from hirz.executor.twin import restore
                    from hirz.twin.scenario import LoadedScenario
                    from scripts.smoke_executor import SCENARIO

                    # A new security rule applies immediately, while the already
                    # authorized inverse must still relock across pause/restart.
                    changed = p.bundle.policy().model_copy(deep=True)
                    changed.autonomy["security"]["door_unlock"] = changed.autonomy[
                        "security"
                    ]["door_unlock"].model_copy(update={"mode": "never"})
                    async with p.repo.write(p.clock):
                        draft = await policy.draft(p, principal, dump(changed))
                        await policy.review_complete(
                            p, principal, draft["id"], member["digest"]
                        )
                        await policy.activate(
                            p,
                            principal.model_copy(update={"passkey_verified": True}),
                            draft["id"],
                            draft["candidate_hash"],
                            member["digest"],
                        )
                    p.bundle = await reload_policy(p)
                    paused = await HouseholdTools(p, principal).call(
                        "execute_household_action",
                        {"action": "pause_automation", "request_id": "pause-unlocked"},
                    )
                    assert paused.data.decision.decision == "execute"
                    restored = LoadedScenario(SCENARIO).world
                    await restore(p, restored)
                    assert state(restored, action)["locked"] is False
                    await registry.close()
                    world = restored
                    p.clock = world.clock
                    registry = await compose(
                        p, world=world, config="presence:twin,energy:twin"
                    )
                    await registry.start()
                    executor = Executor(
                        p, registry, world=world, freeze_twin_clock=False
                    )
                world.clock.jump(end["due_at"] + timedelta(seconds=1))
                await executor.sweep()
                assert state(world, action)["locked"] is True
                async with c.begin():
                    assert (
                        await c.scalar(
                            sa.select(db.actions.c.execution_status).where(
                                db.actions.c.action_id == action.action_id + ":ending"
                            )
                        )
                        == "verified"
                    )
            finally:
                await registry.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "fault",
    [
        "expired",
        "revoked",
        "changed_hash",
        "new_press",
        "quorum",
        "expires_before_dispatch",
        "recovery_before_dispatch",
    ],
)
def test_phone_approval_cannot_outlive_its_authority(scratch_database, fault):
    async def run():
        async with connect(scratch_database) as c:
            p, world, registry, executor = await environment(c)
            try:
                people = {}
                for name in ("malik", "mom", "dad"):
                    key = Authenticator()
                    login = await enroll(
                        p, await auth.initial_invitation(p, ident("members", name)), key
                    )
                    async with c.begin():
                        member = await auth.session(c, login["session"], p.clock())
                    people[name] = (key, login, member)
                _, _, owner = people["malik"]
                candidate = p.bundle.policy().model_copy(deep=True)
                if fault == "quorum":
                    candidate.autonomy["security"]["door_unlock"] = candidate.autonomy[
                        "security"
                    ]["door_unlock"].model_copy(update={"quorum": "all_adults"})
                async with p.repo.write(p.clock):
                    draft = await policy.draft(p, owner["principal"], dump(candidate))
                    await policy.review_complete(
                        p, owner["principal"], draft["id"], owner["digest"]
                    )
                    await policy.activate(
                        p,
                        owner["principal"].model_copy(
                            update={"passkey_verified": True}
                        ),
                        draft["id"],
                        draft["candidate_hash"],
                        owner["digest"],
                    )
                p.bundle = await reload_policy(p)
                p.require_active = True
                world.clock.jump(world.clock() + timedelta(seconds=1))
                world.doorbell_event("doorbell.front_door", p.clock(), "press", None)
                await ingest(p, registry, PRINCIPAL)
                requested = await HouseholdTools(
                    p, PRINCIPAL.model_copy(update={"surface": "alexa"})
                ).call(
                    "execute_household_action",
                    {
                        "action": "request_door_unlock",
                        "minutes": 1,
                        "request_id": "edge-unlock",
                    },
                )
                pending = requested.data.decision.approval
                assert pending
                async with c.begin():
                    action = Action.model_validate(
                        await c.scalar(
                            sa.select(db.actions.c.proposal).where(
                                db.actions.c.action_id
                                == requested.data.decision.action_id
                            )
                        )
                    )

                async def vote(name):
                    key, login, member = people[name]
                    options = await start(
                        p,
                        session=login["session"],
                        binding={
                            "operation": "approve",
                            "approval_id": pending.approval_id,
                            "action_hash": action.content_hash,
                            "approved": True,
                        },
                    )
                    record = await consume(p, options, login["session"])
                    async with p.repo.write(p.clock):
                        await auth.assertion(
                            c,
                            CONFIG,
                            record,
                            key.response(
                                base64url_to_bytes(options["publicKey"]["challenge"])
                            ),
                            p.clock(),
                        )
                        return await HouseholdTools(
                            p,
                            member["principal"].model_copy(
                                update={
                                    "passkey_verified": True,
                                    "verified_action_hash": "changed"
                                    if fault == "changed_hash"
                                    else action.content_hash,
                                    "requester_confirmed": True,
                                }
                            ),
                        ).approve(
                            ApprovalInput(
                                action_id=action.action_id,
                                approval_id=pending.approval_id,
                                approved=True,
                                request_id=options["id"],
                            )
                        )

                if fault == "expired":
                    async with c.begin():
                        await auth.session(
                            c,
                            people["malik"][1]["session"],
                            pending.expires_at - timedelta(minutes=1),
                        )
                    world.clock.jump(pending.expires_at)
                    await ingest(p, registry, PRINCIPAL)
                if fault == "revoked":
                    async with p.repo.write(p.clock):
                        await auth.revoke(
                            p,
                            owner["principal"].model_copy(
                                update={"passkey_verified": True}
                            ),
                            owner["principal"].credential_id,
                            True,
                        )
                    with pytest.raises(ValueError):
                        await vote("malik")
                else:
                    result = await vote("malik")
                    if fault in {"expired", "changed_hash"}:
                        assert result.data.decision.decision == "deny"
                    elif fault in {
                        "new_press",
                        "expires_before_dispatch",
                        "recovery_before_dispatch",
                    }:
                        assert result.data.decision.decision == "execute"
                        if fault == "new_press":
                            world.clock.jump(world.clock() + timedelta(seconds=1))
                            world.doorbell_event(
                                "doorbell.front_door", p.clock(), "press", None
                            )
                        elif fault == "expires_before_dispatch":
                            world.clock.jump(pending.expires_at)
                        else:
                            await enroll(
                                p, people["malik"][1]["recovery_code"], Authenticator()
                            )
                        await ingest(p, registry, PRINCIPAL)
                    else:
                        assert result.data.decision.decision != "execute"
                        assert (await vote("malik")).data.decision.decision != "execute"
                        assert (await vote("mom")).data.decision.decision != "execute"
                await executor.sweep()
                assert state(world, action)["locked"] is True
                if fault == "quorum":
                    assert (await vote("dad")).data.decision.decision == "execute"
                    await executor.sweep()
                    assert state(world, action)["locked"] is False
                    # A new assertion cannot redeem the same approval again.
                    assert (
                        await vote("dad")
                    ).data.decision.event_type == "DENY_APPROVAL_USED"
                    world.clock.jump(world.clock() + timedelta(seconds=61))
                    await executor.sweep()
                    assert state(world, action)["locked"] is True
            finally:
                await registry.close()

    asyncio.run(run())
