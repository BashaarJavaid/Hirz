"""Service-free pipeline precedence, canonicalization and fact selection."""

import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy.dialects import postgresql

from hirz.constitution.boundary import BoundaryResult
from hirz.constitution.schema import Constitution, load
from hirz.graph.context import ContextSnapshot
from hirz.graph.models import ASSET_DOMAINS
from hirz.graph.seeds import demo_id, read_seed
from hirz.pipeline.audit import AuditWriter, PipelineError
from hirz.pipeline.context import extract, quiet_hours
from hirz.pipeline.hashing import action_hash, digest, ingest, timestamp
from hirz.pipeline.models import Action, Principal, Requester, SupplementalEvidence
from hirz.pipeline.service import Pipeline, PolicyBundle, estimate

AT = datetime(2026, 9, 18, 17, tzinfo=UTC)
SEED = read_seed(Path("constitutions/quinn-home.yaml"))
HOME = SEED.household_id
POLICY = load(Path("constitutions/quinn-home.yaml"))
PRINCIPAL = Principal(provider="demo", sub="malik", surface="app")


def ident(kind, name):
    return demo_id("quinn-home", kind, name)


def action(name="communication.notify_member", **updates):
    target = {"adapter": "member", "entity": str(ident("members", "mom"))}
    if name.startswith(("governance.", "finance.")) or name == "energy.optimize_cost":
        target = {"adapter": "household", "entity": str(HOME)}
    elif name.startswith(("energy.", "environment.", "security.")):
        entity = {
            "energy.hvac_adjust": "hvac.living_room",
            "environment.lights": "light.living_room",
            "security.door_unlock": "lock.front_door",
            "energy.ev_charge": "ev",
            "energy.appliance_start": "dishwasher",
        }.get(name, "home_battery")
        target = {"adapter": "twin", "entity": entity}
        if name == "energy.hvac_adjust":
            target["zone"] = str(ident("assets", "hvac.living_room"))
    a = Action.model_validate(
        dict(
            action_id="act_" + uuid4().hex,
            **{"class": name},
            target=target,
            params={"open_minutes": 10, "target_f": 72, "ev_soc_floor": 0.3},
            requested_by={"member_id": "forged", "role": "owner", "surface": "alexa"},
            reason="Synthetic internal pipeline test",
            content_hash="",
        )
        | updates
    )
    return a.model_copy(update={"content_hash": action_hash(a)})


def snapshot():
    data = {
        k: [r.model_dump(mode="json", exclude_none=True) for r in rows]
        for k, rows in SEED.models(AT).items()
        if k != "member_accounts"
    }
    data["observations"] = []
    for name in ("assets", "members"):
        for row in data[name]:
            data["observations"].append(
                dict(
                    id=str(uuid4()),
                    household_id=str(HOME),
                    **{"asset_id" if name == "assets" else "member_id": row["id"]},
                    observed_at=AT.isoformat(),
                    source="twin",
                    domain="presence"
                    if name == "members"
                    else ASSET_DOMAINS[row["kind"]],
                    state={"available": True}
                    | (
                        {
                            "present": True,
                            "sleeping": False,
                            "zone_id": str(ident("assets", "hvac.living_room")),
                        }
                        if name == "members"
                        else {}
                    ),
                )
            )
    data["preferences"].append(
        dict(
            id=str(uuid4()),
            household_id=str(HOME),
            member_id=str(ident("members", "malik")),
            scope="member",
            key="temperature_target_f",
            value=72,
            source="declared",
            confidence=1,
        )
    )
    return ContextSnapshot(
        household_id=HOME,
        scope="all",
        as_of=AT,
        read_at=AT,
        stale=False,
        staleness_seconds=0,
        policy_status="unvalidated",
        data=data,
    )


def evidence(**changes):
    return SupplementalEvidence.model_validate(
        dict(household_id=HOME, observed_at=AT, source="twin", scam_pattern=False)
        | changes
    )


def policy_edit(name, **changes):
    data = POLICY.model_dump()
    domain, key = name.split(".")
    data["autonomy"][domain][key].update(changes)
    return Constitution.model_validate(data)


