"""Item 9 grants, signed append, races and rollback on disposable PostgreSQL."""

import asyncio
from datetime import timedelta
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils
from test_database import connect, migrate
from test_database import scratch_database as scratch_database

from hirz import db
from hirz.constitution.boundary import BoundaryResult, Dogwood
from hirz.graph.models import Observation, Preference
from hirz.graph.repository import GraphRepository
from hirz.graph.seeds import load_seeds
from hirz.pipeline.audit import AuditWriter, PipelineError
from hirz.pipeline.hashing import action_hash, digest
from hirz.pipeline.models import Principal
from hirz.pipeline.service import Pipeline, PolicyBundle
from tests.unit.test_pipeline import (
    AT,
    HOME,
    POLICY,
    PRINCIPAL,
    SEED,
    action,
    ident,
    policy_edit,
    snapshot,
)

pytestmark = pytest.mark.integration
NOW = AT + timedelta(seconds=1)


async def setup(connection, policy=POLICY, *, native=False):
    await migrate(connection)
    await load_seeds(connection, [SEED], lambda: AT - timedelta(seconds=1))
    repo = GraphRepository(connection, HOME)
    async with repo.write(lambda: AT):
        data = snapshot().data
        for row in data["observations"]:
            await repo.put("observations", Observation.model_validate(row))
        await repo.put(
            "preferences", Preference.model_validate(data["preferences"][-1])
        )
    boundary = Dogwood() if native else AsyncMock()
    if not native:
        boundary.authorize.return_value = BoundaryResult(True)
    bundle = await PolicyBundle.validate(HOME, policy, boundary)
    writer = AuditWriter(ec.generate_private_key(ec.SECP256R1()))
    return Pipeline(connection, bundle, boundary, writer, lambda: NOW)


async def count(connection, table):
    return await connection.scalar(sa.select(sa.func.count()).select_from(table))


def test_native_approval_one_grant_and_signed_envelopes(scratch_database):
    async def run():
        async with connect(scratch_database) as connection:
            p = await setup(connection, native=True)
            a = action("security.door_unlock")
            caller = PRINCIPAL.model_copy(
                update={"requester_confirmed": True, "claimed_role": "adult"}
            )
            extra = ()
            preview = await p.evaluate(a, caller, evidence=extra)
            assert preview.event_type == "ASK_CONSTITUTION" and preview.audit_id is None
            assert await count(connection, db.actions) == 0
            assert await count(connection, db.audit_log) == 0
            await connection.rollback()
            proposed = await p.propose(a, caller, evidence=extra)
            assert proposed.approval
            repeated = await p.propose(a, caller, evidence=extra)
            assert repeated.approval == proposed.approval
            apr = proposed.approval.approval_id
            assert (
                await p.vote(apr, caller, approved=True)
            ).event_type == "DENY_APPROVAL_UNAUTHORIZED"
            for invalid in (None, "sha256:wrong"):
                rejected = caller.model_copy(
                    update={"passkey_verified": True, "verified_action_hash": invalid}
                )
                assert (
                    await p.vote(apr, rejected, approved=True)
                ).event_type == "DENY_APPROVAL_UNAUTHORIZED"
            voter = caller.model_copy(
                update={
                    "passkey_verified": True,
                    "verified_action_hash": a.content_hash,
                }
            )
            lower = voter.model_copy(update={"claimed_role": "child"})
            assert (
                await p.vote(apr, lower, approved=True)
            ).event_type == "DENY_APPROVAL_UNAUTHORIZED"
            assert (await p.vote(apr, voter, approved=True)).event_type == "APPROVED"
            assert (await p.vote(apr, voter, approved=True)).event_type == "APPROVED"
            assert await count(connection, db.approval_votes) == 1
            await connection.rollback()
            grant = await p.redeem(a, caller, evidence=extra, approval_id=apr)
            assert grant.event_type == "EXECUTE", grant
            assert (
                grant.boundary.engine == "dogwood-local"
                and grant.boundary.roles == {"owner": True, "adult": True}
            )
            replay = await p.redeem(a, caller, evidence=extra, approval_id=apr)
            assert replay.event_type == "DENY_APPROVAL_USED"
            rows = (
                (
                    await connection.execute(
                        sa.select(db.audit_log).order_by(db.audit_log.c.seq)
                    )
                )
                .mappings()
                .all()
            )
            previous = "0" * 64
            for i, row in enumerate(rows, 1):
                assert row["seq"] == i and row["prev_hash"] == previous
                envelope = {
                    k: v for k, v in row.items() if k not in {"signature", "curr_hash"}
                }
                envelope["household_id"] = str(envelope["household_id"])
                assert digest(envelope) == row["curr_hash"]
                p.audit.key.public_key().verify(
                    row["signature"],
                    bytes.fromhex(row["curr_hash"]),
                    ec.ECDSA(utils.Prehashed(hashes.SHA256())),
                )
                if "audit_id" in row["payload"]:
                    assert row["payload"]["audit_id"] == i
                previous = row["curr_hash"]
            assert (
                await connection.scalar(sa.select(db.actions.c.grant_seq))
                == grant.audit_id
            )
            assert (
                await connection.scalar(sa.select(db.approvals.c.status)) == "redeemed"
            )

    asyncio.run(run())


