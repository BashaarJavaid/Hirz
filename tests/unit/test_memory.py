"""Memory validation, advisory isolation and graph-only comfort selection."""

import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest

from hirz.graph.models import Observation, ObservationState
from hirz.memory.models import Candidate, Page, References, Session, Turn, TurnInput
from hirz.memory.provider import Hint, InProcessMemory
from hirz.planner.coordinator import Clarification, coordinate
from hirz.planner.preferences import windows
from hirz.twin.physics import changed
from tests.unit.test_coordinator import AT, END, add, requirement, snapshot, workload
from tests.unit.test_pipeline import HOME, POLICY, ident


@pytest.mark.parametrize("value", [True, "72", float("nan"), float("inf"), {}, None])
def test_candidate_rejects_invalid_temperature(value):
    with pytest.raises(ValueError):
        Candidate(value=value, confidence=1)


@pytest.mark.parametrize("confidence", [-1, 1.1, float("nan")])
def test_confidence_bounds(confidence):
    with pytest.raises(ValueError):
        Candidate(value=72, confidence=confidence)


def test_input_bounds_and_extra_candidates():
    for kwargs in ({"key": "lights"}, {"member_id": uuid4()}, {"scope": "household"}):
        with pytest.raises(ValueError):
            Candidate(value=72, confidence=1, **kwargs)
    for session_id, text in (
        ("", "x"),
        ("s" * 257, "x"),
        ("ok", ""),
        ("ok", "x" * 8001),
    ):
        with pytest.raises(ValueError):
            TurnInput(session_id=session_id, role="user", text=text)
    TurnInput(session_id="s" * 256, role="assistant", text="x" * 8000)
    for kwargs in ({"limit": 0}, {"limit": 101}, {"after": -1}, {"limit": True}):
        with pytest.raises(ValueError):
            Page(**kwargs)
    with pytest.raises(ValueError):
        References(plan=["one", "two"])


def test_provider_isolation_ordering_and_idempotence():
    async def run():
        session = Session(
            household_id=HOME,
            member_id=ident("members", "malik"),
            surface="app",
            session_id="shared",
        )
        other = changed(session, member_id=ident("members", "dad"))
        hint = Hint(session=session, text="Unaccepted hint")
        provider = InProcessMemory((hint, Hint(session=other, text="Other member")))
        turn = Turn(
            id=uuid4(),
            session=session,
            session_id=session.session_id,
            sequence=1,
            role="user",
            text="hello",
            recorded_at=AT,
            decision_seq=1,
        )
        await provider.append(changed(turn, id=uuid4(), sequence=2))
        await provider.append(turn)
        await provider.append(turn)
        assert [t.sequence for t in await provider.turns(session)] == [1, 2]
        assert len(await provider.turns(session, Page(after=1, limit=1))) == 1
        with pytest.raises(ValueError, match="mismatch"):
            await provider.append(changed(turn, text="changed"))
        assert await provider.hints(session) == (hint,)
        for foreign in (
            other,
            changed(session, household_id=uuid4()),
            changed(session, surface="alexa"),
            changed(session, session_id="other"),
        ):
            assert await provider.turns(foreign) == ()

    asyncio.run(run())


def preference_snapshot(*, value=72, who="malik", presence=True):
    snap = snapshot()
    member = ident("members", who)
    row = dict(
        id=str(uuid4()),
        household_id=str(HOME),
        member_id=str(member),
        scope="member",
        key="temperature_target_f",
        value=value,
        source="learned_accepted",
        confidence=1,
        valid_from=(AT - timedelta(seconds=1)).isoformat(),
    )
    obs = Observation(
        id=uuid4(),
        household_id=HOME,
        member_id=member,
        domain="presence",
        source="twin",
        observed_at=AT,
        state=ObservationState(
            present=True, zone_id=ident("assets", "hvac.living_room")
        ),
    )
    return changed(
        snap,
        data=snap.data
        | {
            "preferences": [row],
            "observations": [obs.model_dump(mode="json")] if presence else [],
            "schedule_events": [],
        },
    )


