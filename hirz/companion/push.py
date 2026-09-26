"""Encrypted subscriptions and three-attempt generic notification delivery."""

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import sqlalchemy as sa
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import BaseModel, ConfigDict, Field, model_validator
from webauthn.helpers import base64url_to_bytes

from hirz import db
from hirz.companion.auth import account, digest
from hirz.pipeline.hashing import action_hash
from hirz.pipeline.models import Action, Principal, Requester, Target
from hirz.pipeline.service import Pipeline


class Keys(BaseModel):
    model_config = ConfigDict(extra="forbid")
    p256dh: str = Field(max_length=128)
    auth: str = Field(max_length=64)


class Subscription(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: str = Field(max_length=4096)
    keys: Keys
    expirationTime: int | None = None

    @model_validator(mode="after")
    def valid(self) -> "Subscription":
        endpoint = urlsplit(self.endpoint)
        host = endpoint.hostname or ""
        if (
            endpoint.scheme != "https"
            or endpoint.username
            or endpoint.password
            or endpoint.fragment
            or endpoint.port not in {None, 443}
            or not (
                host == "fcm.googleapis.com"
                or host == "web.push.apple.com"
                or host.endswith(".push.apple.com")
                or host == "updates.push.services.mozilla.com"
            )
        ):
            raise ValueError("Unsupported browser push service")
        ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), base64url_to_bytes(self.keys.p256dh)
        )
        if len(base64url_to_bytes(self.keys.auth)) != 16:
            raise ValueError("Invalid browser push authentication key")
        return self


@dataclass(frozen=True)
class Config:
    encryption_key: str
    vapid_private_key: str
    vapid_public_key: str
    subject: str

    def __post_init__(self) -> None:
        Fernet(self.encryption_key.encode())
        private = base64url_to_bytes(self.vapid_private_key)
        if len(private) != 32:
            raise ValueError("VAPID requires a P-256 private key")
        key = ec.derive_private_key(int.from_bytes(private, "big"), ec.SECP256R1())
        public = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), base64url_to_bytes(self.vapid_public_key)
        )
        if key.public_key().public_numbers() != public.public_numbers():
            raise ValueError("VAPID key pair does not match")
        if not self.subject.startswith(("mailto:", "https://")):
            raise ValueError("A VAPID contact is required")

    @classmethod
    def environment(cls) -> "Config | None":
        names = (
            "HIRZ_PUSH_ENCRYPTION_KEY",
            "HIRZ_VAPID_PRIVATE_KEY",
            "HIRZ_VAPID_PUBLIC_KEY",
            "HIRZ_VAPID_SUBJECT",
        )
        values = [os.environ.get(name) for name in names]
        if not any(values):
            return None
        if not all(values):
            raise ValueError("Complete push configuration is required")
        return cls(*(str(v) for v in values))


async def grant(
    p: Pipeline, principal: Principal, member: UUID, operation: str, reference: str
) -> None:
    action = Action.model_validate(
        dict(
            action_id=uuid4().hex,
            action_class="communication.notify_member",
            target=Target(adapter="member", entity=str(member)),
            params={"operation": operation, "reference": reference},
            requested_by=Requester(
                member_id=None, role="unknown", surface=principal.surface
            ),
            reason="Hirz needs your attention",
            content_hash="",
        )
    )
    action = action.model_copy(update={"content_hash": action_hash(action)})
    decision = await p.mutate_locked(action, principal)
    if decision.decision != "execute":
        raise ValueError("Notification authorization refused")