def test_twenty_concurrent_redemptions_and_budget_race(scratch_database):
    async def run():
        policy = policy_edit(
            "communication.notify_member", mode="ask", budget={"usd_per_day": "10"}
        )
        async with connect(scratch_database) as connection:
            p = await setup(connection, policy)
            a = action()
            proposal = await p.propose(a, PRINCIPAL, cost=Decimal("6"))
            apr = proposal.approval.approval_id
            await p.vote(apr, PRINCIPAL, approved=True)

            async def redeem():
                async with connect(scratch_database) as other:
                    q = Pipeline(other, p.bundle, p.boundary, p.audit, lambda: NOW)
                    return await q.redeem(
                        a, PRINCIPAL, cost=Decimal("6"), approval_id=apr
                    )

            decisions = await asyncio.gather(*(redeem() for _ in range(20)))
            assert sum(d.event_type == "EXECUTE" for d in decisions) == 1
            assert sum(d.event_type == "DENY_APPROVAL_USED" for d in decisions) == 19
            assert await p.usage(a.action_class, "2026-09-18") == Decimal(6)
            await connection.rollback()
            proposals = []
            for _ in range(2):
                b = action()
                d = await p.propose(b, PRINCIPAL, cost=Decimal("3"))
                await p.vote(d.approval.approval_id, PRINCIPAL, approved=True)
                proposals.append((b, d.approval.approval_id))

            async def race(b, apr):
                async with connect(scratch_database) as other:
                    q = Pipeline(other, p.bundle, p.boundary, p.audit, lambda: NOW)
                    return await q.redeem(
                        b, PRINCIPAL, cost=Decimal("3"), approval_id=apr
                    )

            outcomes = await asyncio.gather(*(race(*pair) for pair in proposals))
            assert sorted(d.event_type for d in outcomes) == ["DENY_BUDGET", "EXECUTE"]
            assert await p.usage(a.action_class, "2026-09-18") == Decimal(9)

    asyncio.run(run())


