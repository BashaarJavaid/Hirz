import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import bytes_to_base64url

from hirz.companion.push import Config, Subscription


def subscription(endpoint="https://web.push.apple.com/test"):
    key = (
        ec.generate_private_key(ec.SECP256R1())
        .public_key()
        .public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
    )
    return {
        "endpoint": endpoint,
        "keys": {
            "p256dh": bytes_to_base64url(key),
            "auth": bytes_to_base64url(bytes(16)),
        },
    }


def test_push_restricts_destinations_and_validates_keys():
    value = Subscription.model_validate(subscription())
    cipher = Fernet(Fernet.generate_key())
    encrypted = cipher.encrypt(value.model_dump_json().encode())
    assert b"apple" not in encrypted
    assert Subscription.model_validate_json(cipher.decrypt(encrypted)) == value
    for endpoint in (
        "http://web.push.apple.com/test",
        "https://127.0.0.1/test",
        "https://web.push.apple.com.evil.test/test",
        "https://evil.test@web.push.apple.com/test",
        "https://web.push.apple.com:8000/test",
    ):
        with pytest.raises(ValueError):
            Subscription.model_validate(subscription(endpoint))


def config():
    key = ec.generate_private_key(ec.SECP256R1())
    return Config(
        Fernet.generate_key().decode(),
        bytes_to_base64url(key.private_numbers().private_value.to_bytes(32, "big")),
        bytes_to_base64url(
            key.public_key().public_bytes(
                serialization.Encoding.X962,
                serialization.PublicFormat.UncompressedPoint,
            )
        ),
        "mailto:test@example.test",
    )


def test_vapid_configuration_refuses_mismatched_keys():
    from dataclasses import replace

    first, second = config(), config()
    with pytest.raises(ValueError, match="does not match"):
        replace(first, vapid_public_key=second.vapid_public_key)
    with pytest.raises(ValueError):
        replace(first, vapid_private_key="malformed")
