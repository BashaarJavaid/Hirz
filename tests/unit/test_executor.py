"""Local command contract, hash compatibility and planner bounded endings."""

from datetime import timedelta

import pytest

from hirz.executor.contracts import ending, validate
from hirz.pipeline.hashing import action_hash, digest, ingest
from hirz.pipeline.models import Action, ExpectedEffect, Inverse, Revert
from tests.unit.test_pipeline import AT, action


def queued(**changes):
    a = action(
        "environment.lights",
        params={"on": True},
        scheduled_for=AT,
        expected_effect=ExpectedEffect(
            entity="light.living_room",
            attr="on",
            value=True,
            by=AT + timedelta(seconds=30),
        ),
    )
    a = a.model_copy(update=changes)
    return a.model_copy(update={"content_hash": action_hash(a)})


def test_legacy_hash_and_optional_decision_serialization():
    from hirz.pipeline.models import Decision

    a = queued()
    assert a.content_hash == "sha256:" + digest(
        {
            "class": a.action_class,
            "target": a.target.model_dump(),
            "params": a.params,
            "scheduled_for": a.scheduled_for,
        }
    )
    assert "revert" not in a.model_dump()
    d = Decision.model_validate(
        dict(
            decision="execute",
            event_type="EXECUTE",
            action_id=a.action_id,
            constitution=dict(
                version=1, rule="fixture", mode="auto", conditions_met=True
            ),
        )
    )
    assert "status" not in d.model_dump() and "speakable" not in d.model_dump()
    assert validate(queued(scheduled_for=None)).scheduled_for is None


@pytest.mark.parametrize(
    "changes",
    [
        {"params": {"on": 1}},
        {"params": {"on": True, "extra": 1}},
        {"expected_effect": None},
        {"action_class": "security.door_unlock"},
        {"action_class": "energy.hvac_adjust", "params": {"target_f": 77}},
        {"action_class": "energy.hvac_adjust", "params": {"target_f": True}},
        {"action_class": "energy.hvac_adjust", "params": {"target_f": 65}},
        {
            "action_class": "energy.ev_charge",
            "params": {"charging": True, "charge_limit": 0.81},
        },
        {"action_class": "energy.battery_dispatch", "params": {"dispatch_kw": 2}},
    ],
)
def test_unsupported_commands_fail_before_dispatch(changes):
    with pytest.raises(ValueError):
        validate(queued(**changes))


def test_bounded_tampering_nonrecursive_and_wrong_target():
    a = queued()
    inverse = Inverse.model_validate(
        {"class": a.action_class, "target": a.target, "params": {"on": False}}
    )
    bounded = queued(revert=Revert(after_s=20, inverse=inverse))
    assert bounded.content_hash != a.content_hash
    assert ending(bounded).scheduled_for == AT + timedelta(seconds=20)
    assert ending(bounded).expected_effect.by == AT + timedelta(seconds=30)
    with pytest.raises(ValueError):
        ingest(
            bounded.model_copy(
                update={"revert": bounded.revert.model_copy(update={"after_s": 10})}
            )
        )
    with pytest.raises(ValueError):
        validate(
            queued(
                revert=Revert(
                    after_s=20,
                    inverse=inverse.model_copy(
                        update={
                            "target": inverse.target.model_copy(
                                update={"entity": "another"}
                            )
                        }
                    ),
                )
            )
        )
    with pytest.raises(ValueError):
        Revert.model_validate(
            {
                "after_s": 20,
                "inverse": inverse.model_dump(by_alias=True) | {"revert": {}},
            }
        )


def test_fractional_endings_preserve_deadlines_and_existing_integer_hashes():
    from hirz.planner.models import Control, Schedule
    from hirz.planner.service import actions
    from tests.unit.test_planner import tiny

    a = queued()
    inverse = Inverse.model_validate(
        {"class": a.action_class, "target": a.target, "params": {"on": False}}
    )
    original = queued(revert=Revert(after_s=20, inverse=inverse))
    restored = Action.model_validate(original.model_dump(mode="json", by_alias=True))
    assert type(restored.revert.after_s) is int
    assert restored.content_hash == action_hash(restored)
    for value in (True, "1.5", 0, -1, float("nan"), float("inf"), 0.0000001):
        with pytest.raises(ValueError):
            Revert(after_s=value, inverse=inverse)
    bounded = queued(revert=Revert(after_s=19.999999, inverse=inverse))
    assert ending(validate(bounded)).scheduled_for == AT + timedelta(
        seconds=20, microseconds=-1
    )
    assert bounded.content_hash != original.content_hash
    p = tiny()
    p = p.model_copy(
        update={
            "slots": (
                p.slots[0].model_copy(
                    update={"start": p.slots[0].start + timedelta(microseconds=1)}
                ),
                p.slots[1],
            )
        }
    )
    controls = tuple(
        Control(ev_kwh=value, battery_kw=0, targets=(), modes=(), appliance_start=False)
        for value in (0.5, 0.5)
    )
    for planned in actions(
        p, Schedule(method="greedy", controls=controls), "fractional"
    ):
        if planned.revert:
            assert ending(validate(planned)).scheduled_for == planned.expected_effect.by


def test_planner_controls_end_at_next_change_and_horizon():
    from hirz.planner.service import plan
    from tests.unit.test_planner import tiny

    result = plan(tiny())
    assert result.plan is not None
    for a in result.actions:
        validate(a)
        assert a.expected_effect is not None
        if a.params.get("charging"):
            assert a.revert and ending(a).scheduled_for <= result.plan.horizon.end