def test_bindings_policy_changes_expiry_and_boundary_retry(scratch_database):
    async def run():
        policy = policy_edit("communication.notify_member", mode="ask")
        async with connect(scratch_database) as connection:
            p = await setup(connection, policy)
            a = action(params={"nested": {"v": 1}})
            d = await p.propose(a, PRINCIPAL, cost=Decimal("1"))
            apr = d.approval.approval_id
            await p.vote(apr, PRINCIPAL, approved=True)
            for changes in (
                {"params": {"nested": {"v": 2}}},
                {"scheduled_for": NOW},
                {
                    "target": a.target.model_copy(
                        update={"zone": str(ident("assets", "hvac.living_room"))}
                    )
                },
                {"action_class": "health.routine_reminders"},
                {
                    "requested_by": a.requested_by.model_copy(
                        update={"claimed_author": "substituted"}
                    )
                },
            ):
                altered = a.model_copy(update=changes)
                altered = altered.model_copy(
                    update={"content_hash": action_hash(altered)}
                )
                assert (
                    await p.redeem(
                        altered, PRINCIPAL, cost=Decimal("1"), approval_id=apr
                    )
                ).event_type == "DENY_APPROVAL_MISMATCH"
            assert (
                await p.redeem(a, PRINCIPAL, cost=Decimal("2"), approval_id=apr)
            ).event_type == "DENY_APPROVAL_MISMATCH"
            forged = PRINCIPAL.model_copy(update={"sub": "dad"})
            assert (
                await p.redeem(a, forged, cost=Decimal("1"), approval_id=apr)
            ).event_type == "DENY_APPROVAL_MISMATCH"
            p.boundary.authorize.return_value = BoundaryResult(False)
            assert (
                await p.redeem(a, PRINCIPAL, cost=Decimal("1"), approval_id=apr)
            ).event_type == "DENY_BOUNDARY"
            assert (
                await connection.scalar(sa.select(db.approvals.c.status)) == "approved"
            )
            await connection.rollback()
            p.boundary.authorize.return_value = BoundaryResult(True)
            changed = policy.model_copy(update={"version": policy.version + 1})
            p.bundle = await PolicyBundle.validate(HOME, changed, p.boundary)
            fresh = await p.redeem(a, PRINCIPAL, cost=Decimal("1"), approval_id=apr)
            assert (
                fresh.event_type == "ASK_CONSTITUTION"
                and fresh.approval.approval_id != apr
            )
            assert fresh.approval.expires_at == d.approval.expires_at
            p.clock = lambda: fresh.approval.expires_at
            assert (
                await p.vote(fresh.approval.approval_id, PRINCIPAL, approved=True)
            ).event_type == "DENY_APPROVAL_EXPIRED"
            assert (
                await p.redeem(
                    a,
                    PRINCIPAL,
                    cost=Decimal("1"),
                    approval_id=fresh.approval.approval_id,
                )
            ).event_type == "DENY_APPROVAL_EXPIRED"

    asyncio.run(run())


def test_pause_resume_and_atomic_failures(scratch_database, monkeypatch):
    async def run():
        async with connect(scratch_database) as connection:
            p = await setup(connection)
            pause = action("governance.pause_automation")
            original = p.audit.append

            async def fail(*args, **kwargs):
                raise RuntimeError("injected signing/audit failure")

            monkeypatch.setattr(p.audit, "append", fail)
            with pytest.raises(PipelineError, match="transaction failed"):
                await p.redeem(pause, PRINCIPAL)
            assert (
                await count(connection, db.actions)
                == await count(connection, db.audit_log)
                == 0
            )
            assert not (await p.snapshot(NOW)).data["households"][0]["autonomy_paused"]
            await connection.rollback()
            monkeypatch.setattr(p.audit, "append", original)
            assert (await p.redeem(pause, PRINCIPAL)).event_type == "EXECUTE"
            assert (
                await p.propose(action(), PRINCIPAL)
            ).event_type == "ASK_CONSTITUTION"
            assert (
                await p.redeem(action("governance.pause_automation"), PRINCIPAL)
            ).event_type == "EXECUTE"
            transitions = await connection.scalar(
                sa.select(sa.func.count())
                .select_from(db.audit_log)
                .where(db.audit_log.c.event_type == "AUTONOMY_PAUSED")
            )
            assert transitions == 1
            await connection.rollback()
            p.clock = lambda: NOW + timedelta(seconds=1)
            resume = action("governance.resume_automation")
            assert (
                await p.redeem(
                    resume, PRINCIPAL.model_copy(update={"surface": "alexa"})
                )
            ).event_type == "DENY_CONSTITUTION"
            assert (
                await p.redeem(action("governance.resume_automation"), PRINCIPAL)
            ).event_type == "EXECUTE"
            # Failure at COMMIT rolls back every table and graph history/view change.
            before = await count(connection, db.audit_log)
            await connection.rollback()

            def fail_commit(conn):
                raise RuntimeError("injected commit failure")

            sa.event.listen(connection.sync_connection, "commit", fail_commit)
            p.clock = lambda: NOW + timedelta(seconds=2)
            with pytest.raises(PipelineError):
                await p.redeem(action("governance.pause_automation"), PRINCIPAL)
            sa.event.remove(connection.sync_connection, "commit", fail_commit)
            assert await count(connection, db.audit_log) == before
            assert not (await p.snapshot(p.clock())).data["households"][0][
                "autonomy_paused"
            ]

    asyncio.run(run())


