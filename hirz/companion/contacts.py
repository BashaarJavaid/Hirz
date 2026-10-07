"""Owner-authorized archival, preserving contact and verification history."""

from uuid import UUID

import sqlalchemy as sa

from hirz import db
from hirz.contacts.service import grant
from hirz.graph.repository import row_model
from hirz.pipeline.models import Principal, VerificationCase
from hirz.pipeline.service import Pipeline


async def remove(p: Pipeline, principal: Principal, contact_id: UUID) -> None:
    contact = await p.repo.get("trusted_contacts", {"id": contact_id})
    if contact is None:
        raise ValueError("Contact unavailable")
    decision = await grant(p, principal, "remove", str(contact_id))
    links = (
        (
            await p.connection.execute(
                sa.select(db.contact_links)
                .where(
                    p.scope(db.contact_links),
                    db.contact_links.c.contact_id == contact_id,
                )
                .order_by(db.contact_links.c.id)
                .with_for_update()
            )
        )
        .mappings()
        .all()
    )
    for channel in links:
        await p.connection.execute(
            db.contact_links.update()
            .where(db.contact_links.c.id == channel["id"])
            .values(
                status="revoked",
                decision_seq=decision.audit_id,
            )
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
                    sa.or_(
                        db.verification_cases.c.document["verification"][
                            "status"
                        ].astext
                        == "pending",
                        sa.exists(
                            sa.select(db.checkin_jobs.c.id).where(
                                p.scope(db.checkin_jobs),
                                db.checkin_jobs.c.case_id == db.verification_cases.c.id,
                                db.checkin_jobs.c.status == "approval",
                            )
                        ),
                    ),
                )
            )
        )
        .mappings()
        .all()
    )
    for row in rows:
        case = VerificationCase.model_validate(row["document"])
        if case.verification is None or case.verification.source == "real":
            from hirz.contacts.checkins import finish

            job = (
                (
                    await p.connection.execute(
                        sa.select(db.checkin_jobs).where(
                            p.scope(db.checkin_jobs),
                            db.checkin_jobs.c.case_id == case.case_id,
                        )
                    )
                )
                .mappings()
                .one()
            )
            receipt = (
                (
                    await p.connection.execute(
                        sa.select(db.checkin_receipts).where(
                            db.checkin_receipts.c.job_id == job["id"],
                        )
                    )
                )
                .mappings()
                .one_or_none()
            )
            worker = principal.model_copy(
                update={
                    "surface": "scheduler",
                    "credential_id": None,
                    "passkey_verified": False,
                }
            )
            await finish(
                p,
                worker,
                dict(job),
                case,
                receipt["answer"] if receipt else "no_answer",
                None if receipt else "contact_removed",
            )
            continue
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
