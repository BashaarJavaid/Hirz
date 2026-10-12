"""Exact registry matching and advisory evidence, without provider calls."""

import copy

import pytest

from hirz.mcp.contracts import Result, response
from hirz.pipeline.models import OrganizationComparison
from hirz.protect.advice import publish
from hirz.protect.organizations import (
    LIMITATION,
    organization_speech,
    parse,
    registry,
    resolve,
)
from hirz.protect.phone import phone
from hirz.protect.scoring import signals
from tests.unit.test_protect import case


@pytest.mark.parametrize("name", ["ComEd", " comed ", "COMMONWEALTH EDISON"])
def test_approved_names(name):
    assert resolve(name) == registry()[0]


@pytest.mark.parametrize(
    "name", [None, "", "the utility", "Com Ed", "CоmEd", "ComEd support"]
)
def test_no_inferred_names(name):
    assert resolve(name) is None


@pytest.mark.parametrize("number", ["800-334-7661", "+1 (800) 334-7661", "18003347661"])
def test_published_formats(number):
    assert phone(number) == registry()[0].phone


@pytest.mark.parametrize(
    "mutation", ["identity", "alias", "empty", "phone", "source", "date", "extra"]
)
def test_malformed_registry(mutation):
    raw = [registry()[0].model_dump(mode="json")]
    if mutation == "identity":
        raw.append(copy.deepcopy(raw[0]))
    elif mutation == "alias":
        raw[0]["aliases"].append("COMED")
    elif mutation == "empty":
        raw[0]["aliases"].append(" ")
    elif mutation == "phone":
        raw[0]["phone"] = "800-334-7661"
    elif mutation == "source":
        raw[0]["source_url"] = "http://example.com"
    elif mutation == "date":
        raw[0]["revision"] = "2026-99-99"
    else:
        raw[0]["extra"] = True
    with pytest.raises(ValueError):
        parse(raw)


def test_enrichment_preserves_evidence_and_warning_limits():
    original = case("When does ComEd open?")
    evidence = OrganizationComparison(
        organization_id="comed",
        display_name="ComEd",
        source_url=str(registry()[0].source_url),
        reviewed_on="2026-10-11",
        registry_revision="2026-10-11",
        saved_contact="insufficient_information",
        registry="matches",
    )
    original = original.model_copy(
        update={
            "subject": original.subject.model_copy(update={"party": "organization"}),
            "organization_comparison": evidence,
            "number_comparison": "matches",
            "speakable": response(
                **organization_speech(evidence, False, original.extraction, "matches")
            ).speakable.model_dump(mode="json"),
        }
    )
    enriched = publish(
        original,
        original.extraction.model_copy(
            update={"status": "complete", "model_signals": signals("urgent dollars")}
        ),
    )
    assert enriched.organization_comparison == evidence
    assert enriched.number_comparison == "matches"
    assert enriched.risk_band.value == "high"
    assert enriched.verification is None
    assert LIMITATION in enriched.speakable["details"]
    assert any("warning signs" in line for line in enriched.speakable["details"])
    Result.model_validate({"speakable": enriched.speakable, "data": {"case": enriched}})
    assert len(enriched.speakable["headline"].split()) <= 20
    assert len(enriched.speakable["details"]) == 3
    assert (
        "number"
        not in organization_speech(None, False, original.extraction, None)["headline"]
    )


def test_invalid_registry_fails_app_startup(monkeypatch):
    from hirz.api.app import create_app

    def invalid():
        return parse([{"id": "malformed"}])

    monkeypatch.setattr("hirz.protect.organizations.registry", invalid)
    with pytest.raises(ValueError):
        create_app()