def test_membership_quorum_rejection_and_security_channels(scratch_database):
    async def run():
        policy = policy_edit(
            "communication.notify_member", mode="ask", quorum="all_adults"
        )
        async with connect(scratch_database) as connection:
            p = await setup(connection, policy)
            a = action()
            d = await p.propose(a, PRINCIPAL)
            apr = d.approval.approval_id
            await p.vote(apr, PRINCIPAL, approved=True)
            assert (
                await p.redeem(a, PRINCIPAL, approval_id=apr)
            ).event_type == "DENY_APPROVAL_UNAUTHORIZED"
            for sub in ("mom", "dad"):
                await p.vote(
                    apr,
                    Principal(provider="demo", sub=sub, surface="app"),
                    approved=True,
                )
            # Revocation of an account prevents its old vote being counted.
            await connection.execute(
                db.member_accounts.delete().where(
                    db.member_accounts.c.household_id == HOME,
                    db.member_accounts.c.sub == "dad",
                )
            )
            await connection.commit()
            assert (
                await p.redeem(a, PRINCIPAL, approval_id=apr)
            ).event_type == "DENY_APPROVAL_UNAUTHORIZED"
            other = action()
            d = await p.propose(other, PRINCIPAL)
            await p.vote(d.approval.approval_id, PRINCIPAL, approved=False)
            assert (
                await p.redeem(other, PRINCIPAL, approval_id=d.approval.approval_id)
            ).event_type == "DENY_APPROVAL_UNAUTHORIZED"
            assert (
                await p.vote("apr_" + uuid4().hex, PRINCIPAL, approved=True)
            ).event_type == "DENY_APPROVAL_MISMATCH"

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["sign", "audit", "commit"])
def test_grant_consumption_and_budget_rollback(scratch_database, monkeypatch, failure):
    async def run():
        policy = policy_edit(
            "communication.notify_member", mode="ask", budget={"usd_per_day": "1"}
        )
        async with connect(scratch_database) as connection:
            p = await setup(connection, policy)
            a = action()
            d = await p.propose(a, PRINCIPAL, cost=Decimal("1"))
            apr = d.approval.approval_id
            await p.vote(apr, PRINCIPAL, approved=True)
            baseline = await count(connection, db.audit_log)
            await connection.rollback()

            class FailedSigner:
                def sign(self, *args):
                    raise RuntimeError("injected signing failure")

            def fail_audit(conn, cursor, statement, parameters, context, many):
                if statement.startswith("INSERT INTO audit_log"):
                    raise RuntimeError("injected audit write failure")

            def fail_commit(conn):
                raise RuntimeError("injected commit failure")

            if failure == "sign":
                monkeypatch.setattr(p.audit, "key", FailedSigner())
            elif failure == "audit":
                sa.event.listen(
                    connection.sync_connection, "before_cursor_execute", fail_audit
                )
            else:
                sa.event.listen(connection.sync_connection, "commit", fail_commit)
            with pytest.raises(PipelineError):
                await p.redeem(a, PRINCIPAL, cost=Decimal("1"), approval_id=apr)
            if failure == "audit":
                sa.event.remove(
                    connection.sync_connection, "before_cursor_execute", fail_audit
                )
            elif failure == "commit":
                sa.event.remove(connection.sync_connection, "commit", fail_commit)
            assert await count(connection, db.audit_log) == baseline
            assert await connection.scalar(sa.select(db.actions.c.grant_seq)) is None
            assert (
                await connection.scalar(sa.select(db.approvals.c.status)) == "approved"
            )
            assert await p.usage(a.action_class, "2026-09-18") == 0

    asyncio.run(run())


