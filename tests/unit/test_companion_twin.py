"""Scenario controls validate the existing DSL and never accept approval evidence."""

from datetime import timedelta

import pytest

from hirz.companion.twin import (
    Command,
    Controls,
    injected,
    position,
    scenario,
    time_label,
)


def test_scenario_controls_and_isolated_injection(tmp_path):
    loaded = scenario("parents-scam-check")
    at = loaded.spec.clock.start
    row = {
        "scenario": "parents-scam-check",
        "controls": Controls(at=at).model_dump(mode="json"),
        "updated_at": at,
    }
    assert position(row, at + timedelta(minutes=20)) == at
    row["controls"]["paused"] = False
    assert position(row, at + timedelta(seconds=5)) == at + timedelta(minutes=5)
    assert position(row, at + timedelta(days=1)) == loaded.spec.clock.end
    command = Command(
        operation="inject",
        id="test",
        event={
            "at": "17:01",
            "event": "doorbell.press",
            "entity": "doorbell.front_door",
        },
    )
    controls = Controls(at=at, injections=[command.event])
    result = injected("parents-scam-check", controls, tmp_path)
    assert any(
        e.event == "doorbell.press" and e.at == "17:01" for e in result.spec.timeline
    )
    assert time_label(result, at) == "17:00"
    assert result.seed_path == loaded.seed_path.resolve()
    for event in (
        {"at": "17:01", "event": "app.approve", "deferred": "Pretend authenticated"},
        {
            "at": "17:01",
            "event": "constitution.activate",
            "member": "malik",
            "patch": "/tmp/anything.yaml",
        },
        {
            "at": "17:01",
            "event": "doorbell.press",
            "entity": "doorbell.front_door",
            "passkey_verified": True,
        },
    ):
        with pytest.raises(ValueError):
            Command(operation="inject", id="test", event=event)
    with pytest.raises(ValueError):
        scenario("../../constitutions/quinn-home")


def test_interactive_doorbell_samples_running_clock_once():
    from itertools import count

    from hirz.twin.clock import SimClock

    world = scenario("demo-evening").world
    ticks = count()
    world.clock = SimClock(world.clock(), 1, timer=lambda: next(ticks) / 1000)
    with pytest.raises(ValueError, match="current simulation instant"):
        world.doorbell_event("doorbell.front_door", world.clock(), "press", None)
    event = world.doorbell_event("doorbell.front_door", None, "press", None)
    assert event.state.last_press_at == event.observed_at


def test_twin_factory_survives_policy_activation_without_cross_household_access():
    from uuid import uuid4

    from hirz.twin.adapters import factories

    world = scenario("demo-evening").world
    factory = factories(world)[("devices", "twin")]
    updated = world.household.model_copy(
        update={"constitution_version": 8, "autonomy_paused": True}
    )
    assert factory(updated).household_id == world.household.id
    with pytest.raises(ValueError, match="another household"):
        factory(updated.model_copy(update={"id": uuid4()}))
