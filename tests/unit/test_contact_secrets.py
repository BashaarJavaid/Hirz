"""Secret normalization, slow hashing and mandatory verified SMTP transport."""

from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from hirz.contacts.secrets import (
    SCRYPT,
    Config,
    check_word,
    email,
    hash_word,
    send_email,
)


def test_contact_secret_boundaries():
    assert email(" A.B+Tag@EXAMPLE.COM ") == "A.B+Tag@example.com"
    for value in (
        "Name <a@example.com>",
        "a@example.com,b@example.com",
        "a@éxample.com",
        "a@example.com\n",
        "a..b@example.com",
        "a@-example.com",
        "a@example.com\x7f",
    ):
        with pytest.raises(ValueError):
            email(value)
    stored = hash_word("  CaféSecret  ")
    assert all(stored[k] == v for k, v in SCRYPT.items())
    assert check_word("Cafe\u0301Secret", stored)
    assert not check_word("caféSecret", stored)
    assert hash_word("CaféSecret") != stored
    with pytest.raises(ValueError, match="reset"):
        check_word("CaféSecret", "0" * 64)
    for value in ("short", "x" * 129):
        with pytest.raises(ValueError):
            hash_word(value)
    key = Fernet.generate_key().decode()
    config = Config(key, "https://home.example", "private-app-password")
    secret = {"destination": "A.B+Tag@example.com", "token": "example-capability"}
    sealed = config.seal(secret)
    assert all(v.encode() not in sealed for v in secret.values())
    assert config.open(sealed) == secret
    assert config.binding("CaféSecret") != config.binding("caféSecret")
    assert config.link("opaque") == "https://home.example/contact-links#opaque"
    with pytest.raises(ValueError):
        Config("malformed", "https://home.example")
    with pytest.raises(ValueError):
        Config(key, "http://home.example")
    transport = MagicMock()
    with patch("hirz.contacts.secrets.smtplib.SMTP", return_value=transport) as smtp:
        send_email(config, secret["destination"], secret["token"])
    smtp.assert_called_once_with("smtp.gmail.com", 587, timeout=10)
    client = transport.__enter__.return_value
    names = [v[0] for v in client.method_calls]
    assert names == ["ehlo", "starttls", "ehlo", "login", "send_message"]
    context = client.starttls.call_args.kwargs["context"]
    assert context.check_hostname and context.verify_mode.name == "CERT_REQUIRED"
    assert "CaféSecret" not in client.send_message.call_args.args[0].as_string()
    client.starttls.side_effect = RuntimeError("No TLS")
    client.reset_mock()
    with (
        patch("hirz.contacts.secrets.smtplib.SMTP", return_value=transport),
        pytest.raises(RuntimeError),
    ):
        send_email(config, secret["destination"], secret["token"])
    client.login.assert_not_called()
    client.send_message.assert_not_called()