async def pipeline(
    policy=POLICY, snap=None, principal=PRINCIPAL, role="owner", used=Decimal(0)
):
    boundary = AsyncMock()
    boundary.authorize.return_value = BoundaryResult(True)
    bundle = await PolicyBundle.validate(HOME, policy, boundary)
    p = Pipeline(
        AsyncMock(),
        bundle,
        boundary,
        AuditWriter(ec.generate_private_key(ec.SECP256R1())),
        lambda: AT,
    )
    p.snapshot = AsyncMock(return_value=snap or snapshot())
    p.requester = AsyncMock(
        return_value=Requester(
            member_id=str(ident("members", principal.sub)),
            role=role,
            surface=principal.surface,
        )
    )
    p.usage = AsyncMock(return_value=used)
    return p


def test_plan_authority_denial_explains_the_rejected_authority():
    async def run():
        p = await pipeline()
        p.plan_authority = AsyncMock(side_effect=ValueError("private internal detail"))
        ev = await p.assess(
            action("energy.hvac_adjust", plan_id="plan_test"),
            PRINCIPAL,
            None,
            (),
            AT,
        )
        assert ev.decision.decision == "deny"
        assert ev.decision.explain.rejected == (
            "Plan execution lacks current approver authority",
        )
        assert ev.decision.risk is None
        p.boundary.authorize.assert_not_awaited()

    asyncio.run(run())


def test_usage_nets_reservation_and_negative_adjustment_on_same_date():
    async def run():
        p = await pipeline()
        p.connection.scalar.side_effect = [Decimal("0.30"), Decimal("-0.10")]
        used = await Pipeline.usage(p, "energy.optimize_cost", "2026-10-13")
        assert isinstance(used, Decimal) and used == Decimal("0.20")
        assert p.connection.scalar.await_count == 2
        for call in p.connection.scalar.await_args_list:
            query = call.args[0].compile(dialect=postgresql.dialect())
            assert {HOME, "energy.optimize_cost", "2026-10-13"} <= set(
                query.params.values()
            )
            assert "sum(CAST(" in str(query) and " AS NUMERIC)" in str(query)
        grant, adjustment = p.connection.scalar.await_args_list
        assert "JOIN actions" in str(grant.args[0])
        assert "RESERVATION_ADJUSTED" in adjustment.args[0].compile().params.values()

    asyncio.run(run())


def test_connection_failure_logs_household_without_params(caplog):
    async def run():
        p = await pipeline()
        sentinel = "private-action-param-sentinel"
        a = action(params={"message": sentinel})
        p.connection.in_transaction = Mock(return_value=False)
        p.connection.begin = Mock(side_effect=RuntimeError(sentinel))
        with pytest.raises(PipelineError, match="Pipeline evaluation failed"):
            await p.evaluate(a, PRINCIPAL)
        record = caplog.records[-1]
        assert record.name == "hirz.pipeline.service"
        assert record.getMessage() == (
            f"Pipeline.evaluate household={HOME} error=RuntimeError"
        )
        assert sentinel not in caplog.text
        assert sentinel not in repr(record.__dict__)

    asyncio.run(run())


def test_canonical_vectors_and_safe_validation():
    a = action(params={"z": [1, {"b": 2, "a": 1}], "a": 1.0}, scheduled_for=AT)
    b = a.model_copy(
        update={
            "params": {"a": 1, "z": [1, {"a": 1, "b": 2}]},
            "scheduled_for": datetime.fromisoformat("2026-09-18T12:00:00-05:00"),
        }
    )
    assert action_hash(a) == action_hash(b)
    assert timestamp(AT) == "2026-09-18T17:00:00.000000Z"
    assert digest({"amount": Decimal("0.10")}) != digest({"amount": 0.1})
    assert ingest(a) == a
    for value in (float("nan"), float("inf"), 2**60):
        with pytest.raises(ValueError, match="Invalid"):
            action(params={"v": value})
    with pytest.raises(ValueError, match="hash"):
        ingest(a.model_copy(update={"params": {"x": 1}}))
    for cost in (Decimal("NaN"), Decimal("-1"), 0.1):
        with pytest.raises(ValueError):
            estimate(cost)
    assert estimate(Decimal("1E+2")) == "100"