def test_budget_equality_new_gates_and_cleared_gates(scratch_database):
    async def run():
        policy = policy_edit("communication.notify_member", budget={"usd_per_day": "1"})
        async with connect(scratch_database) as connection:
            p = await setup(connection, policy)
            a = action()
            assert (
                await p.propose(a, PRINCIPAL, cost=Decimal("1"))
            ).event_type == "ASK_BUDGET"
            d = await p.propose(a, PRINCIPAL, cost=Decimal("1"))
            apr = d.approval.approval_id
            await p.vote(apr, PRINCIPAL, approved=True)
            # A newly paused household is a new approval reason.
            await p.redeem(action("governance.pause_automation"), PRINCIPAL)
            fresh = await p.redeem(a, PRINCIPAL, cost=Decimal("1"), approval_id=apr)
            assert (
                fresh.event_type == "ASK_CONSTITUTION"
                and fresh.approval.approval_id != apr
            )
            await p.vote(fresh.approval.approval_id, PRINCIPAL, approved=True)
            p.clock = lambda: NOW + timedelta(seconds=1)
            await p.redeem(action("governance.resume_automation"), PRINCIPAL)
            # Cleared pause does not require another approval; equality can be approved.
            grant = await p.redeem(
                a, PRINCIPAL, cost=Decimal("1"), approval_id=fresh.approval.approval_id
            )
            assert grant.event_type == "EXECUTE" and grant.budget.reserved == 1
            assert (
                await p.redeem(action(), PRINCIPAL, cost=Decimal("0.01"))
            ).event_type == "DENY_BUDGET"

    asyncio.run(run())


def test_cross_household_constraints_and_incompatible_audit(scratch_database):
    async def run():
        async with connect(scratch_database) as connection:
            p = await setup(
                connection, policy_edit("communication.notify_member", mode="ask")
            )
            a = action()
            d = await p.propose(a, PRINCIPAL)
            # A household-scoped approval id from elsewhere discloses no proposal.
            from pathlib import Path

            from hirz.graph.seeds import read_seed

            other = read_seed(Path("constitutions/quinn-parents.yaml"))
            await load_seeds(connection, [other], lambda: NOW)
            bundle = await PolicyBundle.validate(
                other.household_id, p.bundle.policy(), p.boundary
            )
            q = Pipeline(connection, bundle, p.boundary, p.audit, lambda: NOW)
            assert (
                await q.vote(d.approval.approval_id, PRINCIPAL, approved=True)
            ).event_type == "DENY_APPROVAL_MISMATCH"
            with pytest.raises(sa.exc.IntegrityError):
                async with connection.begin():
                    await connection.execute(
                        db.approval_votes.insert().values(
                            household_id=other.household_id,
                            approval_id=d.approval.approval_id,
                            member_id=ident("members", "malik"),
                            approved=True,
                            principal={},
                            created_at=NOW,
                        )
                    )
            original = p.audit
            p.audit = AuditWriter(ec.generate_private_key(ec.SECP256R1()))
            with pytest.raises(PipelineError, match="incompatible signing key"):
                await p.propose(action(), PRINCIPAL)
            p.audit = original
            await connection.execute(
                db.audit_pointer.update()
                .where(db.audit_pointer.c.household_id == HOME)
                .values(seq=100)
            )
            await connection.commit()
            with pytest.raises(PipelineError, match="Invalid audit pointer"):
                await p.propose(action(), PRINCIPAL)

    asyncio.run(run())


def test_deadline_after_boundary_and_native_false_condition(scratch_database):
    async def run():
        policy = policy_edit(
            "communication.notify_member", conditions=["context.hour == 0"]
        )
        async with connect(scratch_database) as connection:
            p = await setup(connection, policy, native=True)
            a = action()
            d = await p.propose(a, PRINCIPAL)
            assert d.event_type == "ASK_CONSTITUTION"
            await p.vote(d.approval.approval_id, PRINCIPAL, approved=True)
            assert (
                await p.redeem(a, PRINCIPAL, approval_id=d.approval.approval_id)
            ).event_type == "EXECUTE"
            b = action()
            d = await p.propose(b, PRINCIPAL)
            await p.vote(d.approval.approval_id, PRINCIPAL, approved=True)
            real = p.boundary.authorize

            async def delayed(*args, **kwargs):
                answer = await real(*args, **kwargs)
                p.clock = lambda: d.approval.expires_at
                return answer

            p.boundary.authorize = delayed
            assert (
                await p.redeem(b, PRINCIPAL, approval_id=d.approval.approval_id)
            ).event_type == "DENY_APPROVAL_EXPIRED"
            assert (
                await connection.scalar(
                    sa.select(db.actions.c.grant_seq).where(
                        db.actions.c.action_id == b.action_id
                    )
                )
                is None
            )

    asyncio.run(run())


