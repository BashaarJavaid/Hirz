"""HTTP trust boundary rejects identity fields and cross-origin requests."""

from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from hirz.companion.api import Companion, router
from tests.unit.test_companion_auth import CONFIG


def test_anonymous_bootstrap_and_forged_authority():
    app = FastAPI()
    app.include_router(router(Companion(Mock(), Mock(), CONFIG)))
    with TestClient(app, base_url=CONFIG.origin) as client:
        response = client.get("/api/auth/session")
        assert response.json() == {"authenticated": False}
        cookie = response.headers["set-cookie"]
        assert (
            "Secure" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie
        )
        assert response.headers["cache-control"] == "no-store"
        assert (
            client.post(
                "/api/auth/begin",
                json={"operation": "login"},
                headers={"origin": "https://evil.test"},
            ).status_code
            == 400
        )
        for authority in (
            {"member_id": "not-a-uuid"},
            {"member_id": "00000000-0000-0000-0000-000000000000"},
            {"passkey_verified": True},
            {"role": "owner"},
            {"household_id": "forged"},
        ):
            assert (
                client.post(
                    "/api/auth/begin",
                    json={"operation": "login", **authority},
                    headers={"origin": CONFIG.origin},
                ).status_code
                == 422
            )
        assert (
            client.post(
                "/api/auth/begin",
                json={"operation": "revoke", "credential_id": "a"},
                headers={"origin": CONFIG.origin},
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/api/auth/logout", headers={"origin": CONFIG.origin}
            ).status_code
            == 403
        )
