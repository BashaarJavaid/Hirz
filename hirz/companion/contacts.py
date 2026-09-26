"""Owner-authorized archival, preserving contact and verification history."""

from uuid import UUID

import sqlalchemy as sa

from hirz import db
from hirz.companion.governance import household
from hirz.graph.repository import row_model
from hirz.pipeline.models import Principal, VerificationCase
from hirz.pipeline.service import Pipeline


async def remove(p: Pipeline, principal: Principal, contact_id: UUID) -> None:
    contact = await p.repo.get("trusted_contacts", {"id": contact_id})
    if contact is None:
        raise ValueError("Contact unavailable")
    decision = await household(
        p, principal, "contacts", {"operation": "remove", "contact_id": str(contact_id)}
    )
    channels = (
        (
            await p.connection.execute(
                sa.select(db.contact_channels).where(
                    p.scope(db.contact_channels),
                    db.contact_channels.c.contact_id == contact_id,
                )
            )
        )
        .mappings()
        .all()
    )
    for channel in channels:
        await p.repo.close(
            "contact_channels",
            row_model("contact_channels", dict(channel)),
            expected_version=channel["valid_from"],
        )
    await p.repo.close(
        "trusted_contacts",
        row_model("trusted_contacts", contact),
        expected_version=contact["valid_from"],
    )
    rows = (
        (
            await p.connection.execute(
                sa.select(db.verification_cases).where(
                    p.scope(db.verification_cases),
                    db.verification_cases.c.document["subject"]["contact_id"].astext
                    == str(contact_id),
                    db.verification_cases.c.document["verification"]["status"].astext
                    == "pending",
                )
            )
        )
        .mappings()
        .all()
    )
    for row in rows:
        case = VerificationCase.model_validate(row["document"])
        assert case.verification
        updated = case.model_copy(
            update={
                "verification": case.verification.model_copy(
                    update={"status": "no_answer"}
                ),
                "speakable": {
                    "headline": "The contact was removed. No reply will be accepted for this check."
                },
            }
        )
        await p.connection.execute(
            db.verification_cases.update()
            .where(
                p.scope(db.verification_cases), db.verification_cases.c.id == row["id"]
            )
            .values(
                document=updated.model_dump(mode="json"), decision_seq=decision.audit_id
            )
        )