def test_caregiver_quorum_empty_eligible_and_requester_demotion(scratch_database):
    from hirz.graph.models import Member, MemberAccount
    from hirz.graph.repository import row_model

    async def run():
        policy = policy_edit(
            "communication.notify_member", mode="ask", quorum="all_adults"
        )
        async with connect(scratch_database) as connection:
            p = await setup(connection, policy)
            caregiver = uuid4()
            async with p.repo.write(lambda: NOW):
                await p.repo.put(
                    "members",
                    Member(
                        household_id=HOME,
                        id=caregiver,
                        display_name="Test caregiver",
                        role="caregiver",
                    ),
                )
                await p.repo.put(
                    "member_accounts",
                    MemberAccount(
                        household_id=HOME,
                        member_id=caregiver,
                        provider="demo",
                        sub="caregiver",
                    ),
                )
            a = action()
            d = await p.propose(a, PRINCIPAL)
            for sub in ("malik", "mom", "dad"):
                await p.vote(
                    d.approval.approval_id,
                    Principal(provider="demo", sub=sub, surface="app"),
                    approved=True,
                )
            assert (
                await p.redeem(a, PRINCIPAL, approval_id=d.approval.approval_id)
            ).event_type == "DENY_APPROVAL_UNAUTHORIZED"
            await p.vote(
                d.approval.approval_id,
                Principal(provider="demo", sub="caregiver", surface="app"),
                approved=True,
            )
            assert (
                await p.redeem(a, PRINCIPAL, approval_id=d.approval.approval_id)
            ).event_type == "EXECUTE"
            # Owner quorum becomes empty after the sole owner is demoted.
            p.bundle = await PolicyBundle.validate(
                HOME,
                policy_edit("communication.notify_member", mode="ask", quorum="owner"),
                p.boundary,
            )
            mom = Principal(provider="demo", sub="mom", surface="app")
            b = action()
            pending = await p.propose(b, mom)
            await p.vote(pending.approval.approval_id, PRINCIPAL, approved=True)
            c = action()
            own = await p.propose(c, PRINCIPAL)
            await p.vote(own.approval.approval_id, PRINCIPAL, approved=True)
            p.clock = lambda: NOW + timedelta(seconds=1)
            async with p.repo.write(p.clock):
                row = await p.repo.get("members", {"id": ident("members", "malik")})
                member = row_model("members", row).model_copy(update={"role": "guest"})
                await p.repo.put("members", member, expected_version=row["valid_from"])
            assert (
                await p.redeem(b, mom, approval_id=pending.approval.approval_id)
            ).event_type == "DENY_APPROVAL_UNAUTHORIZED"
            assert (
                await p.redeem(c, PRINCIPAL, approval_id=own.approval.approval_id)
            ).event_type == "DENY_CONSTITUTION"

    asyncio.run(run())


def test_caller_transaction_is_refused_without_rolling_it_back(scratch_database):
    async def run():
        async with connect(scratch_database) as connection:
            p = await setup(connection)
            async with connection.begin():
                await connection.execute(sa.text("SELECT 1"))
                for call in (
                    p.evaluate(action(), PRINCIPAL),
                    p.propose(action(), PRINCIPAL),
                    p.vote("apr_" + uuid4().hex, PRINCIPAL, approved=True),
                ):
                    with pytest.raises(PipelineError, match="idle connection"):
                        await call
                    assert connection.in_transaction()
                assert await count(connection, db.audit_log) == 0

    asyncio.run(run())