def test_graph_preference_freshness_provenance_explicit_precedence_and_bounds():
    snap = preference_snapshot()
    p = workload()
    output = coordinate(p, snap, POLICY)
    assert output.result.plan and not output.conflicts
    assert output.inputs.slots[0].end == AT + timedelta(seconds=300)
    assert output.inputs.zones[0].preferences[0] == 72
    assert all(t is None for t in output.inputs.zones[0].preferences[1:])
    assert set(output.inputs.zones[0].lower) == {66}
    assert set(output.inputs.zones[0].upper) == {76}
    evidence = output.result.plan.constraints[0]
    assert evidence.member_id == ident("members", "malik")
    assert evidence.encoded["preference_id"] == snap.data["preferences"][0]["id"]
    assert "preference_version" in evidence.encoded
    request = requirement("prefer living room at 71 F", end=AT + timedelta(minutes=2))
    overrides = coordinate(p, add(snap, request), POLICY)
    assert overrides.inputs.zones[0].preferences[:2] == (71, 72)
    band = requirement("keep living room between 69 and 71 F")
    assert not windows(p, add(snap, band), (band,))
    assert (
        coordinate(p, preference_snapshot(presence=False), POLICY)
        .inputs.zones[0]
        .preferences
        == (None,) * 8
    )


def arrival(member, zone, start, end):
    return dict(
        id=str(uuid4()),
        household_id=str(HOME),
        schedule_id=str(uuid4()),
        member_id=str(member),
        zone_id=str(zone),
        kind="arrival",
        starts_at=AT.isoformat(),
        expected_at=start.isoformat(),
        ends_at=end.isoformat(),
    )


def test_arrival_windows_presence_suppression_and_ambiguity():
    p, snap = workload(), preference_snapshot(presence=False)
    member = ident("members", "malik")
    room = ident("assets", "hvac.living_room")
    guest = ident("assets", "hvac.guest_room")
    event = arrival(member, room, AT + timedelta(minutes=1), AT + timedelta(minutes=10))
    snap = changed(snap, data=snap.data | {"schedule_events": [event]})
    result = coordinate(p, snap, POLICY)
    assert result.inputs.zones[0].preferences[:3] == (None, 72, None)
    assert result.inputs.slots[1].start == AT + timedelta(minutes=1)
    elsewhere = preference_snapshot().data["observations"][0]
    elsewhere["state"]["zone_id"] = str(guest)
    blocked = changed(snap, data=snap.data | {"observations": [elsewhere]})
    rows = windows(p, blocked, ())
    assert rows[0].spec.starts_at == AT + timedelta(seconds=300)
    assert rows[0].spec.ends_at == AT + timedelta(minutes=10)
    contradictory = preference_snapshot().data["observations"][0]
    with pytest.raises(Clarification, match="presence"):
        windows(
            p,
            changed(
                blocked,
                data=blocked.data | {"observations": [elsewhere, contradictory]},
            ),
            (),
        )
    with pytest.raises(Clarification, match="rooms"):
        windows(
            p,
            changed(
                snap,
                data=snap.data
                | {"schedule_events": [event, arrival(member, guest, AT, END)]},
            ),
            (),
        )
    with pytest.raises(Clarification, match="Multiple"):
        windows(
            p,
            changed(
                snap, data=snap.data | {"preferences": snap.data["preferences"] * 2}
            ),
            (),
        )


def test_conflicting_graph_preferences_and_manual_hold_survives():
    snap = preference_snapshot()
    dad = preference_snapshot(value=73, who="dad")
    both = changed(
        snap,
        data=snap.data
        | {
            "preferences": snap.data["preferences"] + dad.data["preferences"],
            "observations": snap.data["observations"] + dad.data["observations"],
        },
    )
    result = coordinate(workload(), both, POLICY)
    assert result.conflicts and len(result.conflicts[0].members) == 2
    hold = requirement(
        "prefer living room at 70 F",
        kind="manual_hold",
        mode="off",
        ends_at=AT + timedelta(hours=2),
    )
    held = coordinate(workload(), add(snap, hold), POLICY)
    assert held.inputs.zones[0].held_targets == (70,) * len(held.inputs.slots)
    assert not held.result.actions


