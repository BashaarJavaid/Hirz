"""Contact secrets never enter graph projections, tool results or audit actions."""

import hashlib
import hmac
import json
import os
import re
import secrets
import smtplib
import ssl
import unicodedata
from dataclasses import dataclass
from email.message import EmailMessage
from urllib.parse import urlsplit

from cryptography.fernet import Fernet

SENDER = "bashaar.230102@gmail.com"
SCRYPT = {"n": 131072, "r": 8, "p": 1, "dklen": 32}


def email(value: str) -> str:
    # Reject controls before trimming so header injection is never normalized away.
    if not value.isascii() or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Provide one ASCII email address")
    value = value.strip()
    if len(value) > 254 or value.count("@") != 1:
        raise ValueError("Provide one ASCII email address")
    local, domain = value.split("@")
    if (
        not 1 <= len(local) <= 64
        or not re.fullmatch(r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+", local)
        or local.startswith(".")
        or local.endswith(".")
        or ".." in local
        or not re.fullmatch(
            r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
            r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+",
            domain,
        )
    ):
        raise ValueError("Provide one ASCII email address")
    return local + "@" + domain.lower()


def word(value: str) -> str:
    value = unicodedata.normalize("NFC", value).strip()
    if not 8 <= len(value) <= 128:
        raise ValueError("The safe word must have 8 through 128 characters")
    return value


def hash_word(value: str) -> dict[str, str | int]:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        word(value).encode(), salt=salt, maxmem=256 * 1024 * 1024, **SCRYPT
    )
    return {"algorithm": "scrypt", **SCRYPT, "salt": salt.hex(), "hash": derived.hex()}


def check_word(value: str, stored: dict[str, str | int] | str) -> bool:
    if (
        not isinstance(stored, dict)
        or stored.get("algorithm") != "scrypt"
        or any(stored.get(k) != v for k, v in SCRYPT.items())
    ):
        raise ValueError("Ask the owner to reset this safe word")
    salt, expected = (
        bytes.fromhex(str(stored["salt"])),
        bytes.fromhex(str(stored["hash"])),
    )
    if len(salt) != 16 or len(expected) != 32:
        raise ValueError("Ask the owner to reset this safe word")
    actual = hashlib.scrypt(
        word(value).encode(), salt=salt, maxmem=256 * 1024 * 1024, **SCRYPT
    )
    return hmac.compare_digest(actual, expected)


@dataclass(frozen=True)
class Config:
    encryption_key: str
    origin: str
    password: str = ""

    def __post_init__(self) -> None:
        Fernet(self.encryption_key.encode())
        parsed = urlsplit(self.origin)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.netloc != parsed.hostname
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Contact links require the configured HTTPS origin")

    @classmethod
    def environment(cls) -> "Config | None":
        key = os.environ.get("HIRZ_CONTACT_ENCRYPTION_KEY")
        if not key:
            return None
        return cls(
            key,
            os.environ.get("HIRZ_COMPANION_ORIGIN", ""),
            os.environ.get("HIRZ_CONTACT_SMTP_PASSWORD", ""),
        )

    def seal(self, value: dict[str, str]) -> bytes:
        return Fernet(self.encryption_key.encode()).encrypt(json.dumps(value).encode())

    def open(self, value: bytes) -> dict[str, str]:
        result = json.loads(Fernet(self.encryption_key.encode()).decrypt(value))
        if not isinstance(result, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in result.items()
        ):
            raise ValueError("Invalid contact secret")
        return result

    def binding(self, value: str) -> str:
        # A keyed binding prevents the ceremony record becoming a cheap word oracle.
        return hmac.new(
            self.encryption_key.encode(), value.encode(), "sha256"
        ).hexdigest()

    def link(self, token: str) -> str:
        return self.origin + "/contact-links#" + token


def send_email(config: Config, destination: str, token: str) -> None:
    """Worker calls through asyncio.to_thread, outside every DB transaction."""
    if not config.password:
        raise ValueError("Contact email is not configured")
    message = EmailMessage()
    message["From"] = SENDER
    message["To"] = email(destination)
    message["Subject"] = "A private request in Hirz"
    message.set_content(
        "Open this private Hirz link to review a request. Opening it does not confirm "
        "anything.\n\n" + config.link(token) + "\n"
    )
    # https://docs.python.org/3.12/library/smtplib.html#smtplib.SMTP.starttls
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=10) as smtp:
        smtp.ehlo()
        smtp.starttls(context=ssl.create_default_context())
        smtp.ehlo()
        smtp.login(SENDER, config.password)
        smtp.send_message(message)
