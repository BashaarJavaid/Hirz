"""HTTP trust boundary rejects identity fields and cross-origin requests."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from hirz.companion.api import Companion, router
from tests.unit.test_companion_auth import CONFIG


def test_recorded_patch_reports_changed_base(monkeypatch):
    from hirz.companion import policy
    from hirz.constitution.schema import dump
    from tests.unit.test_companion_drafting import POLICY

    service = Companion(Mock(), Mock(), CONFIG)
    service.demo_world = Mock()

    @asynccontextmanager
    async def authorized(request):
        yield Mock(), {}

    monkeypatch.setattr(service, "authorized", authorized)
    monkeypatch.setattr(
        policy,
        "current",
        AsyncMock(
            return_value={"yaml": dump(POLICY.model_copy(update={"version": 8}))}
        ),
    )
    app = FastAPI()
    app.include_router(router(service))
    with TestClient(app, base_url=CONFIG.origin) as client:
        response = client.post(
            "/api/constitution/recorded-draft",
            json={"sentence": "Never unlock for an unexpected visitor"},
        )
    assert response.status_code == 409
    assert "your household is on version 8" in response.json()["detail"]


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
