"""Explicitly initialize the separate contact encryption key; no database changes."""

from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import set_key

from hirz.local import read_env


def main() -> None:
    path = Path(".env")
    values = read_env(path)
    name = "HIRZ_CONTACT_ENCRYPTION_KEY"
    if name in values:
        Fernet(str(values[name]).encode())  # Refuse malformed or empty existing keys.
    else:
        set_key(path, name, Fernet.generate_key().decode())
    path.chmod(0o600)
    print(
        "Contact encryption key preserved or initialized in private .env; no database changes."
    )


if __name__ == "__main__":
    main()
