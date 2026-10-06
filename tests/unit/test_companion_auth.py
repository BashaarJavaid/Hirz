"""A real software authenticator: CBOR registration and P-256 signed assertions."""

import json
import secrets
import struct
from hashlib import sha256

import cbor2
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn import verify_authentication_response, verify_registration_response
from webauthn.helpers import bytes_to_base64url as b64

from hirz.companion.auth import Config, csrf, guard, same_origin_client

CONFIG = Config("https://hirz.example.test", "hirz.example.test")


class Authenticator:
    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.id = secrets.token_bytes(32)
        self.counter = 0

    def response(
        self,
        challenge,
        *,
        register=False,
        origin=CONFIG.origin,
        rp=CONFIG.rp_id,
        uv=True,
        cross=False,
        handle=None,
    ):
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
        result = {"clientDataJSON": b64(client)}
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


def test_real_registration_and_assertion_verification():
    authenticator = Authenticator()
    challenge = secrets.token_bytes(32)
    registration = verify_registration_response(
        credential=authenticator.response(challenge, register=True),
        expected_challenge=challenge,
        expected_rp_id=CONFIG.rp_id,
        expected_origin=CONFIG.origin,
        require_user_verification=True,
    )
    response = authenticator.response(challenge)
    verified = verify_authentication_response(
        credential=response,
        expected_challenge=challenge,
        expected_rp_id=CONFIG.rp_id,
        expected_origin=CONFIG.origin,
        credential_public_key=registration.credential_public_key,
        credential_current_sign_count=registration.sign_count,
        require_user_verification=True,
    )
    assert verified.new_sign_count == 2
    for change in ({"origin": "https://evil.test"}, {"rp": "evil.test"}, {"uv": False}):
        with pytest.raises(Exception):
            verify_authentication_response(
                credential=authenticator.response(challenge, **change),
                expected_challenge=challenge,
                expected_rp_id=CONFIG.rp_id,
                expected_origin=CONFIG.origin,
                credential_public_key=registration.credential_public_key,
                credential_current_sign_count=registration.sign_count,
                require_user_verification=True,
            )
    with pytest.raises(Exception):
        verify_authentication_response(
            credential=response,
            expected_challenge=b"wrong",
            expected_rp_id=CONFIG.rp_id,
            expected_origin=CONFIG.origin,
            credential_public_key=registration.credential_public_key,
            credential_current_sign_count=registration.sign_count,
            require_user_verification=True,
        )
    response["response"]["signature"] = b64(bytes(64))
    with pytest.raises(Exception):
        verify_authentication_response(
            credential=response,
            expected_challenge=challenge,
            expected_rp_id=CONFIG.rp_id,
            expected_origin=CONFIG.origin,
            credential_public_key=registration.credential_public_key,
            credential_current_sign_count=registration.sign_count,
            require_user_verification=True,
        )


def test_origin_csrf_and_cross_origin_guards():
    guard(CONFIG, CONFIG.origin, "session", csrf("session"))
    for origin, token in (
        ("https://evil.test", csrf("session")),
        (CONFIG.origin, "forged"),
        (None, None),
    ):
        with pytest.raises(ValueError):
            guard(CONFIG, origin, "session", token)
    with pytest.raises(ValueError):
        same_origin_client(Authenticator().response(b"test", cross=True))
    for origin in (
        "http://hirz.example.test",
        "https://hirz.example.test/",
        "https://evil.test",
        "https://hirz.example.test:443",
    ):
        with pytest.raises(ValueError):
            Config(origin, CONFIG.rp_id)
