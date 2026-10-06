"""Read-only audit verification and selected-range exports."""

import base64
import hashlib
import json
import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, NoReturn
from uuid import UUID

import sqlalchemy as sa
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncConnection

from hirz import db
from hirz.pipeline.hashing import digest, timestamp
from hirz.pipeline.models import AuditEvent

ZERO = "0" * 64
LIMITATION = (
    "not anchored: local mode; omitted history, later rows, and completeness "
    "are not proven; tail truncation, complete erasure, and a re-signed rewrite "
    "cannot be excluded"
)


class AuditError(ValueError):
    """Only fixed, safe diagnostics; never a payload or upstream exception."""

    def __init__(self, reason: str, result: dict[str, Any] | None = None):
        super().__init__(reason)
        self.result = result or {}


def fingerprint(key: ec.EllipticCurvePublicKey) -> str:
    return hashlib.sha256(
        key.public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    ).hexdigest()


def public_pem(key: ec.EllipticCurvePublicKey) -> str:
    return key.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode("ascii")


def public_key(pem: str) -> ec.EllipticCurvePublicKey:
    try:
        key = serialization.load_pem_public_key(pem.encode("ascii"))
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(
            key.curve, ec.SECP256R1
        ):
            raise ValueError
        return key
    except (ValueError, TypeError):
        raise AuditError("Expected a PEM P-256 public key") from None


def event_json(row: AuditEvent) -> dict[str, Any]:
    data = row.model_dump(mode="python")
    data.update(
        household_id=str(row.household_id),
        created_at=timestamp(row.created_at),
        signature=base64.b64encode(row.signature).decode("ascii"),
    )
    return data


def decode_event(data: dict[str, Any]) -> dict[str, Any]:
    """Decode transport fields only; never coerce signed JSON payload values."""
    try:
        if any(
            type(data.get(k)) is not str
            for k in ("household_id", "created_at", "signature")
        ):
            raise ValueError
        result = dict(data)
        result["household_id"] = UUID(data["household_id"])
        result["created_at"] = datetime.fromisoformat(data["created_at"])
        result["signature"] = base64.b64decode(data["signature"], validate=True)
        if (
            str(result["household_id"]) != data["household_id"]
            or timestamp(result["created_at"]) != data["created_at"]
            or base64.b64encode(result["signature"]).decode("ascii")
            != data["signature"]
        ):
            raise ValueError
        return result
    except (ValueError, TypeError):
        raise AuditError("Malformed audit row encoding") from None


class Verification:
    """One streaming checker shared by database and offline verification."""

    def __init__(self, household: UUID, key: ec.EllipticCurvePublicKey):
        if not isinstance(key.curve, ec.SECP256R1):
            raise AuditError("Expected a P-256 public key")
        self.household, self.key = household, key
        self.fingerprint = fingerprint(key)
        self.count = 0
        self.first: int | None = None
        self.last: AuditEvent | None = None

    def summary(self) -> dict[str, Any]:
        return dict(
            status="valid" if self.count else "empty",
            household_id=str(self.household),
            start_seq=self.first,
            end_seq=self.last.seq if self.last else None,
            checked_count=self.count,
            key_fingerprint=self.fingerprint,
            failure_seq=None,
            reason=None,
            anchoring=LIMITATION,
        )

    def fail(self, reason: str, seq: int | None = None) -> NoReturn:
        raise AuditError(
            reason, self.summary() | dict(status="invalid", failure_seq=seq)
        )

    def feed(self, data: Mapping[str, Any]) -> AuditEvent:
        seq = data.get("seq")
        location = seq if type(seq) is int and seq > 0 else None
        try:
            row = AuditEvent.model_validate(dict(data))
        except ValidationError:
            self.fail("Malformed audit row", location)
        if row.household_id != self.household:
            self.fail("Household mismatch", row.seq)
        if self.last and row.seq != self.last.seq + 1:
            self.fail("Noncontiguous sequence", row.seq)
        if (row.seq == 1 and row.prev_hash != ZERO) or (
            self.last and row.prev_hash != self.last.curr_hash
        ):
            self.fail("Previous hash mismatch", row.seq)
        if self.last and row.created_at < self.last.created_at:
            self.fail("Creation time moved backwards", row.seq)
        if row.key_fingerprint != self.fingerprint:
            self.fail("Untrusted key fingerprint", row.seq)
        envelope = row.model_dump(exclude={"signature", "curr_hash"})
        envelope["household_id"] = str(row.household_id)
        try:
            current = digest(envelope)
        except ValueError:
            self.fail("Invalid canonical data", row.seq)
        if current != row.curr_hash:
            self.fail("Envelope hash mismatch", row.seq)
        try:
            self.key.verify(
                row.signature,
                bytes.fromhex(current),
                ec.ECDSA(utils.Prehashed(hashes.SHA256())),
            )
        except (InvalidSignature, ValueError):
            self.fail("Invalid signature", row.seq)
        self.first = row.seq if self.first is None else self.first
        self.last = row
        self.count += 1
        return row


