"""A real software authenticator: CBOR registration and P-256 signed assertions."""

import secrets

import pytest
from webauthn import verify_authentication_response, verify_registration_response
from webauthn.helpers import bytes_to_base64url as b64

from hirz.companion.auth import Config, csrf, guard, same_origin_client
from hirz.twin.authenticator import CONFIG, Authenticator


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
    assert CONFIG.secure is True
    assert CONFIG.session_cookie == "__Host-hirz-session"
    assert CONFIG.browser_cookie == "__Host-hirz-browser"
    for origin in ("http://localhost:8002", "http://localhost"):
        config = Config(origin, "localhost")
        assert config.secure is False
        assert config.session_cookie == "hirz-session"
        assert config.browser_cookie == "hirz-browser"
    for origin in (
        "http://127.0.0.1:8002",
        "http://localhost.evil.test:8002",
        "http://localhost:8002/",
        "http://localhost:8002?x=1",
    ):
        with pytest.raises(ValueError):
            Config(origin, "localhost")
    with pytest.raises(ValueError):
        Config("http://localhost:8002", "hirz.example.test")
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
