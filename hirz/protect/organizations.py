"""Curated public references; matching a number never authenticates a caller."""

from datetime import date, datetime
from functools import cache
from hashlib import sha256
from importlib.resources import files
from typing import Any

import sqlalchemy as sa
import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from hirz import db
from hirz.pipeline.models import OrganizationComparison, VerificationExtraction
from hirz.pipeline.service import Pipeline
from hirz.protect.advice import notice
from hirz.protect.phone import phone


class Organization(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    display_name: str = Field(min_length=1, max_length=100)
    aliases: tuple[str, ...]
    phone: str
    source_url: HttpUrl
    reviewed_on: date
    revision: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")

    @model_validator(mode="after")
    def valid(self) -> "Organization":
        if phone(self.phone) != self.phone or self.source_url.scheme != "https":
            raise ValueError("Registry requires a normalized phone and HTTPS source")
        if any(
            not n.strip() or n != n.strip() for n in (self.display_name, *self.aliases)
        ):
            raise ValueError("Registry names must be nonempty and trimmed")
        date.fromisoformat(self.revision)
        return self


def parse(raw: Any) -> tuple[Organization, ...]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("Registry must contain organizations")
    records = tuple(Organization.model_validate(row) for row in raw)
    identities: set[str] = set()
    names: set[str] = set()
    for record in records:
        if record.id in identities:
            raise ValueError("Duplicate organization identity")
        identities.add(record.id)
        for name in (record.display_name, *record.aliases):
            key = name.casefold()
            if key in names:
                raise ValueError("Duplicate organization name or alias")
            names.add(key)
    return records


@cache
def registry() -> tuple[Organization, ...]:
    return parse(
        yaml.safe_load(files("hirz.protect").joinpath("organizations.yaml").read_text())
    )


def resolve(name: str | None) -> Organization | None:
    return next(
        (
            r
            for r in registry()
            if name
            and name.strip().casefold()
            in {n.casefold() for n in (r.display_name, *r.aliases)}
        ),
        None,
    )


async def saved(p: Pipeline, organization: Organization) -> tuple[Any, Any]:
    contact = (
        (
            await p.connection.execute(
                sa.select(db.trusted_contacts).where(
                    p.scope(db.trusted_contacts),
                    db.trusted_contacts.c.attributes["party"].astext == "organization",
                    db.trusted_contacts.c.attributes["organization_id"].astext
                    == organization.id,
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    channel = None
    if contact:
        channel = (
            (
                await p.connection.execute(
                    sa.select(db.contact_channels).where(
                        p.scope(db.contact_channels),
                        db.contact_channels.c.contact_id == contact["id"],
                        db.contact_channels.c.attributes["provenance"].astext
                        == "registry-confirmed",
                        db.contact_channels.c.attributes["kind"].astext == "phone",
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
    return contact, channel


async def compare(
    p: Pipeline, organization: Organization, number: str | None
) -> tuple[Any, OrganizationComparison | None]:
    contact, channel = await saved(p, organization)
    attributes = channel["attributes"] if channel else {}
    usable = (
        attributes.get("registry_revision") == organization.revision
        and bool(attributes.get("verified_at"))
        and datetime.fromisoformat(attributes["verified_at"]) <= p.clock()
    )
    if number is None:
        return contact if usable else None, None
    hashed = sha256(phone(number).encode()).hexdigest()
    evidence = OrganizationComparison(
        organization_id=organization.id,
        display_name=organization.display_name,
        source_url=str(organization.source_url),
        reviewed_on=organization.reviewed_on.isoformat(),
        registry_revision=organization.revision,
        saved_revision=attributes.get("registry_revision"),
        saved_contact=(
            "matches" if hashed == attributes["value_hash"] else "does_not_match"
        )
        if usable
        else "insufficient_information",
        registry="matches" if phone(number) == organization.phone else "does_not_match",
    )
    return contact if usable else None, evidence


LIMITATION = "Caller ID can be forged. A match does not establish identity or mean you should pay."


def organization_speech(
    evidence: OrganizationComparison | None,
    warning: bool,
    extraction: VerificationExtraction | None,
    comparison: str | None,
) -> dict[str, Any]:
    headline = "There is insufficient information to compare this number with a verified organization record."
    if comparison is None:
        headline = "Contact the utility independently before acting on this request."
    elif evidence:
        name = evidence.display_name
        if comparison == "matches":
            if evidence.saved_contact == evidence.registry == "matches":
                headline = f"The supplied number matches your saved {name} contact and Hirz’s published {name} record."
            elif evidence.saved_contact == "matches":
                headline = f"The supplied number matches your saved {name} contact."
            else:
                headline = (
                    f"The supplied number matches Hirz’s published {name} record."
                )
        elif comparison == "does_not_match":
            headline = f"The supplied number does not match the {name} records checked."
    advice = (
        "This request has warning signs. Do not send money. " if warning else ""
    ) + "Contact the utility independently; a trusted-person check is also available."
    return {
        "headline": headline,
        "details": (LIMITATION, advice, notice(extraction))
        if comparison
        else (advice, notice(extraction)),
        "options": ("Check with a trusted contact",),
    }
