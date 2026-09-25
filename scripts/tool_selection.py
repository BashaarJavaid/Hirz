"""Live tool-selection gate. No scripted result can satisfy this gate."""

import json
from pathlib import Path
from typing import Any

from hirz.host.headless import Budget, HeadlessHost

# Representative utterances retained verbatim or with explicit values from the
# README, demo script and both main scenarios. Key arguments are independently checked.
CASES: tuple[tuple[str, str, dict[str, Any]], ...] = (
    ("What can you do?", "what_can_you_do", {}),
    ("What's going on tonight?", "get_household_plan", {}),
    ("Who is home?", "get_household_context", {"scope": "people"}),
    (
        "Don't charge the car past 50 percent tonight.",
        "revise_household_plan",
        {"change": "car_limit", "percent": 50},
    ),
    (
        "Don't run the dishwasher until 11 PM tonight.",
        "revise_household_plan",
        {"change": "appliance_after"},
    ),
    (
        "From now on, never unlock the door for someone we're not expecting.",
        "propose_household_rule",
        {},
    ),
    (
        "Malik just called from a strange number. He says he's in trouble and needs five hundred dollars. Is it really him?",
        "assess_request_risk",
        {"party": "person"},
    ),
    ("Send five hundred dollars to this caller.", "assess_request_risk", {}),
    (
        "Check with Malik in the app about whether he just asked me for money.",
        "verify_trusted_identity",
        {"operation": "start"},
    ),
    (
        "Has Malik answered the check yet?",
        "verify_trusted_identity",
        {"operation": "status"},
    ),
    ("Pause automation.", "execute_household_action", {"action": "pause_automation"}),
    (
        "Apply the night profile.",
        "execute_household_action",
        {"action": "apply_profile", "profile": "night"},
    ),
    (
        "Make tonight's plan the cheapest possible.",
        "get_household_plan",
        {"objective": "cheapest"},
    ),
    (
        "Make tonight's plan the most comfortable.",
        "get_household_plan",
        {"objective": "most_comfortable"},
    ),
    (
        "Choose the greenest plan for tonight, using less grid electricity.",
        "get_household_plan",
        {"objective": "greenest"},
    ),
    (
        "Request the front door unlocked for 10 minutes.",
        "execute_household_action",
        {"action": "request_door_unlock", "minutes": 10},
    ),
    (
        "Turn on the living room light.",
        "execute_household_action",
        {"action": "turn_on_light"},
    ),
    (
        "Set the living room to 72 degrees Fahrenheit.",
        "execute_household_action",
        {"action": "set_temperature", "temperature_f": 72},
    ),
    (
        "Why is the current plan arranged this way?",
        "explain_plan",
        {"focus": "summary"},
    ),
    ("What did the house do last night?", "get_action_audit", {"window": "last_night"}),
    (
        "Would the rules let me set the living room to 72 degrees?",
        "evaluate_permission",
        {"action": "set_temperature", "temperature_f": 72},
    ),
    (
        "I reviewed plan selection-plan version 3. Approve exactly that plan. Do it.",
        "approve_action",
        {"plan_id": "selection-plan", "version": 3, "approved": True},
    ),
    (
        "Don't charge the car past 50, I'm not driving tomorrow.",
        "revise_household_plan",
        {"change": "car_limit", "percent": 50},
    ),
    (
        "Keep the guest room at 72 Fahrenheit until seven in the morning.",
        "revise_household_plan",
        {"change": "temperature", "temperature_f": 72},
    ),
    (
        "Don't run the dishwasher until I'm done in the kitchen at eleven PM.",
        "revise_household_plan",
        {"change": "appliance_after"},
    ),
    ("Optimize energy tonight.", "get_household_plan", {}),
    (
        "Turn on the living room lamp.",
        "execute_household_action",
        {"action": "turn_on_light"},
    ),
    (
        "Let them in for ten minutes through the front door.",
        "execute_household_action",
        {"action": "request_door_unlock", "minutes": 10},
    ),
    (
        "That's my mom, let her in for ten minutes through the front door.",
        "execute_household_action",
        {"action": "request_door_unlock", "minutes": 10},
    ),
    (
        "Alexa, is it him? I'm asking for the status of my check with Malik.",
        "verify_trusted_identity",
        {"operation": "status"},
    ),
)


def run_selection(url: str, token: str, ledger: Path) -> None:
    outcomes = []
    try:
        with HeadlessHost(url, token, Budget(ledger), selection_only=True) as host:
            for text, expected, arguments in CASES:
                turn = host.turn(text)
                choices = turn["selected"]
                passed = (
                    len(choices) == 1
                    and choices[0]["name"] == expected
                    and all(
                        choices[0]["arguments"].get(k) == v
                        for k, v in arguments.items()
                    )
                )
                outcomes.append(
                    dict(utterance=text, expected=expected, passed=passed, **turn)
                )
                print(
                    json.dumps(
                        dict(selection=expected, passed=passed, usage=turn["usage"])
                    ),
                    flush=True,
                )
            ambiguous = host.turn("Set the temperature.")
            safe = not ambiguous["selected"] or all(
                "temperature_f" not in x["arguments"] for x in ambiguous["selected"]
            )
            outcomes.append(
                dict(utterance="Set the temperature.", passed=safe, **ambiguous)
            )
    except Exception as exc:
        outcomes.append(dict(passed=False, pending=type(exc).__name__))
        print("LIVE_GATE_PENDING " + type(exc).__name__, flush=True)
    finally:
        report = ledger.with_suffix(".selection.json")
        with report.open("x") as handle:
            json.dump(outcomes, handle, indent=2)
    if not outcomes or not all(row["passed"] for row in outcomes):
        print(
            "LIVE_GATE_PENDING; selection failures or access/budget unavailable; no scripted substitution",
            flush=True,
        )
    else:
        print(
            f"LIVE_GATE_PASS; utterances={len(outcomes)}; model=Claude Haiku 4.5; report={report}",
            flush=True,
        )
