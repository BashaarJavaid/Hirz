"""Consumer notices and monotone publication of advisory signals."""

from datetime import datetime

from hirz.pipeline.models import (
    VerificationCase,
    VerificationExtraction,
)
from hirz.protect.scoring import band, union
from hirz.risk import RiskBand

OFFLINE = "Keyword-only check; some warning signs may be missed."
PENDING = "Additional warning checks are in progress."
LABELS = {
    "financial_or_access_request": "Money or access was requested",
    "unfamiliar_channel_reported": "An unfamiliar channel was reported",
    "secrecy": "You were asked to keep this secret",
    "third_party_recipient": "A third-party recipient was named",
    "urgency_language": "Pressure to act quickly",
    "claimed_authority": "A claim of authority",
}


def notice(extraction: VerificationExtraction | None) -> str:
    if extraction and extraction.status in {"pending", "running"}:
        return PENDING
    if extraction and extraction.status == "complete":
        return (
            "Additional warning checks completed; possible warning signs are advisory."
        )
    return OFFLINE


def labels(case: VerificationCase) -> tuple[str, ...]:
    keywords = (
        {s.signal for s in case.extraction.keyword_signals}
        if case.extraction
        else {s.signal for s in case.signals}
    )
    return tuple(
        (
            "Possible "
            + {
                "financial_or_access_request": "money or access request",
                "unfamiliar_channel_reported": "reported unfamiliar channel",
                "secrecy": "request for secrecy",
                "third_party_recipient": "third-party recipient",
                "urgency_language": "pressure to act quickly",
                "claimed_authority": "claim of authority",
            }[s.signal]
            if s.signal not in keywords
            else LABELS[s.signal]
        )
        for s in case.signals[:3]
    )


def publish(
    case: VerificationCase, extraction: VerificationExtraction
) -> VerificationCase:
    found = union(case.signals, extraction.keyword_signals, extraction.model_signals)
    speech = dict(case.speakable)
    details = speech.get("details") or []
    assert isinstance(details, (list, tuple))
    speech["details"] = [
        d for d in details if d not in {OFFLINE, PENDING, notice(extraction)}
    ] + [notice(extraction)]
    if found and not case.verification and case.subject.party == "person":
        speech["headline"] = (
            "This request has warning signs. Check with your trusted contact before acting."
        )
    if case.subject.party == "organization" and not case.verification:
        from hirz.protect.organizations import organization_speech

        speech = organization_speech(
            case.organization_comparison,
            bool(found),
            extraction,
            case.number_comparison,
        )
    return case.model_copy(
        update={
            "extraction": extraction,
            "signals": found,
            "risk_band": max((case.risk_band, band(found)), key=list(RiskBand).index),
            "recommended": ("verify_via_verified_channel", "do_not_transfer")
            if found
            else case.recommended,
            "speakable": speech,
        }
    )


def retry_advice(case: VerificationCase, at: datetime) -> VerificationCase:
    if case.extraction and case.extraction.status in {"pending", "running"}:
        return publish(
            case,
            case.extraction.model_copy(
                update={
                    "status": "fallback",
                    "finished_at": at,
                    "failure_code": "retry_unfinished",
                }
            ),
        )
    return case
