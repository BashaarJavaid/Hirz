"""Transactional signed append; read-only verification/export live in hirz.audit."""

import hashlib
from datetime import datetime
from typing import Any
from uuid import UUID

import rfc8785
import sqlalchemy as sa
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from sqlalchemy.ext.asyncio import AsyncConnection

from hirz import db
from hirz.pipeline.hashing import timestamp, wire
from hirz.pipeline.models import Decision, EventType


class PipelineError(RuntimeError):
    """Safe fail-closed error: no committed authorization is returned."""


class AuditWriter:
    def __init__(self, key: ec.EllipticCurvePrivateKey):
        if not isinstance(key.curve, ec.SECP256R1):
            raise PipelineError("Audit signing requires P-256")
        self.key = key
        self.fingerprint = hashlib.sha256(
            key.public_key().public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        ).hexdigest()

    async def append(
        self,
        connection: AsyncConnection,
        household_id: UUID,
        at: datetime,
        event: EventType,
        payload: dict[str, Any] | Decision,
    ) -> int:
        return (
            await self.append_many(connection, household_id, ((at, event, payload),))
        )[0]

    async def append_many(
        self,
        connection: AsyncConnection,
        household_id: UUID,
        events: tuple[tuple[datetime, EventType, dict[str, Any] | Decision], ...],
    ) -> tuple[int, ...]:
        """Sign every row in order; amortize SQL under the same household lock."""
        if not events:
            return ()
        at = events[0][0]
        # The caller already owns the graph transaction lock, before this row lock.
        pointer = (
            sa.select(db.audit_pointer)
            .where(db.audit_pointer.c.household_id == household_id)
            .with_for_update()
            .cte("locked_pointer")
        )
        head = (
            sa.select(
                db.audit_log.c.seq,
                db.audit_log.c.curr_hash,
                db.audit_log.c.key_fingerprint,
                db.audit_log.c.created_at,
            )
            .where(db.audit_log.c.household_id == household_id)
            .order_by(db.audit_log.c.seq.desc())
            .limit(1)
            .cte("audit_head")
        )
        # The singleton retains missing-pointer/head cases. Lock inside the CTE,
        # not the nullable outer join; the caller already holds the household lock.
        state = (
            (
                await connection.execute(
                    sa.select(
                        pointer.c.seq.label("pointer_seq"),
                        pointer.c.curr_hash.label("pointer_hash"),
                        head,
                    ).select_from(
                        sa.select(sa.literal(1))
                        .subquery()
                        .outerjoin(pointer, sa.true())
                        .outerjoin(head, sa.true())
                    )
                )
            )
            .mappings()
            .one()
        )
        if state["pointer_seq"] is None:
            if state["seq"] is not None:
                raise PipelineError("Invalid audit pointer")
            await connection.execute(
                db.audit_pointer.insert().values(household_id=household_id)
            )
            seq, previous = 1, "0" * 64
        else:
            seq, previous = state["pointer_seq"] + 1, state["pointer_hash"]
            if (state["seq"] is None and (seq != 1 or previous != "0" * 64)) or (
                state["seq"] is not None
                and (
                    state["seq"] != seq - 1
                    or state["curr_hash"] != previous
                    or state["key_fingerprint"] != self.fingerprint
                    or state["created_at"] > at
                )
            ):
                raise PipelineError("Invalid audit pointer or incompatible signing key")
        rows = []
        sequences = []
        previous_at = at
        for at, event, payload in events:
            if at < previous_at:
                raise PipelineError("Audit batch timestamps must be ordered")
            if isinstance(payload, Decision):
                payload = payload.model_copy(update={"audit_id": seq}).model_dump(
                    mode="json", by_alias=True
                )
            envelope = dict(
                household_id=str(household_id),
                seq=seq,
                event_type=event.value,
                payload=wire(payload),
                prev_hash=previous,
                key_fingerprint=self.fingerprint,
                created_at=timestamp(at),
            )
            # Payload is already normalized above; avoid a second recursive walk.
            try:
                current = hashlib.sha256(rfc8785.dumps(envelope)).hexdigest()
            except (ValueError, TypeError):
                raise ValueError("Invalid canonical data") from None
            signature = self.key.sign(
                bytes.fromhex(current), ec.ECDSA(utils.Prehashed(hashes.SHA256()))
            )
            rows.append(
                envelope
                | {
                    "household_id": household_id,
                    "created_at": at,
                    "curr_hash": current,
                    "signature": signature,
                }
            )
            sequences.append(seq)
            seq, previous, previous_at = seq + 1, current, at
        await connection.execute(db.audit_log.insert(), rows)
        await connection.execute(
            db.audit_pointer.update()
            .where(db.audit_pointer.c.household_id == household_id)
            .values(seq=sequences[-1], curr_hash=previous)
        )
        return tuple(sequences)