def test_memory_command_validation_consent_and_terminal_state(monkeypatch):
    from unittest.mock import AsyncMock

    from hirz.memory import service as memory
    from hirz.memory.models import Proposal
    from hirz.pipeline.hashing import digest
    from hirz.pipeline.service import PolicyBundle
    from tests.unit.test_pipeline import PRINCIPAL, action, pipeline

    async def run():
        p = await pipeline()
        candidate = Candidate(value=74, confidence=1)
        source = uuid4()
        command = memory.Command(
            operation="propose",
            content_hash=digest(
                {
                    "source_turn": str(source),
                    "candidate": candidate.model_dump(mode="json"),
                }
            ),
            source_turn=source,
            candidate=candidate,
        )
        monkeypatch.setattr(memory, "scoped_row", AsyncMock(return_value={}))
        monkeypatch.setattr(memory, "preference", AsyncMock(return_value=None))

        def make(cmd):
            return action("governance.memory", params=cmd.model_dump(mode="json"))

        assert await memory.prepare(p, make(command), PRINCIPAL) == command
        for bad in (
            changed(command, content_hash="0" * 64),
            changed(command, source_turn=None),
            changed(command, proposal_id=uuid4()),
        ):
            with pytest.raises(ValueError):
                await memory.prepare(p, make(bad), PRINCIPAL)
        turn = TurnInput(session_id="x", role="user", text="private")
        append = memory.Command(
            operation="append_turn", content_hash=digest(turn.model_dump(mode="json"))
        )
        with pytest.raises(ValueError, match="Private"):
            await memory.prepare(p, make(append), PRINCIPAL)
        p._memory_turn = turn
        assert await memory.prepare(p, make(append), PRINCIPAL) == append
        with pytest.raises(ValueError, match="Unexpected"):
            await memory.prepare(
                p, make(changed(append, candidate=candidate)), PRINCIPAL
            )
        for principal in (changed(PRINCIPAL, surface="scheduler"),):
            with pytest.raises(Clarification):
                await memory.prepare(p, make(append), principal)
        with pytest.raises(Clarification):
            await memory.prepare(p, changed(make(append), scheduled_for=AT), PRINCIPAL)
        proposal = Proposal(
            id=uuid4(),
            household_id=HOME,
            member_id=ident("members", "malik"),
            source_turn=source,
            candidate=candidate,
            preference_id=None,
            preference_version=None,
            created_at=AT,
            decision_seq=1,
            audit_seq=2,
        )
        memory.scoped_row.return_value = proposal.model_dump()
        review = memory.Command(
            operation="accept",
            proposal_id=proposal.id,
            content_hash=digest(
                {"proposal_id": str(proposal.id), "operation": "accept"}
            ),
        )
        assert await memory.prepare(p, make(review), PRINCIPAL) == review
        for bad in (
            changed(review, content_hash="0" * 64),
            changed(review, candidate=candidate),
            changed(review, proposal_id=None),
        ):
            with pytest.raises(ValueError):
                await memory.prepare(p, make(bad), PRINCIPAL)
        with pytest.raises(ValueError, match="app"):
            await memory.prepare(p, make(review), changed(PRINCIPAL, surface="alexa"))
        memory.scoped_row.return_value = changed(
            proposal, status="accepted"
        ).model_dump()
        with pytest.raises(ValueError, match="already"):
            await memory.prepare(p, make(review), PRINCIPAL)
        memory.scoped_row.return_value = proposal.model_dump()
        memory.preference.return_value = {"id": uuid4(), "valid_from": AT}
        with pytest.raises(ValueError, match="changed"):
            await memory.prepare(p, make(review), PRINCIPAL)
        data = POLICY.model_dump()
        data["learning"]["accept_memory_proposals"] = "never"
        p.bundle = await PolicyBundle.validate(
            HOME, type(POLICY).model_validate(data), p.boundary
        )
        for cmd in (command, review):
            with pytest.raises(ValueError, match="disabled"):
                await memory.prepare(p, make(cmd), PRINCIPAL)
        reject = changed(
            review,
            operation="reject",
            content_hash=digest(
                {"proposal_id": str(proposal.id), "operation": "reject"}
            ),
        )
        assert await memory.prepare(p, make(reject), PRINCIPAL) == reject
        assert await memory.prepare(p, make(append), PRINCIPAL) == append

    asyncio.run(run())