class Export(BaseModel):
    """Unsigned transport wrapper, not a signed completeness assertion."""

    model_config = ConfigDict(extra="forbid", strict=True)
    format_version: int = Field(ge=1, le=1)
    household_id: str
    start_seq: int | None = Field(gt=0)
    end_seq: int | None = Field(gt=0)
    public_key: str
    rows: list[dict[str, Any]]


def export_document(
    household: UUID, key: ec.EllipticCurvePublicKey, rows: list[AuditEvent]
) -> dict[str, Any]:
    return dict(
        format_version=1,
        household_id=str(household),
        start_seq=rows[0].seq if rows else None,
        end_seq=rows[-1].seq if rows else None,
        public_key=public_pem(key),
        rows=[event_json(row) for row in rows],
    )


async def verify_database(
    connection: AsyncConnection,
    household: UUID,
    key: ec.EllipticCurvePublicKey,
    *,
    collect: bool = False,
    selected: tuple[int, int] | None = None,
) -> tuple[dict[str, Any], list[AuditEvent]]:
    """Own one read-only snapshot; verify the whole chain even for range exports."""
    check = Verification(household, key)
    rows: list[AuditEvent] = []
    if connection.in_transaction():
        raise AuditError("Audit verification requires an idle connection")
    async with connection.begin():
        # PostgreSQL 16 transaction-iso.html#XACT-REPEATABLE-READ: one stable snapshot.
        await connection.exec_driver_sql(
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
        )
        if not await connection.scalar(
            sa.select(sa.exists().where(db.households.c.id == household))
        ):
            check.fail("Unknown household")
        pointer = (
            (
                await connection.execute(
                    sa.select(db.audit_pointer).where(
                        db.audit_pointer.c.household_id == household
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        async with connection.stream(
            sa.select(db.audit_log)
            .where(db.audit_log.c.household_id == household)
            .order_by(db.audit_log.c.seq)
        ) as result:
            async for data in result.mappings():
                if check.last is None and data["seq"] != 1:
                    check.fail("Missing genesis", data["seq"])
                row = check.feed(dict(data))
                if collect and (
                    selected is None or selected[0] <= row.seq <= selected[1]
                ):
                    # ponytail: selected range occupies memory; stream JSON if exports outgrow RAM.
                    rows.append(row)
        head_seq = check.last.seq if check.last else 0
        head_hash = check.last.curr_hash if check.last else ZERO
        if (pointer is None and check.count) or (
            pointer is not None
            and (pointer["seq"] != head_seq or pointer["curr_hash"] != head_hash)
        ):
            check.fail("Audit pointer mismatch")
        if selected is not None and not (1 <= selected[0] <= selected[1] <= head_seq):
            check.fail("Range must lie within the verified chain")
    return check.summary(), rows


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AuditError("Duplicate JSON key")
        result[key] = value
    return result


def invalid_constant(value: str) -> None:
    raise AuditError("Nonfinite JSON number")


def verify_file(
    path: Path,
    household: UUID,
    *,
    key: ec.EllipticCurvePublicKey | None = None,
    trusted_fingerprint: str | None = None,
) -> dict[str, Any]:
    if (key is None) == (trusted_fingerprint is None):
        raise AuditError("Supply exactly one trusted public key or fingerprint")
    try:
        document = Export.model_validate(
            json.loads(
                path.read_text(encoding="utf-8"),
                object_pairs_hook=unique_object,
                parse_constant=invalid_constant,
            )
        )
    except (ValueError, TypeError) as exc:
        if isinstance(exc, AuditError):
            raise
        raise AuditError("Malformed or unsupported audit export") from None
    embedded = public_key(document.public_key)
    expected = fingerprint(key) if key is not None else trusted_fingerprint
    check = Verification(household, embedded)
    if check.fingerprint != expected:
        check.fail("Untrusted export public key")
    if document.household_id != str(household):
        check.fail("Household mismatch")
    for data in document.rows:
        try:
            decoded = decode_event(data)
        except AuditError as exc:
            seq = data.get("seq")
            check.fail(str(exc), seq if type(seq) is int and seq > 0 else None)
        check.feed(decoded)
    if (document.start_seq, document.end_seq) != (
        check.first,
        check.last.seq if check.last else None,
    ):
        check.fail("Export range metadata mismatch")
    return check.summary()


def write_export(path: Path, document: dict[str, Any]) -> None:
    """Exclusive creation: never follow a symlink or overwrite another file."""
    encoded = json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(encoded)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


async def retain_export(
    connection: AsyncConnection,
    household_id: UUID,
    key: ec.EllipticCurvePublicKey,
    folder: Path,
) -> tuple[dict[str, Any], list[Any]]:
    """Retain and independently verify an export without an authorization runtime."""
    summary, rows = await verify_database(connection, household_id, key, collect=True)
    write_export(
        folder / "audit.json",
        export_document(household_id, key, rows),
    )
    fd = os.open(folder / "public-key.pem", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as keyfile:
        keyfile.write(public_pem(key))
    verified = verify_file(
        folder / "audit.json",
        household_id,
        trusted_fingerprint=fingerprint(key),
    )
    if summary["status"] != verified["status"] or verified["status"] not in {
        "valid",
        "empty",
    }:
        raise ValueError("Signed audit verification failed")
    return verified, rows
