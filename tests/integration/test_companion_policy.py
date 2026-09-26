"""Reviewed activation, stale bundles, history and transaction failure."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from test_companion_auth_database import enroll
from test_database import connect
from test_database import scratch_database as scratch_database
from test_pipeline_database import setup

from hirz import db
from hirz.companion import auth, policy
from hirz.constitution.schema import dump
from hirz.executor.local import policy as reload_policy
from tests.unit.test_companion_auth import Authenticator
from tests.unit.test_pipeline import POLICY, action, ident

pytestmark = pytest.mark.integration


def test_running_mcp_proposal_and_policy_reload(scratch_database):
    from hirz.mcp.auth import Identity, identity_context
    from hirz.mcp.runtime import HouseholdRuntime
    from tests.unit.test_pipeline import PRINCIPAL

    async def run():
        async with connect(scratch_database) as c:
            p = await setup(c, native=True)
            login = await enroll(
                p,
                await auth.initial_invitation(p, ident("members", "malik")),
                Authenticator(),
            )
            async with c.begin():
                owner = await auth.session(c, login["session"], p.clock())
                requester = await p.requester(PRINCIPAL)
            phone = owner["principal"].model_copy(update={"passkey_verified": True})
            voice = PRINCIPAL.model_copy(update={"surface": "alexa"})
            runtime = HouseholdRuntime(c.engine, p.audit, clock=lambda: p.clock())
            token = identity_context.set(Identity(p.household_id, voice, requester))
            try:
                async with runtime.run():
                    with pytest.raises(ValueError, match="Activate the household"):
                        await runtime.call("get_household_context", {})
                    for version in (7, 8):
                        if version == 8:
                            await runtime.call(
                                "propose_household_rule",
                                {
                                    "text": "Never unlock for an unexpected visitor",
                                    "request_id": "voice-proposal",
                                },
                            )
                        async with p.repo.write(p.clock):
                            candidate = p.bundle.policy().model_copy(deep=True)
                            if version == 8:
                                proposal = (
                                    (await c.execute(sa.select(db.rule_proposals)))
                                    .mappings()
                                    .one()
                                )
                                assert proposal["surface"] == "alexa"
                                assert proposal["status"] == "queued"
                                candidate.autonomy["security"]["door_unlock"] = (
                                    candidate.autonomy["security"][
                                        "door_unlock"
                                    ].model_copy(
                                        update={"never_for": ("unexpected_visitor",)}
                                    )
                                )
                                draft = await policy.proposal_draft(
                                    p, phone, proposal["id"], dump(candidate)
                                )
                            else:
                                draft = await policy.draft(p, phone, dump(candidate))
                            await policy.review_complete(
                                p, phone, draft["id"], owner["digest"]
                            )
                        with pytest.raises(ValueError):
                            async with p.repo.write(p.clock):
                                await policy.activate(
                                    p,
                                    phone.model_copy(update={"surface": "alexa"}),
                                    draft["id"],
                                    draft["candidate_hash"],
                                    owner["digest"],
                                )
                        async with p.repo.write(p.clock):
                            assert (
                                await policy.activate(
                                    p,
                                    phone,
                                    draft["id"],
                                    draft["candidate_hash"],
                                    owner["digest"],
                                )
                                == version
                            )
                        result = await runtime.call(
                            "evaluate_permission",
                            {
                                "action": "pause_automation",
                                "request_id": f"preview-{version}",
                            },
                        )
                        assert result.data.decision.constitution.version == version
                        assert (
                            runtime.bundles[p.household_id][0].policy().version
                            == version
                        )
                        p.bundle = await reload_policy(p)
                    async with c.begin():
                        assert (
                            await c.scalar(sa.select(db.rule_proposals.c.status))
                            == "activated"
                        )
            finally:
                identity_context.reset(token)

    asyncio.run(run())


def test_initial_activation_stale_runtime_and_rollback(scratch_database):
    async def run():
        async with connect(scratch_database) as c:
            p = await setup(c, native=True)
            p.require_active = True
            key = Authenticator()
            invitation = await auth.initial_invitation(p, ident("members", "malik"))
            login = await enroll(p, invitation, key)
            async with c.begin():
                current = await auth.session(c, login["session"], p.clock())
            principal = current["principal"].model_copy(
                update={"passkey_verified": True}
            )
            before = await p.redeem(action(), principal)
            assert before.decision == "deny"
            async with p.repo.write(p.clock):
                draft = await policy.draft(p, principal, dump(POLICY))
                assert (
                    await policy.activate(
                        p,
                        principal,
                        draft["id"],
                        draft["candidate_hash"],
                        current["digest"],
                    )
                    == 7
                )
            p.bundle = await reload_policy(p)
            original = p.bundle
            new = POLICY.model_copy(deep=True)
            new.autonomy["security"]["door_unlock"] = new.autonomy["security"][
                "door_unlock"
            ].model_copy(update={"never_for": ("unexpected_visitor",)})
            at = p.clock() + timedelta(seconds=1)
            p.clock = lambda: at
            async with p.repo.write(p.clock):
                draft = await policy.draft(
                    p, principal, dump(new), "Never unlock for an unexpected visitor"
                )
                if len(draft["review"]["lines"]) > 3:
                    await policy.review_complete(
                        p, principal, draft["id"], current["digest"]
                    )
                await policy.activate(
                    p,
                    principal,
                    draft["id"],
                    draft["candidate_hash"],
                    current["digest"],
                )
            # A running caller holding the old bundle cannot grant further work.
            assert (await p.redeem(action(), principal)).decision == "deny"
            p.bundle = await reload_policy(p)
            assert p.bundle.policy().version == 8 and p.bundle != original
            with pytest.raises(ValueError):
                async with p.repo.write(p.clock):
                    await policy.activate(
                        p,
                        principal,
                        draft["id"],
                        draft["candidate_hash"],
                        current["digest"],
                    )
            at += timedelta(seconds=1)
            async with p.repo.write(p.clock):
                rollback = await policy.draft(
                    p, principal, dump(POLICY), "Restore the previous policy"
                )
                await policy.review_complete(
                    p, principal, rollback["id"], current["digest"]
                )
            writer = p.audit.append
            p.audit.append = AsyncMock(side_effect=RuntimeError("audit unavailable"))
            with pytest.raises(RuntimeError):
                async with p.repo.write(p.clock):
                    await policy.activate(
                        p,
                        principal,
                        rollback["id"],
                        rollback["candidate_hash"],
                        current["digest"],
                    )
            p.audit.append = writer
            async with c.begin():
                assert (await policy.current(p))["version"] == 8
                assert (await policy.get(p, rollback["id"]))["status"] == "ready"
            async with p.repo.write(p.clock):
                assert (
                    await policy.activate(
                        p,
                        principal,
                        rollback["id"],
                        rollback["candidate_hash"],
                        current["digest"],
                    )
                    == 9
                )
            async with c.begin():
                rows = (
                    await c.execute(
                        sa.select(
                            db.constitution_versions.c.version,
                            db.constitution_versions.c.status,
                        ).order_by(db.constitution_versions.c.version)
                    )
                ).all()
                assert rows == [(7, "superseded"), (8, "superseded"), (9, "active")]

    asyncio.run(run())


def test_complete_review_is_session_bound_and_concurrent_activation_is_stale(
    scratch_database,
):
    from hirz.pipeline.service import Pipeline

    async def run():
        async with connect(scratch_database) as c:
            p = await setup(c, native=True)
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
            async with p.repo.write(p.clock):
                initial = await policy.draft(p, principal, dump(POLICY))
                await policy.activate(
                    p,
                    principal,
                    initial["id"],
                    initial["candidate_hash"],
                    member["digest"],
                )
            p.bundle = await reload_policy(p)
            at = p.clock() + timedelta(seconds=1)
            p.clock = lambda: at
            changed = POLICY.model_copy(
                update={
                    "defaults": POLICY.defaults.model_copy(
                        update={"approval_ttl_minutes": 29}
                    )
                }
            )
            async with p.repo.write(p.clock):
                candidates = [
                    await policy.draft(p, principal, dump(changed)) for _ in range(2)
                ]
            assert all(len(d["review"]["lines"]) > 3 for d in candidates)
            with pytest.raises(policy.ReviewError, match="complete review"):
                async with p.repo.write(p.clock):
                    await policy.activate(
                        p,
                        principal,
                        candidates[0]["id"],
                        candidates[0]["candidate_hash"],
                        member["digest"],
                    )
            async with p.repo.write(p.clock):
                for d in candidates:
                    await policy.review_complete(
                        p, principal, d["id"], member["digest"]
                    )
            with pytest.raises(policy.ReviewError, match="complete review"):
                async with p.repo.write(p.clock):
                    await policy.activate(
                        p,
                        principal,
                        candidates[0]["id"],
                        candidates[0]["candidate_hash"],
                        "another-session",
                    )

            async def activate(d):
                async with connect(scratch_database) as other:
                    caller = Pipeline(other, p.bundle, p.boundary, p.audit, p.clock)
                    async with caller.repo.write(caller.clock):
                        return await policy.activate(
                            caller,
                            principal,
                            d["id"],
                            d["candidate_hash"],
                            member["digest"],
                        )

            results = await asyncio.gather(
                *(activate(d) for d in candidates), return_exceptions=True
            )
            assert results.count(8) == 1
            assert (
                sum(
                    isinstance(r, policy.ReviewError) and "Stale preview" in str(r)
                    for r in results
                )
                == 1
            )
            async with c.begin():
                assert (await policy.current(p))["version"] == 8

    asyncio.run(run())


def test_running_executor_uses_new_policy_for_queued_action(scratch_database):
    from test_executor_database import environment

    from hirz.executor.twin import state
    from scripts.smoke_executor import action as light_action
    from tests.unit.test_pipeline import PRINCIPAL

    async def run():
        async with connect(scratch_database) as c:
            p, world, registry, executor = await environment(c)
            try:
                login = await enroll(
                    p,
                    await auth.initial_invitation(p, ident("members", "malik")),
                    Authenticator(),
                )
                async with c.begin():
                    owner = await auth.session(c, login["session"], p.clock())
                principal = owner["principal"].model_copy(
                    update={"passkey_verified": True}
                )
                for version in (7, 8):
                    changed = p.bundle.policy().model_copy(deep=True)
                    if version == 8:
                        changed.autonomy["environment"]["lights"] = changed.autonomy[
                            "environment"
                        ]["lights"].model_copy(update={"mode": "never"})
                        changed.per_role["guest"]["environment.lights"] = (
                            changed.per_role["guest"]["environment.lights"].model_copy(
                                update={"mode": "never"}
                            )
                        )
                    async with p.repo.write(p.clock):
                        draft = await policy.draft(p, principal, dump(changed))
                        await policy.review_complete(
                            p, principal, draft["id"], owner["digest"]
                        )
                        await policy.activate(
                            p,
                            principal,
                            draft["id"],
                            draft["candidate_hash"],
                            owner["digest"],
                        )
                    if version == 7:
                        p.bundle = await reload_policy(p)
                        p.require_active = True
                        queued = light_action(world)
                        before = state(world, queued)
                        assert (
                            await p.enqueue(queued, PRINCIPAL)
                        ).decision == "execute"
                    world.clock.jump(world.clock() + timedelta(seconds=1))
                assert p.bundle.policy().version == 7
                executor.reload_policy = lambda: reload_policy(p)
                results = await executor.sweep()
                assert any(
                    d is not None and d.event_type == "DENY_CONSTITUTION"
                    for d in results
                )
                assert p.bundle.policy().version == 8
                assert state(world, queued) == before
                async with c.begin():
                    assert (
                        await c.scalar(
                            sa.select(db.actions.c.execution_status).where(
                                db.actions.c.action_id == queued.action_id
                            )
                        )
                        == "held"
                    )
            finally:
                await registry.close()

    asyncio.run(run())


def test_companion_upgrade_from_0005_preserves_policy_and_unmanaged_assets(
    scratch_database,
):
    from test_database import migrate, rejected

    from hirz.graph.repository import row_model
    from tests.unit.test_pipeline import HOME

    async def run():
        async with connect(scratch_database) as c:
            await migrate(c, target="0005_execution_attempt")
            # Initial schema fixture only: no runtime mutation or activation.
            async with c.begin():
                await c.execute(
                    db.households.insert().values(
                        id=HOME,
                        name="Upgrade fixture",
                        timezone="America/Chicago",
                        locale="en-US",
                        constitution_version=7,
                    )
                )
                await c.execute(
                    db.assets.insert().values(
                        household_id=HOME,
                        id=ident("assets", "light.living_room"),
                        attributes={"name": "Existing light", "kind": "light"},
                    )
                )
                await c.execute(
                    db.constitution_versions.insert().values(
                        household_id=HOME,
                        version=7,
                        yaml=dump(POLICY),
                        hash=auth.digest(dump(POLICY)),
                        status="unvalidated",
                    )
                )
            await migrate(c)
            async with c.begin():
                row = (
                    (await c.execute(sa.select(db.constitution_versions)))
                    .mappings()
                    .one()
                )
                assert row["version"] == 7 and row["yaml"] == dump(POLICY)
                assert row["status"] == "unvalidated" and row["compiled_cedar"] is None
                asset = (await c.execute(sa.select(db.assets))).mappings().one()
                assert row_model("assets", asset).managed_through_hirz is False
                for invalid in ("draft", "active", "superseded"):
                    await rejected(
                        c, db.constitution_versions.update().values(status=invalid)
                    )
                assert (
                    await c.scalar(sa.select(sa.func.count()).select_from(db.audit_log))
                    == 0
                )

    asyncio.run(run())