def test_memory_service_fallback_and_authority_free_references(monkeypatch):
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, Mock

    from hirz.memory import service as memory
    from hirz.memory.models import Proposal
    from hirz.pipeline.models import ConstitutionEvidence, Decision, EventType
    from tests.unit.test_pipeline import PRINCIPAL, pipeline

    @asynccontextmanager
    async def transaction():
        yield

    async def run():
        p = await pipeline()
        p.connection.begin = transaction
        p.redeem = AsyncMock(
            return_value=Decision(
                decision="execute",
                event_type=EventType.EXECUTE,
                action_id="x",
                constitution=ConstitutionEvidence(
                    version=1,
                    rule="governance.memory",
                    mode="auto",
                    conditions_met=True,
                ),
                audit_id=1,
            )
        )
        provider = AsyncMock()
        provider.append.side_effect = RuntimeError("unavailable")
        service = memory.MemoryService(p, provider)
        turn = TurnInput(session_id="one", role="assistant", text="private")
        session = await service.session(PRINCIPAL, "one")
        row = dict(
            household_id=HOME,
            member_id=session.member_id,
            surface="app",
            id=uuid4(),
            sequence=1,
            recorded_at=AT,
            decision_seq=1,
            **turn.model_dump(),
        )
        monkeypatch.setattr(memory, "scoped_row", AsyncMock(return_value=row))
        result = await service.record_turn(PRINCIPAL, action_id="x", turn=turn)
        assert result.record.text == "private" and p._memory_turn is None
        assert "private" not in str(p.redeem.call_args)
        p._memory_turn = turn
        with pytest.raises(ValueError, match="Overlapping"):
            await service.record_turn(PRINCIPAL, action_id="y", turn=turn)
        p._memory_turn = None
        provider.hints.side_effect = RuntimeError("unavailable")
        assert await service.hints(PRINCIPAL, "one") == ()
        provider.hints.side_effect = None
        provider.hints.return_value = (
            Hint(session=session, text="mine"),
            Hint(session=changed(session, member_id=uuid4()), text="private-other"),
        )
        assert [h.text for h in await service.hints(PRINCIPAL, "one")] == ["mine"]
        mappings = Mock()
        mappings.mappings.return_value = [row]
        p.connection.execute.return_value = mappings
        assert (await service.turns(PRINCIPAL, "one"))[0] == result.record
        proposal = Proposal(
            id=uuid4(),
            household_id=HOME,
            member_id=session.member_id,
            source_turn=row["id"],
            candidate=Candidate(value=74, confidence=1),
            preference_id=None,
            preference_version=None,
            created_at=AT,
            decision_seq=1,
            audit_seq=2,
        )
        memory.scoped_row.return_value = proposal.model_dump()
        assert (
            await service.propose(
                PRINCIPAL,
                action_id="propose",
                source_turn=row["id"],
                candidate=proposal.candidate,
            )
        ).record == proposal
        assert (
            await service.review(
                PRINCIPAL, action_id="accept", proposal_id=proposal.id, accept=True
            )
        ).record == proposal
        with pytest.raises(ValueError):
            await service.review(
                PRINCIPAL, action_id="x", proposal_id=proposal.id, accept="yes"
            )
        mappings.mappings.return_value = [proposal.model_dump()]
        assert await service.proposals(PRINCIPAL, pending_only=False) == (proposal,)
        assert await service.proposals(PRINCIPAL) == (proposal,)
        p.redeem.return_value = changed(p.redeem.return_value, decision="deny")
        assert (
            await service.review(
                PRINCIPAL, action_id="reject", proposal_id=proposal.id, accept=False
            )
        ).record is None
        p.connection.scalar.return_value = None
        with pytest.raises(Clarification, match="identify"):
            await service.resolve(PRINCIPAL, "one", "plan")
        with pytest.raises(Clarification, match="Unknown"):
            await service.resolve(PRINCIPAL, "one", "invented")
        p.connection.scalar.return_value = "case"
        with pytest.raises(Clarification, match="not available"):
            await service.resolve(PRINCIPAL, "one", "verification_case")
        with pytest.raises(Clarification, match="Unknown"):
            await memory.reference(p, "invented", "x")
        mappings.mappings.return_value = mappings
        mappings.one_or_none.return_value = None
        with pytest.raises(Clarification, match="unavailable"):
            await memory.reference(p, "plan", "missing")
        mappings.one_or_none.return_value = {"document": {"status": "superseded"}}
        with pytest.raises(Clarification, match="current"):
            await service.resolve(PRINCIPAL, "one", "plan")
        mappings.one_or_none.return_value = {
            "document": {
                "status": "proposed",
                "horizon": {"end": (p.clock() - timedelta(seconds=1)).isoformat()},
            }
        }
        with pytest.raises(Clarification, match="ended"):
            await memory.reference(p, "plan", "ended")
        mappings.one_or_none.return_value["document"]["horizon"]["end"] = (
            END.isoformat()
        )
        assert await memory.reference(p, "plan", "live") == "live"
        mappings.one_or_none.return_value = {"execution_status": "cancelled"}
        with pytest.raises(Clarification, match="current"):
            await memory.reference(p, "action", "old")
        mappings.one_or_none.return_value = {"execution_status": "queued"}
        assert await service.resolve(PRINCIPAL, "one", "action") == "case"
        p.requester.return_value = changed(p.requester.return_value, member_id=None)
        with pytest.raises(Clarification):
            await service.session(PRINCIPAL, "one")

    asyncio.run(run())