@pytest.mark.parametrize(
    "name,edit,cost,extras,expected",
    [
        ("finance.transfer_money", {}, None, {}, "DENY_CONSTITUTION"),
        (
            "finance.transfer_money",
            {"mode": "ask"},
            None,
            {"scam_pattern": False},
            "DENY_RISK",
        ),
        ("finance.verify_request", {}, None, {"scam_pattern": True}, "VERIFY"),
        (
            "finance.verify_request",
            {"overrides": [{"when": 'risk.band == "critical"', "mode": "never"}]},
            None,
            {"scam_pattern": True},
            "DENY_CONSTITUTION",
        ),
        ("communication.notify_member", {}, None, {}, "EXECUTE"),
        ("communication.notify_member", {"mode": "ask"}, None, {}, "ASK_CONSTITUTION"),
        (
            "communication.notify_member",
            {"conditions": ['context.price_band == "low"']},
            None,
            {},
            "ASK_UNRESOLVED_CONDITION",
        ),
        (
            "communication.notify_member",
            {"conditions": ["context.hour == 0"]},
            None,
            {},
            "ASK_CONSTITUTION",
        ),
        ("energy.optimize_cost", {}, None, {}, "DENY_BUDGET"),
        ("energy.optimize_cost", {}, Decimal("10"), {}, "ASK_BUDGET"),
        ("energy.optimize_cost", {}, Decimal("10.01"), {}, "DENY_BUDGET"),
        ("energy.optimize_cost", {}, Decimal("9.99"), {}, "EXECUTE"),
        (
            "security.door_unlock",
            {},
            None,
            {"guest_present": False},
            "ASK_CONSTITUTION",
        ),
        ("security.door_unlock", {}, None, {"guest_present": True}, "DENY_RISK"),
        ("energy.hvac_adjust", {}, None, {}, "EXECUTE"),
        ("energy.hvac_adjust", {}, None, {"missing_presence": True}, "DENY_RISK"),
    ],
)
def test_precedence(name, edit, cost, extras, expected):
    async def run():
        snap = snapshot()
        if extras.get("guest_present"):
            snap.data["members"][1]["role"] = "guest"
        if extras.get("missing_presence"):
            snap.data["observations"] = [
                r for r in snap.data["observations"] if not r.get("member_id")
            ]
        p = await pipeline(policy_edit(name, **edit) if edit else POLICY, snap=snap)
        ev = await p.assess(
            action(name),
            PRINCIPAL.model_copy(update={"requester_confirmed": True}),
            cost,
            (evidence(scam_pattern=extras["scam_pattern"]),)
            if "scam_pattern" in extras
            else (),
            AT,
        )
        assert ev.decision.event_type == expected
        if expected == "EXECUTE":
            ev = await p.boundary_check(ev, AT)
            assert ev.decision.boundary.roles == {"owner": True}
            assert ev.decision.boundary.context_hash.startswith("sha256:")
        if name == "finance.transfer_money" and not edit:
            assert ev.decision.risk is None
            p.snapshot.assert_not_called()
        if expected == "ASK_UNRESOLVED_CONDITION":
            assert ev.diagnostics == ("context.price_band",)

    asyncio.run(run())


@pytest.mark.parametrize(
    "role", ["owner", "adult", "caregiver", "teen", "child", "guest", "unknown"]
)
@pytest.mark.parametrize("surface", ["app", "alexa", "scheduler"])
def test_resume_requires_adult_lineage_in_app(role, surface):
    async def run():
        principal = PRINCIPAL.model_copy(update={"surface": surface})
        p = await pipeline(principal=principal, role=role)
        result = await p.assess(
            action("governance.resume_automation"), principal, None, (), AT
        )
        expected = (
            "EXECUTE"
            if role in {"owner", "adult", "caregiver"} and surface == "app"
            else "DENY_CONSTITUTION"
        )
        assert result.decision.event_type == expected

    asyncio.run(run())


