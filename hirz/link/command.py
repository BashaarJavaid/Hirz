"""Canonical Actions signed for one home, with no worker-supplied hash authority."""

import base64
from datetime import datetime, timedelta
from typing import Any, Literal, Protocol, Self
from uuid import UUID, uuid4

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils
from pydantic import AwareDatetime, Field, model_validator

from hirz.audit import fingerprint as key_fingerprint
from hirz.executor.contracts import SUPPORTED, expired, validate
from hirz.graph.models import utc
from hirz.pipeline.hashing import digest
from hirz.pipeline.models import Action, Model


class Rejected(ValueError):
    """A safe reason code, never an untrusted command or a credential."""


class Command(Model):
    version: Literal[1] = 1
    home_id: UUID
    action: Action
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    nonce: UUID

    @model_validator(mode="after")
    def contract(self) -> Self:
        action = validate(self.action)
        if SUPPORTED[action.action_class][0] != "devices" or not timedelta(
            0
        ) < self.expires_at - self.issued_at <= timedelta(seconds=60):
            raise ValueError("Invalid signed command contract")
        return self


class Envelope(Model):
    command: Command
    signature: str = Field(min_length=1, max_length=128)


def message(command: Command) -> bytes:
    # Revalidate even model_copy/model_construct instances at this trust boundary.
    command = Command.model_validate(command.model_dump(by_alias=True))
    return bytes.fromhex(digest(command.model_dump(mode="json", by_alias=True)))


def fingerprint(key: ec.EllipticCurvePublicKey) -> str:
    if not isinstance(key.curve, ec.SECP256R1):
        raise ValueError("Link requires a pinned P-256 public key")
    return key_fingerprint(key)


class Signer(Protocol):
    def sign(self, value: bytes) -> bytes: ...


class DevelopmentSigner:
    """An explicitly supplied local test key; never selected as an AWS fallback."""

    def __init__(self, key: ec.EllipticCurvePrivateKey):
        fingerprint(key.public_key())
        self.key = key

    def sign(self, value: bytes) -> bytes:
        return self.key.sign(value, ec.ECDSA(utils.Prehashed(hashes.SHA256())))


class KMSSigner:
    def __init__(self, sdk: Any, key_arn: str):
        if not key_arn.startswith("arn:aws:kms:") or ":key/" not in key_arn:
            raise ValueError("Configure the exact KMS signing key ARN")
        self.sdk, self.key_arn = sdk, key_arn

    def sign(self, value: bytes) -> bytes:
        if len(value) != 32:
            raise ValueError("Expected a SHA-256 command digest")
        # https://docs.aws.amazon.com/kms/latest/APIReference/API_Sign.html
        response = self.sdk.sign(
            KeyId=self.key_arn,
            Message=value,
            MessageType="DIGEST",
            SigningAlgorithm="ECDSA_SHA_256",
        )
        if (
            response.get("KeyId") != self.key_arn
            or response.get("SigningAlgorithm") != "ECDSA_SHA_256"
            or not isinstance(response.get("Signature"), bytes)
        ):
            raise ValueError("Unexpected KMS signature response")
        return response["Signature"]  # type: ignore[no-any-return]


def sign(
    action: Action,
    *,
    home_id: UUID,
    approved_hash: str,
    at: datetime,
    signer: Signer,
) -> Envelope:
    action = validate(action)
    if action.content_hash != approved_hash:
        raise Rejected("hash_mismatch")
    at = utc(at)
    command = Command(
        home_id=home_id,
        action=action,
        issued_at=at,
        expires_at=at + timedelta(seconds=60),
        nonce=uuid4(),
    )
    return Envelope(
        command=command,
        signature=base64.b64encode(signer.sign(message(command))).decode("ascii"),
    )


def authenticated(value: object, key: ec.EllipticCurvePublicKey) -> Envelope:
    fingerprint(key)
    try:
        envelope = Envelope.model_validate(value)
        key.verify(
            base64.b64decode(envelope.signature, validate=True),
            message(envelope.command),
            ec.ECDSA(utils.Prehashed(hashes.SHA256())),
        )
    except (ValueError, TypeError, InvalidSignature):
        raise Rejected("invalid_signature_or_command") from None
    return envelope


def verify(
    value: object,
    *,
    key: ec.EllipticCurvePublicKey,
    home_id: UUID,
    at: datetime,
) -> Envelope:
    at = utc(at)
    envelope = authenticated(value, key)
    command = envelope.command
    if command.home_id != home_id:
        raise Rejected("wrong_home")
    if not command.issued_at <= at < command.expires_at:
        raise Rejected("expired_or_future_command")
    if expired(command.action, at) or (
        command.action.scheduled_for is not None and command.action.scheduled_for > at
    ):
        raise Rejected("action_not_due_or_expired")
    return envelope
