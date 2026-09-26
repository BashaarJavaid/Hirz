"""Explicit local HTTPS identity and push-key initialization; never resets an account."""

import argparse
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from dotenv import set_key
from webauthn.helpers import bytes_to_base64url

from hirz.companion.auth import Config
from hirz.companion.push import Config as PushConfig
from hirz.local import read_env


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True)
    args = parser.parse_args()
    config = Config(args.origin, urlsplit(args.origin).hostname or "")
    path = Path(".env")
    values = read_env(
        path
    )  # Existing regular file, mode 0600. Never regenerate audit keys.
    for name, value in (
        ("HIRZ_COMPANION_ORIGIN", config.origin),
        ("HIRZ_COMPANION_RP_ID", config.rp_id),
    ):
        if values.get(name) not in {None, value}:
            raise ValueError(
                "Existing companion identity differs; review the RP change explicitly"
            )
    names = (
        "HIRZ_PUSH_ENCRYPTION_KEY",
        "HIRZ_VAPID_PRIVATE_KEY",
        "HIRZ_VAPID_PUBLIC_KEY",
        "HIRZ_VAPID_SUBJECT",
    )
    existing = [values.get(name) for name in names]
    if any(existing) and not all(existing):
        raise ValueError(
            "Incomplete push keys; restore the existing configuration before initialization"
        )
    if all(existing):
        PushConfig(*(str(value) for value in existing))
    else:
        key = ec.generate_private_key(ec.SECP256R1())
        generated = (
            Fernet.generate_key().decode(),
            bytes_to_base64url(key.private_numbers().private_value.to_bytes(32, "big")),
            bytes_to_base64url(
                key.public_key().public_bytes(
                    serialization.Encoding.X962,
                    serialization.PublicFormat.UncompressedPoint,
                )
            ),
            config.origin,
        )
        for name, value in zip(names, generated, strict=True):
            set_key(path, name, value)
    for name, value in (
        ("HIRZ_COMPANION_ORIGIN", config.origin),
        ("HIRZ_COMPANION_RP_ID", config.rp_id),
    ):
        set_key(path, name, value)
    path.chmod(0o600)
    print(
        "Companion identity and push keys configured in private .env; existing keys preserved; no database changes."
    )


if __name__ == "__main__":
    main()