def test_identity_confirmation_pause_and_boundary():
    async def run():
        a = action()
        claimed = PRINCIPAL.model_copy(update={"claimed_role": "child"})
        p = await pipeline()
        assert (
            await p.assess(a, claimed, None, (), AT)
        ).decision.event_type == "DENY_CONSTITUTION"
        p = await pipeline(role="unknown")
        assert (
            await p.assess(a, PRINCIPAL, None, (), AT)
        ).decision.event_type == "DENY_CONSTITUTION"
        data = POLICY.model_dump()
        data["verification"]["require_requester_confirmation"] = (a.action_class,)
        p = await pipeline(Constitution.model_validate(data))
        assert (
            await p.assess(a, PRINCIPAL, None, (), AT)
        ).decision.event_type == "ASK_REQUESTER_CONFIRMATION"
        assert (
            await p.assess(
                a,
                PRINCIPAL.model_copy(update={"requester_confirmed": True}),
                None,
                (),
                AT,
            )
        ).decision.event_type == "EXECUTE"
        snap = snapshot()
        snap.data["households"][0]["autonomy_paused"] = True
        p = await pipeline(snap=snap)
        assert (
            await p.assess(a, PRINCIPAL, None, (), AT)
        ).decision.event_type == "ASK_CONSTITUTION"
        assert (
            await p.assess(
                action("governance.pause_automation"), PRINCIPAL, None, (), AT
            )
        ).decision.event_type == "EXECUTE"
        alexa = PRINCIPAL.model_copy(update={"surface": "alexa"})
        p = await pipeline(principal=alexa)
        assert (
            await p.assess(action("governance.resume_automation"), alexa, None, (), AT)
        ).decision.event_type == "DENY_CONSTITUTION"
        p = await pipeline()
        ev = await p.assess(
            a, PRINCIPAL.model_copy(update={"claimed_role": "adult"}), None, (), AT
        )
        p.boundary.authorize.side_effect = [BoundaryResult(True), BoundaryResult(False)]
        assert (await p.boundary_check(ev, AT)).decision.event_type == "DENY_BOUNDARY"
        assert ev.decision.boundary.roles == {"owner": True, "adult": False}
        for response in (
            None,
            {"allowed": True},
            BoundaryResult(True, engine="unknown"),
        ):
            p.boundary.authorize.side_effect = None
            p.boundary.authorize.return_value = response
            assert (
                await p.boundary_check(ev, AT)
            ).decision.event_type == "DENY_BOUNDARY"
        p.boundary.authorize.side_effect = TimeoutError()
        assert (await p.boundary_check(ev, AT)).decision.event_type == "DENY_BOUNDARY"

    asyncio.run(run())


def test_context_ambiguity_missing_stale_and_sources():
    a = action("energy.hvac_adjust").model_copy(
        update={
            "requested_by": Requester(
                member_id=str(ident("members", "malik")), role="owner", surface="app"
            )
        }
    )
    s = snapshot()
    f = extract(s, POLICY, a, (), Decimal(0))
    assert f.risk.baseline_target_f == 72 and f.risk.sleeping_in_target_zone is False
    assert all(r["source"] == "twin" for r in f.policy.values["observations"])
    s.data["preferences"].append(deepcopy(s.data["preferences"][-1]))
    assert extract(s, POLICY, a, (), Decimal(0)).risk.baseline_target_f is None
    s.data["observations"] = [
        r
        for r in s.data["observations"]
        if r.get("asset_id") != str(ident("assets", "hvac.living_room"))
    ]
    assert extract(s, POLICY, a, (), Decimal(0)).risk.observation_ages_seconds is None
    with pytest.raises(ValueError):
        extract(s, POLICY, a, (evidence(household_id=uuid4()),), Decimal(0))


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s.data["asset_bindings"].append(
            deepcopy(s.data["asset_bindings"][4])
        ),
        lambda s: s.data["observations"].append(
            dict(s.data["observations"][0], state={"available": False})
        ),
        lambda s: s.data["observations"][0].update(
            observed_at=(AT + timedelta(seconds=1)).isoformat()
        ),
    ],
)
def test_bad_context_fails_closed(change):
    s = snapshot()
    change(s)
    with pytest.raises(ValueError):
        extract(s, POLICY, action("energy.hvac_adjust"), (), Decimal(0))


def test_quiet_hours_start_day_and_half_open():
    data = POLICY.model_dump(by_alias=True)
    data["quiet_hours"] = [
        {"days": ["fri"], "from": "22:00", "to": "07:00", "affects": ["notify_member"]}
    ]
    p = Constitution.model_validate(data)
    for stamp, expected in [
        ("2026-09-18T21:59:00+00:00", False),
        ("2026-09-18T22:00:00+00:00", True),
        ("2026-09-19T06:59:00+00:00", True),
        ("2026-09-19T07:00:00+00:00", False),
        ("2026-09-19T22:00:00+00:00", False),
    ]:
        assert (
            quiet_hours(p, "communication.notify_member", datetime.fromisoformat(stamp))
            is expected
        )
    assert not quiet_hours(
        p, "environment.lights", datetime.fromisoformat("2026-09-18T22:00:00+00:00")
    )


