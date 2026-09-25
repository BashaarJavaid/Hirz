"""Explicit initialization and serving of the loopback simulated OAuth issuer."""

import argparse
import os
from pathlib import Path

import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from dotenv import dotenv_values, set_key

from hirz.local import LocalError, read_env
from hirz.mcp.dev_oauth import KEY_NAME, DevProvider, create_issuer, signing_key


def initialize(path: Path) -> None:
    values = read_env(path)
    # A present but empty/malformed entry is not permission to replace a key.
    if path.exists() and KEY_NAME in dotenv_values(path, interpolate=False):
        signing_key(values)
        return
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    if not path.exists():
        with open(path, "x", opener=lambda p, f: os.open(p, f, 0o600)):
            pass
    set_key(path, KEY_NAME, pem)
    path.chmod(0o600)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "serve"))
    args = parser.parse_args()
    try:
        if args.command == "init":
            initialize(Path(".env"))
            print("Dev OAuth RSA key ready; existing entries preserved.")
        else:
            provider = DevProvider(signing_key(read_env(Path(".env"))))
            uvicorn.run(
                create_issuer(provider), host="127.0.0.1", port=8001, access_log=False
            )
    except LocalError as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