def test_refresh_discards_old_room_preference_targets():
    from hirz.executor.replanning import outstanding
    from hirz.executor.runtime import RuntimeInputs
    from tests.unit.test_refresh import world_inputs

    async def run():
        world, registry, snap, runtime = await world_inputs()
        try:
            preferred = preference_snapshot()
            snap = changed(
                snap,
                data=snap.data
                | {
                    "preferences": preferred.data["preferences"],
                    "observations": [
                        r
                        for r in snap.data["observations"]
                        if r["domain"] != "presence"
                    ]
                    + preferred.data["observations"],
                    "schedule_events": [],
                },
            )
            result = coordinate(workload(), snap, POLICY)
            assert result.inputs.zones[0].targets[0] == 72
            runtime = RuntimeInputs.from_schedule(result.inputs, result.result.schedule)
            # Presence expires/changes independently of the original preference window.
            departed = changed(
                snap,
                data=snap.data
                | {
                    "observations": [
                        r
                        for r in snap.data["observations"]
                        if r["domain"] != "presence"
                    ]
                },
            )
            rebuilt, _, _ = outstanding(
                runtime, departed, runtime.workload.requester, (), world.read()[1], {}
            )
            assert set(rebuilt.zones[0].targets) == {70}
            refreshed = coordinate(rebuilt, departed, POLICY)
            assert set(refreshed.inputs.zones[0].preferences) == {None}
            assert set(refreshed.inputs.zones[0].targets) == {70}
        finally:
            await registry.close()

    asyncio.run(run())


def test_reference_outage_requires_clarification_and_turn_identity_is_consistent():
    from unittest.mock import AsyncMock, Mock

    import sqlalchemy as sa

    from hirz.memory.service import MemoryService
    from tests.unit.test_pipeline import PRINCIPAL, pipeline

    async def run():
        p = await pipeline()
        p.connection.begin = Mock(return_value=AsyncMock())
        p.connection.scalar.side_effect = sa.exc.OperationalError(
            "query", {}, RuntimeError("unavailable")
        )
        with pytest.raises(Clarification, match="unavailable"):
            await MemoryService(p).resolve(PRINCIPAL, "one", "plan")

    asyncio.run(run())
    session = Session(
        household_id=HOME, member_id=uuid4(), surface="app", session_id="one"
    )
    with pytest.raises(ValueError, match="identity mismatch"):
        Turn(
            id=uuid4(),
            session=session,
            session_id="two",
            role="user",
            text="text",
            sequence=1,
            recorded_at=AT,
            decision_seq=1,
        )
