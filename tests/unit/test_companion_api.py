"""HTTP trust boundary rejects identity fields and cross-origin requests."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock

import pytest
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


def test_account_verifier_lives_with_companion(monkeypatch):
    from hirz.api.app import create_app

    state = []

    @asynccontextmanager
    async def run():
        state.append("started")
        try:
            yield
        finally:
            state.append("stopped")

    @asynccontextmanager
    async def boundary():
        yield

    verifier = Mock()
    verifier.run = run
    service = Companion(
        Mock(),
        Mock(),
        CONFIG,
        account_verifier=verifier,
        account_login_origin="https://login.example.test",
    )
    monkeypatch.setattr(service.boundary, "persistent", boundary)
    with TestClient(create_app(companion=service)) as client:
        assert client.get("/health").status_code == 200
        callback = client.get("/account-link")
        assert callback.status_code == 200
        assert (
            "connect-src 'self' https://login.example.test;"
            in callback.headers["content-security-policy"]
        )
        assert callback.headers["referrer-policy"] == "no-referrer"
        assert state == ["started"]
    assert state == ["started", "stopped"]


@pytest.mark.parametrize(
    "origin",
    [
        "http://login.example.test",
        "https://login.example.test/path",
        "https://login.example.test; script-src unsafe-inline",
        "https://user@login.example.test",
    ],
)
def test_account_login_origin_cannot_expand_browser_policy(origin):
    with pytest.raises(ValueError, match="HTTPS issuer"):
        Companion(
            Mock(), Mock(), CONFIG, account_verifier=Mock(), account_login_origin=origin
        )
