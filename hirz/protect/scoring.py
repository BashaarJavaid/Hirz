"""ADR-015 keyword vocabulary and deterministic advisory weights."""

import re

from hirz.pipeline.models import VerificationSignal
from hirz.risk import RiskBand

# Approved 2026-09-23. Advisory only; never supplies execution's trusted scam flag.
PHRASES: dict[str, tuple[int, tuple[str, ...]]] = {
    "financial_or_access_request": (
        2,
        (
            "send money",
            "pay money",
            "transfer money",
            "wire money",
            "dollars",
            "gift cards",
            "bank details",
            "password",
            "verification code",
            "unlock the door",
            "open the door",
        ),
    ),
    "unfamiliar_channel_reported": (
        2,
        ("strange number", "new number", "unknown number", "different number"),
    ),
    "secrecy": (2, ("keep this secret", "don't tell anyone")),
    "third_party_recipient": (
        2,
        ("courier", "someone collecting money", "another person's account"),
    ),
    "urgency_language": (1, ("urgent", "immediately", "right now")),
    "claimed_authority": (1, ("police", "government", "bank", "irs")),
}


def signals(text: str) -> tuple[VerificationSignal, ...]:
    found = []
    for name, (weight, phrases) in PHRASES.items():
        matched = False
        for clause in re.split(r"[.!?;,\n]", text.casefold().replace("’", "'")):
            for phrase in phrases:
                for match in re.finditer(r"\b" + re.escape(phrase) + r"\b", clause):
                    prefix = re.findall(r"[a-z']+", clause[: match.start()])[-3:]
                    if phrase == "don't tell anyone" or not {
                        "no",
                        "not",
                        "never",
                    }.intersection(prefix):
                        matched = True
        if matched:
            found.append(
                VerificationSignal.model_validate(dict(signal=name, weight=weight))
            )
    return tuple(found)


def band(found: tuple[VerificationSignal, ...]) -> RiskBand:
    names = {s.signal for s in found}
    if {"financial_or_access_request", "unfamiliar_channel_reported"} <= names:
        return RiskBand.CRITICAL
    score = sum(PHRASES[name][0] for name in names)
    return (
        RiskBand.LOW
        if score == 0
        else RiskBand.MEDIUM
        if score <= 2
        else RiskBand.HIGH
        if score <= 4
        else RiskBand.CRITICAL
    )


def scam_pattern(found: tuple[VerificationSignal, ...]) -> bool:
    return {
        "financial_or_access_request",
        "unfamiliar_channel_reported",
        "urgency_language",
    } <= {s.signal for s in found}


def union(*groups: tuple[VerificationSignal, ...]) -> tuple[VerificationSignal, ...]:
    names = {s.signal for group in groups for s in group}
    return tuple(
        VerificationSignal.model_validate({"signal": name, "weight": weight})
        for name, (weight, _) in PHRASES.items()
        if name in names
    )
