"""Software WebAuthn device for disposable scenarios and authentication tests."""

import json
import secrets
import struct
from hashlib import sha256
from typing import Any

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import bytes_to_base64url as b64

from hirz.companion.auth import Config

CONFIG = Config("https://hirz.example.test", "hirz.example.test")


class Authenticator:
    def __init__(self) -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.id = secrets.token_bytes(32)
        self.counter = 0

    def response(
        self,
        challenge: bytes,
        *,
        register: bool = False,
        origin: str = CONFIG.origin,
        rp: str = CONFIG.rp_id,
        uv: bool = True,
        cross: bool = False,
        handle: str | None = None,
    ) -> dict[str, Any]:
        client = json.dumps(
            {
                "type": "webauthn.create" if register else "webauthn.get",
                "challenge": b64(challenge),
                "origin": origin,
                "crossOrigin": cross,
            }
        ).encode()
        self.counter += 1
        data = (
            sha256(rp.encode()).digest()
            + bytes([(0x41 if register else 0x01) | (4 if uv else 0)])
            + struct.pack(">I", self.counter)
        )
        result: dict[str, Any] = {"clientDataJSON": b64(client)}
        if register:
            pub = self.key.public_key().public_numbers()
            cose = cbor2.dumps(
                {1: 2, 3: -7, -1: 1, -2: pub.x.to_bytes(32), -3: pub.y.to_bytes(32)}
            )
            data += bytes(16) + struct.pack(">H", len(self.id)) + self.id + cose
            result["attestationObject"] = b64(
                cbor2.dumps({"fmt": "none", "authData": data, "attStmt": {}})
            )
        else:
            result |= {
                "authenticatorData": b64(data),
                "signature": b64(
                    self.key.sign(
                        data + sha256(client).digest(), ec.ECDSA(hashes.SHA256())
                    )
                ),
                "userHandle": handle,
            }
        return {
            "id": b64(self.id),
            "rawId": b64(self.id),
            "type": "public-key",
            "response": result,
            "clientExtensionResults": {},
        }