def test_binding_strength_and_bundle_integrity():
    base = {
        "hash": "h",
        "gates": {"risk_band": 2, "risk_factors": ["state_stale"], "pause": True},
    }
    assert Pipeline.compatible(base, {"hash": "h", "gates": {}})
    assert Pipeline.compatible(base, {"hash": "h", "gates": {"risk_band": 1}})
    for changes in (
        {"risk_band": 3},
        {"risk_factors": ["guest_present"]},
        {"quiet": True},
    ):
        assert not Pipeline.compatible(base, {"hash": "h", "gates": changes})
    assert not Pipeline.compatible(base, {"hash": "other", "gates": {}})

    async def run():
        p = await pipeline()
        original = p.bundle.policy()
        assert p.bundle.policy() == original
        assert p.bundle.policy() is not original
        original = original.model_copy(update={"version": original.version + 1})
        assert p.bundle.policy().version != original.version
        for changed in (
            replace(p.bundle, policy_json=original.model_dump_json()),
            replace(p.bundle, compiled=replace(p.bundle.compiled, policy="changed")),
            replace(p.bundle, compiled=replace(p.bundle.compiled, schema="changed")),
            replace(p.bundle, fingerprint="changed"),
        ):
            with pytest.raises(PipelineError, match="changed after validation"):
                changed.policy()
        p.bundle.compiled.manifest["version"] = 100
        with pytest.raises(PipelineError):
            p.bundle.policy()

    asyncio.run(run())


def test_high_floor_quiet_hours_bounds_and_target_denials():
    async def run():
        snap = snapshot()
        for asset in snap.data["assets"]:
            if asset["kind"] == "light":
                asset["room_kind"] = "bedroom"
        for row in snap.data["observations"]:
            if row.get("member_id"):
                row["state"]["sleeping"] = True
            row["observed_at"] = (AT - timedelta(seconds=301)).isoformat()
        a = action(
            "environment.lights",
            target={
                "adapter": "twin",
                "entity": "light.living_room",
                "zone": str(ident("assets", "hvac.living_room")),
            },
        )
        p = await pipeline(snap=snap)
        ev = await p.assess(
            a,
            PRINCIPAL,
            None,
            (),
            AT,
        )
        assert ev.decision.event_type == "ASK_RISK"
        assert ev.decision.risk.band == "high"
        p = await pipeline()
        bounded = await p.assess(
            action("energy.hvac_adjust", params={"target_f": 90}),
            PRINCIPAL,
            None,
            (),
            AT,
        )
        assert (
            bounded.decision.event_type == "DENY_CONSTITUTION"
            and bounded.decision.risk is None
        )
        bad = await p.assess(
            action(target={"adapter": "member", "entity": str(uuid4())}),
            PRINCIPAL,
            None,
            (),
            AT,
        )
        assert bad.decision.event_type == "DENY_CONSTITUTION" and bad.diagnostics == (
            "context",
        )
        data = POLICY.model_dump(by_alias=True)
        data["quiet_hours"] = [
            {
                "days": ["fri"],
                "from": "00:00",
                "to": "23:59",
                "affects": ["notify_member"],
            }
        ]
        p = await pipeline(Constitution.model_validate(data))
        ev = await p.assess(action(), PRINCIPAL, None, (), AT)
        assert ev.decision.event_type == "ASK_CONSTITUTION" and ev.gates["quiet"]

    asyncio.run(run())


