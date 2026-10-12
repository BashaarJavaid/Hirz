"""Press-time correlation boundaries, independent of replies or visitor claims."""

from datetime import timedelta

import pytest

from hirz.pipeline.models import VerificationState
from hirz.protect.courier import trigger
from tests.unit.test_pipeline import AT, snapshot
from tests.unit.test_protect import case


@pytest.mark.parametrize(
    "age,eligible", [(0, True), (3600, True), (3600.001, False), (-1, False)]
)
@pytest.mark.parametrize(
    "status", [None, "pending", "genuine", "not_genuine", "will_call", "no_answer"]
)
def test_case_window_and_every_reply(age, eligible, status):
    value = case()
    if status:
        value = value.model_copy(
            update={
                "verification": VerificationState(
                    status=status,
                    sent_to="contact",
                    started_at=AT,
                    expires_at=AT + timedelta(minutes=2),
                )
            }
        )
    snap = snapshot()
    bell = next(r for r in snap.data["observations"] if r["domain"] == "doorbell")
    bell["state"]["last_press_at"] = AT.isoformat()
    assert bool(trigger(value, AT - timedelta(seconds=age), snap, AT)) == eligible


@pytest.mark.parametrize(
    "press_age,observation_age,available,expected",
    [
        (60, 0, True, True),
        (60.001, 0, True, False),
        (-1, 0, True, False),
        (0, 61, True, False),
        (0, -1, True, False),
        (0, 0, False, False),
    ],
)
def test_fresh_available_press(press_age, observation_age, available, expected):
    snap = snapshot()
    bell = next(r for r in snap.data["observations"] if r["domain"] == "doorbell")
    bell["observed_at"] = (AT - timedelta(seconds=observation_age)).isoformat()
    bell["state"].update(
        last_press_at=(AT - timedelta(seconds=press_age)).isoformat(),
        available=available,
    )
    assert bool(trigger(case(), AT - timedelta(minutes=5), snap, AT)) == expected


@pytest.mark.parametrize("offset,expected", [(0, False), (60, True)])
def test_arrivals_are_start_inclusive_end_exclusive(offset, expected):
    snap = snapshot()
    bell = next(r for r in snap.data["observations"] if r["domain"] == "doorbell")
    bell["state"]["last_press_at"] = AT.isoformat()
    snap.data["schedule_events"] = [
        {
            "kind": "arrival",
            "starts_at": (AT - timedelta(seconds=offset)).isoformat(),
            "ends_at": (AT + timedelta(seconds=60 - offset)).isoformat(),
        }
    ]
    assert bool(trigger(case(), AT, snap, AT)) == expected
    assert trigger(case("Dinner at six"), AT, snap, AT) is None