async def subscribe(
    p: Pipeline, principal: Principal, member: UUID, value: Subscription, config: Config
) -> str:
    previous = (
        (
            await p.connection.execute(
                sa.select(db.companion_push).where(
                    p.scope(db.companion_push),
                    db.companion_push.c.endpoint_hash == digest(value.endpoint),
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if previous and previous["member_id"] != member:
        raise ValueError("This browser is subscribed for another member")
    reference = previous["id"] if previous else uuid4().hex
    await grant(p, principal, member, "subscribe", reference)
    encrypted = Fernet(config.encryption_key.encode()).encrypt(
        value.model_dump_json().encode()
    )
    if previous:
        await p.connection.execute(
            db.companion_push.update()
            .where(db.companion_push.c.id == reference)
            .values(ciphertext=encrypted, disabled_at=None)
        )
    else:
        await p.connection.execute(
            db.companion_push.insert().values(
                id=reference,
                household_id=p.household_id,
                member_id=member,
                endpoint_hash=digest(value.endpoint),
                ciphertext=encrypted,
                created_at=p.clock(),
            )
        )
    return str(reference)


async def queue(
    p: Pipeline, principal: Principal, sub: Any, reference: str, expires_at: datetime
) -> None:
    if expires_at <= p.clock():
        return
    exists = await p.connection.scalar(
        sa.select(db.companion_delivery.c.reference).where(
            db.companion_delivery.c.subscription_id == sub["id"],
            db.companion_delivery.c.reference == reference,
        )
    )
    if exists is None:
        await grant(p, principal, sub["member_id"], "queue", reference)
        await p.connection.execute(
            db.companion_delivery.insert().values(
                subscription_id=sub["id"],
                reference=reference,
                expires_at=expires_at,
                next_attempt=p.clock(),
            )
        )


async def destination(p: Pipeline, member: UUID, reference: str) -> str | None:
    if reference.startswith("notice:"):
        exists = await p.connection.scalar(
            sa.select(db.pending_notifications.c.audit_seq).where(
                p.scope(db.pending_notifications),
                db.pending_notifications.c.member_id == member,
                db.pending_notifications.c.audit_seq
                == int(reference.removeprefix("notice:")),
            )
        )
        return "/tonight" if exists is not None else None
    if reference.startswith("proposal:"):
        exists = await p.connection.scalar(
            sa.select(db.rule_proposals.c.id).where(
                p.scope(db.rule_proposals),
                db.rule_proposals.c.id == reference.removeprefix("proposal:"),
                db.rule_proposals.c.status.in_(["queued", "ready", "failed"]),
            )
        )
        role = await p.connection.scalar(
            sa.select(db.members.c.role).where(
                p.scope(db.members), db.members.c.id == member
            )
        )
        return "/constitution" if exists is not None and role == "owner" else None
    approval = await p.approval(reference)
    if (
        approval is None
        or approval["status"] != "pending"
        or approval["expires_at"] <= p.clock()
    ):
        return None
    proposal = await p.connection.scalar(
        sa.select(db.actions.c.proposal).where(
            p.scope(db.actions), db.actions.c.action_id == approval["action_id"]
        )
    )
    if proposal is None:
        return None
    recipient = await p.requester(await account(p.connection, p.household_id, member))
    rule = p.bundle.policy().rule(proposal["class"], recipient.role)
    if recipient.role not in p.bundle.policy().approvers(
        proposal["class"], rule.quorum
    ) or "app_push" not in (
        rule.ask_channels or p.bundle.policy().defaults.ask_channels
    ):
        return None
    return "/approvals"


async def advance(p: Pipeline, config: Config) -> None:
    """Worker only: claim before sending, then record delivery under another grant."""
    async with p.repo.write(p.clock):
        subscriptions = (
            (
                await p.connection.execute(
                    sa.select(db.companion_push).where(
                        p.scope(db.companion_push),
                        db.companion_push.c.disabled_at.is_(None),
                    )
                )
            )
            .mappings()
            .all()
        )
        pending = (
            (
                await p.connection.execute(
                    sa.select(db.approvals, db.actions.c.proposal)
                    .join(
                        db.actions,
                        sa.and_(
                            db.actions.c.household_id == db.approvals.c.household_id,
                            db.actions.c.action_id == db.approvals.c.action_id,
                        ),
                    )
                    .where(
                        p.scope(db.approvals),
                        db.approvals.c.status == "pending",
                        db.approvals.c.expires_at > p.clock(),
                    )
                )
            )
            .mappings()
            .all()
        )
        for sub in subscriptions:
            principal = (
                await account(p.connection, p.household_id, sub["member_id"])
            ).model_copy(update={"surface": "scheduler"})
            member = await p.requester(principal)
            for approval in pending:
                rule = p.bundle.policy().rule(
                    approval["proposal"]["class"], member.role
                )
                if member.role not in p.bundle.policy().approvers(
                    approval["proposal"]["class"], rule.quorum
                ) or "app_push" not in (
                    rule.ask_channels or p.bundle.policy().defaults.ask_channels
                ):
                    continue
                await queue(
                    p, principal, sub, approval["approval_id"], approval["expires_at"]
                )
            ttl = timedelta(minutes=p.bundle.policy().defaults.approval_ttl_minutes)
            notices = (
                (
                    await p.connection.execute(
                        sa.select(
                            db.pending_notifications.c.audit_seq,
                            db.audit_log.c.created_at,
                        )
                        .join(
                            db.audit_log,
                            sa.and_(
                                db.audit_log.c.household_id
                                == db.pending_notifications.c.household_id,
                                db.audit_log.c.seq
                                == db.pending_notifications.c.audit_seq,
                            ),
                        )
                        .where(
                            p.scope(db.pending_notifications),
                            db.pending_notifications.c.member_id == sub["member_id"],
                            db.audit_log.c.created_at > p.clock() - ttl,
                        )
                    )
                )
                .mappings()
                .all()
            )
            for notice in notices:
                await queue(
                    p,
                    principal,
                    sub,
                    "notice:" + str(notice["audit_seq"]),
                    notice["created_at"] + ttl,
                )
            if member.role == "owner":
                proposals = (
                    (
                        await p.connection.execute(
                            sa.select(db.rule_proposals).where(
                                p.scope(db.rule_proposals),
                                db.rule_proposals.c.status.in_(
                                    ["queued", "ready", "failed"]
                                ),
                                db.rule_proposals.c.created_at > p.clock() - ttl,
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
                for proposal in proposals:
                    await queue(
                        p,
                        principal,
                        sub,
                        "proposal:" + proposal["id"],
                        proposal["created_at"] + ttl,
                    )
    # Each network attempt is outside the household transaction.
    for sub in subscriptions:
        async with p.repo.write(p.clock):
            job = (
                (
                    await p.connection.execute(
                        sa.select(db.companion_delivery)
                        .where(
                            db.companion_delivery.c.subscription_id == sub["id"],
                            db.companion_delivery.c.status.in_(["pending", "sending"]),
                            sa.or_(
                                db.companion_delivery.c.next_attempt <= p.clock(),
                                db.companion_delivery.c.expires_at <= p.clock(),
                            ),
                        )
                        .order_by(db.companion_delivery.c.next_attempt)
                        .limit(1)
                    )
                )
                .mappings()
                .one_or_none()
            )
            if job is None:
                continue
            principal = (
                await account(p.connection, p.household_id, sub["member_id"])
            ).model_copy(update={"surface": "scheduler"})
            url = (
                await destination(p, sub["member_id"], job["reference"])
                if job["expires_at"] > p.clock() and job["attempts"] < 3
                else None
            )
            if url is None:
                await grant(p, principal, sub["member_id"], "cancel", job["reference"])
                await p.connection.execute(
                    db.companion_delivery.update()
                    .where(
                        db.companion_delivery.c.subscription_id == sub["id"],
                        db.companion_delivery.c.reference == job["reference"],
                    )
                    .values(status="failed")
                )
                continue
            active = await p.connection.scalar(
                sa.select(db.companion_push.c.id).where(
                    db.companion_push.c.id == sub["id"],
                    db.companion_push.c.disabled_at.is_(None),
                )
            )
            if not active:
                continue
            await grant(p, principal, sub["member_id"], "attempt", job["reference"])
            attempts = job["attempts"] + 1
            await p.connection.execute(
                db.companion_delivery.update()
                .where(
                    db.companion_delivery.c.subscription_id == sub["id"],
                    db.companion_delivery.c.reference == job["reference"],
                )
                .values(
                    attempts=attempts,
                    status="sending",
                    next_attempt=p.clock() + timedelta(seconds=30 * attempts),
                )
            )
        gone = False
        try:
            from pywebpush import (  # type: ignore[import-untyped]
                WebPushException,
                webpush_async,
            )

            subscription = Subscription.model_validate_json(
                Fernet(config.encryption_key.encode()).decrypt(sub["ciphertext"])
            )
            if p.clock() >= job["expires_at"]:
                raise ValueError("Notification expired before delivery")
            await webpush_async(
                subscription_info=subscription.model_dump(exclude={"expirationTime"}),
                data=json.dumps({"title": "Hirz needs your attention", "url": url}),
                vapid_private_key=config.vapid_private_key,
                vapid_claims={"sub": config.subject},
                timeout=5,
                ttl=max(0, int((job["expires_at"] - p.clock()).total_seconds())),
            )
            status = "sent"
        except WebPushException as exc:
            gone = exc.status_code in {404, 410}
            status = "failed" if gone or attempts >= 3 else "pending"
        except Exception:
            status = "failed" if attempts >= 3 else "pending"
        async with p.repo.write(p.clock):
            await grant(p, principal, sub["member_id"], "result", job["reference"])
            await p.connection.execute(
                db.companion_delivery.update()
                .where(
                    db.companion_delivery.c.subscription_id == sub["id"],
                    db.companion_delivery.c.reference == job["reference"],
                )
                .values(status=status)
            )
            if gone:
                await p.connection.execute(
                    db.companion_push.update()
                    .where(db.companion_push.c.id == sub["id"])
                    .values(disabled_at=p.clock())
                )
