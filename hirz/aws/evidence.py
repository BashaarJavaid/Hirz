"""Seal one-off task output to the local acceptance runner, never log invitations."""

import base64
import json
import os
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def seal(document: dict[str, Any], public_pem: str) -> dict[str, str]:
    public = serialization.load_pem_public_key(public_pem.encode())
    if not isinstance(public, rsa.RSAPublicKey) or public.key_size < 2048:
        raise ValueError("Acceptance evidence requires an RSA recipient")
    key, nonce = AESGCM.generate_key(bit_length=256), os.urandom(12)
    wrapped = public.encrypt(
        key,
        padding.OAEP(
            mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None
        ),
    )
    data = AESGCM(key).encrypt(
        nonce, json.dumps(document, default=str).encode(), b"hirz-item36"
    )
    return {
        k: base64.b64encode(v).decode()
        for k, v in {"key": wrapped, "nonce": nonce, "data": data}.items()
    }


def unseal(document: dict[str, str], private: rsa.RSAPrivateKey) -> dict[str, Any]:
    key = private.decrypt(
        base64.b64decode(document["key"], validate=True),
        padding.OAEP(
            mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None
        ),
    )
    return dict(
        json.loads(
            AESGCM(key).decrypt(
                base64.b64decode(document["nonce"], validate=True),
                base64.b64decode(document["data"], validate=True),
                b"hirz-item36",
            )
        )
    )