@pytest.mark.parametrize(
    "never,expected,second,legacy,seconds,event",
    [
        (True, True, False, False, 120, "EXECUTE"),
        (True, True, True, False, 120, "DENY_APPROVAL_MISMATCH"),
        (True, False, False, False, 120, "DENY_CONSTITUTION"),
        (False, False, False, False, 120, "EXECUTE"),
        (True, True, False, True, 120, "DENY_CONSTITUTION"),
        (False, False, False, True, 120, "EXECUTE"),
        (True, True, True, False, 1811, "DENY_APPROVAL_EXPIRED"),
    ],
)
def test_bound_doorbell_approval(never, expected, second, legacy, seconds, event):
    from tests.unit.test_adapter_facts import bell, context

    async def run():
        press = datetime.fromisoformat("2026-10-13T19:04:00-05:00")
        snap = context(press + timedelta(seconds=10))
        if not expected:
            snap.data["schedule_events"] = []
        bell(snap)["state"]["last_press_at"] = press.isoformat()
        policy = policy_edit(
            "security.door_unlock", never_for=["unexpected_visitor"] if never else []
        ).model_copy(update={"version": 8 if never else 7})
        p = await pipeline(policy, snap=snap)
        a = action("security.door_unlock")
        caller = PRINCIPAL.model_copy(update={"requester_confirmed": True})
        voter = caller.model_copy(
            update={
                "passkey_verified": True,
                "verified_action_hash": a.content_hash,
            }
        )
        # Exercise real propose/vote/redeem; only storage and native subprocess
        # are mocked here. The PostgreSQL case covers their actual contracts.
        p.connection.in_transaction = Mock(return_value=False)
        p.repo.write = Mock(return_value=AsyncMock())
        p.repo._at = AT
        p.proposal = AsyncMock(return_value=(True, None, a))
        p.pending = AsyncMock(return_value=None)
        p.record = AsyncMock(
            side_effect=lambda ev, at: ev.decision.model_copy(update={"audit_id": 1})
        )
        p.audit = AsyncMock()
        p.clock = lambda: snap.as_of
        asked = await p.propose(a, caller)
        if never and not expected:
            assert asked.event_type == event
            assert asked.approval is None
            p.connection.execute.assert_not_called()
            return
        assert asked.event_type == "ASK_CONSTITUTION"
        approval = p.connection.execute.call_args.args[0].compile().params
        assert approval["binding"]["doorbell"] == {
            "asset_id": bell(snap)["asset_id"],
            "last_press_at": press.isoformat(),
            "expected": expected,
        }
        if legacy:
            approval["binding"].pop("doorbell")
        p.approval = AsyncMock(return_value=approval)
        stored = {
            "proposal": a.model_dump(by_alias=True),
            "principal": caller.model_dump(),
            "cost": None,
        }
        rows = Mock()
        rows.mappings.return_value.one.return_value = stored
        p.connection.execute.return_value = rows
        p.connection.scalar.return_value = None

        async def eligible(approval, ev):
            approval["approved_at"] = press + timedelta(seconds=60)
            return True, voter

        p.eligible_votes = AsyncMock(side_effect=eligible)

        def advance(seconds):
            nonlocal snap
            snap = snap.model_copy(update={"as_of": press + timedelta(seconds=seconds)})
            p.snapshot.return_value = snap
            for row in snap.data["observations"]:
                row["observed_at"] = snap.as_of.isoformat()

        advance(60)
        assert (
            await p.vote(approval["approval_id"], voter, approved=True)
        ).event_type == "APPROVED"
        advance(61)
        assert (
            await p.vote(approval["approval_id"], voter, approved=True)
        ).event_type == "APPROVED"
        # Move the schedule too: classification remains the ASK-time fact.
        snap.data["schedule_events"] = []
        advance(seconds)
        if second:
            bell(snap)["state"]["last_press_at"] = (
                press + timedelta(seconds=90)
            ).isoformat()
            p.connection.execute.reset_mock()
            refused_vote = await p.vote(approval["approval_id"], voter, approved=True)
            assert refused_vote.event_type == event
            assert not any(
                getattr(call.args[0], "is_insert", False)
                for call in p.connection.execute.call_args_list
            )
        granted = await p.redeem(a, caller, approval_id=approval["approval_id"])
        assert granted.event_type == event
        assert p.pending.call_count == 1  # No new approval for the second press.
        if event == "DENY_APPROVAL_MISMATCH":
            assert granted.explain.rejected == ("a newer doorbell press",)
        if event == "EXECUTE":
            ev = p.record.call_args.args[0]
            values = ev.facts.policy.values
            assert granted.boundary.context_hash == "sha256:" + digest(values)
            inputs = p.boundary.authorize.call_args.args[1].inputs
            if legacy:
                assert "unexpected_visitor" not in values["context"]
            else:
                assert values["doorbell"] == approval["binding"]["doorbell"]
                assert values["context"]["unexpected_visitor"] is not expected
                assert inputs["f_context_unexpected_visitor"] is not expected
                assert digest(dict(values) | {"doorbell": {}}) != digest(values)
        # Read-only decide uses evaluate: it must still apply the 60-second window.
        preview = await p.evaluate(a, caller)
        assert preview.approval is None
        if never and not second:
            assert preview.event_type == "DENY_CONSTITUTION"

    asyncio.run(run())
