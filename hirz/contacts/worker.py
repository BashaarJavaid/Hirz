"""Contact worker; claims commit before SMTP. Errors never log credentials or tokens."""

import asyncio
import smtplib
from datetime import timedelta

import sqlalchemy as sa

from hirz import db
from hirz.companion.auth import account
from hirz.contacts import checkins
from hirz.contacts.secrets import Config, send_email
from hirz.contacts.service import contact_time, grant, link
from hirz.pipeline.hashing import action_hash
from hirz.pipeline.models import Action, Principal, Requester, Target
from hirz.pipeline.service import Pipeline


async def advance(p: Pipeline) -> None:
    config = Config.environment()
    if config is None:
        return
    await sync_channels(p)
    await checkins.advance(p)
    async with p.connection.begin():
        pending = (
            (
                await p.connection.execute(
                    sa.select(db.contact_links.c.id).where(
                        p.scope(db.contact_links),
                        db.contact_links.c.kind == "email",
                        db.contact_links.c.status == "pending",
                        db.contact_links.c.delivery_status.in_(["pending", "sending"]),
                    )
                )
            )
            .scalars()
            .all()
        )
    for reference in pending:
        async with p.repo.write(p.clock):
            channel = await link(p, reference)
            if channel["status"] != "pending" or channel["delivery_status"] not in {
                "pending",
                "sending",
            }:
                continue
            principal = (
                await account(p.connection, p.household_id, channel["owner_id"])
            ).model_copy(update={"surface": "scheduler", "requester_confirmed": True})
            if (
                channel["expires_at"] <= contact_time(p)
                or channel["delivery_attempts"] >= 3
            ):
                decision = await grant(p, principal, "process", reference)
                await p.connection.execute(
                    db.contact_links.update()
                    .where(db.contact_links.c.id == reference)
                    .values(
                        delivery_status="failed",
                        ciphertext=None,
                        decision_seq=decision.audit_id,
                    )
                )
                continue
            if channel["next_attempt"] and channel["next_attempt"] > contact_time(p):
                continue
            if not await send_allowed(p, channel["contact_id"]):
                continue
            action = Action.model_validate(
                dict(
                    action_id=reference,
                    action_class="communication.contact_trusted_contact",
                    target=Target(
                        adapter="contacts", entity=str(channel["contact_id"])
                    ),
                    params={"operation": "enrollment", "channel": reference},
                    requested_by=Requester(
                        member_id=None, role="unknown", surface="app"
                    ),
                    reason="Mailbox confirmation requested by the household owner",
                    content_hash="",
                )
            )
            action = action.model_copy(update={"content_hash": action_hash(action)})
            original = Principal.model_validate(channel["proof"]["requester"])
            stored_grant = await p.connection.scalar(
                sa.select(db.actions.c.grant_seq).where(
                    p.scope(db.actions),
                    db.actions.c.action_id == reference,
                )
            )
            if stored_grant is None:
                permission = await p.mutate_locked(action, original)
                if permission.decision != "execute":
                    continue
            if not await checkins.delivery_allowed(p, action, original):
                continue
            attempt = channel["delivery_attempts"] + 1
            decision = await grant(p, principal, "process", reference)
            await p.connection.execute(
                db.contact_links.update()
                .where(db.contact_links.c.id == reference)
                .values(
                    delivery_status="sending",
                    delivery_attempts=attempt,
                    next_attempt=contact_time(p) + timedelta(seconds=30 * attempt),
                    decision_seq=decision.audit_id,
                )
            )
            private = config.open(channel["ciphertext"])
        permanent = False
        try:
            await asyncio.to_thread(
                send_email, config, private["destination"], private["token"]
            )
            status = "sent"
        except (smtplib.SMTPRecipientsRefused, smtplib.SMTPAuthenticationError):
            status, permanent = "failed", True
        except (OSError, smtplib.SMTPException, ValueError):
            status = "failed" if attempt >= 3 else "pending"
        async with p.repo.write(p.clock):
            channel = await link(p, reference)
            decision = await grant(p, principal, "process", reference)
            await p.connection.execute(
                db.contact_links.update()
                .where(db.contact_links.c.id == reference)
                .values(
                    delivery_status=status,
                    decision_seq=decision.audit_id,
                    delivery_attempts=3 if permanent else attempt,
                )
            )


async def sync_channels(p: Pipeline) -> None:
    """Project only hashes/provenance; channel validity always comes from private links."""
    from uuid import UUID, uuid5

    from hirz.graph.models import ContactChannel
    from hirz.graph.repository import row_model

    async with p.repo.write(p.clock):
        links = (
            (
                await p.connection.execute(
                    sa.select(db.contact_links)
                    .where(p.scope(db.contact_links))
                    .order_by(db.contact_links.c.id)
                    .with_for_update()
                )
            )
            .mappings()
            .all()
        )
        for channel in links:
            principal = (
                await account(p.connection, p.household_id, channel["owner_id"])
            ).model_copy(update={"surface": "scheduler"})
            phone_id = uuid5(UUID(channel["id"]), "phone")
            if channel["status"] == "revoked":
                for reference in (UUID(channel["id"]), phone_id):
                    current = await p.repo.get("contact_channels", {"id": reference})
                    if current:
                        await grant(p, principal, "process", channel["id"])
                        await p.repo.close(
                            "contact_channels",
                            row_model("contact_channels", current),
                            expected_version=current["valid_from"],
                        )
            elif channel["status"] == "active" and (channel["proof"] or {}).get(
                "phone_hash"
            ):
                current = await p.repo.get("contact_channels", {"id": phone_id})
                value = channel["proof"]["phone_hash"]
                if current and current["attributes"]["value_hash"] == value:
                    continue
                await grant(p, principal, "process", channel["id"])
                await p.repo.put(
                    "contact_channels",
                    ContactChannel(
                        id=phone_id,
                        household_id=p.household_id,
                        contact_id=channel["contact_id"],
                        kind="phone",
                        value_hash=value,
                        verified_at=p.repo._at,
                        source="real",
                        provenance="contact-confirmed",
                    ),
                    expected_version=current["valid_from"] if current else None,
                )


async def send_allowed(p: Pipeline, contact_id: object) -> bool:
    """Conservative rolling caps count all transport attempts, including crash retries."""
    from datetime import timedelta

    for window, limit, contact in (
        (timedelta(minutes=15), 3, contact_id),
        (timedelta(days=1), 20, None),
    ):
        checks = (
            sa.select(sa.func.coalesce(sa.func.sum(db.checkin_jobs.c.attempts), 0))
            .join(
                db.contact_links,
                db.contact_links.c.id == db.checkin_jobs.c.link_id,
            )
            .where(
                p.scope(db.checkin_jobs),
                db.checkin_jobs.c.created_at >= contact_time(p) - window,
            )
        )
        enrollments = sa.select(
            sa.func.coalesce(sa.func.sum(db.contact_links.c.delivery_attempts), 0)
        ).where(
            p.scope(db.contact_links),
            db.contact_links.c.created_at >= contact_time(p) - window,
        )
        if contact is not None:
            checks = checks.where(db.contact_links.c.contact_id == contact)
            enrollments = enrollments.where(db.contact_links.c.contact_id == contact)
        if (
            int(await p.connection.scalar(checks) or 0)
            + int(await p.connection.scalar(enrollments) or 0)
            >= limit
        ):
            return False
    return True
