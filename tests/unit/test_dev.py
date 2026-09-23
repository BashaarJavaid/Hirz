"""Bootstrap protocol and credential handling without Docker or physical devices."""

import asyncio
import json
import secrets
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from websockets.asyncio.server import ServerConnection, serve

from hirz.api.app import app
from scripts import init_dev as dev


@pytest.fixture
def env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / ".env"
    monkeypatch.setattr(dev, "ENV_FILE", path)
    return path


def test_liveness_has_no_application_or_docs_routes() -> None:
    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost:8000"
        ) as client:
            response = await client.get("/health")
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}
            for path in ("/ready", "/docs", "/redoc", "/openapi.json"):
                assert (await client.get(path)).status_code == 404

    asyncio.run(run())


def test_env_creation_and_rerun_preserve_credentials(env_file: Path) -> None:
    first = dev.prepare_env(set())
    assert first["HA_USERNAME"] == "hirz"
    assert len(first["POSTGRES_PASSWORD"]) >= 43
    assert first["POSTGRES_PASSWORD"] != first["HA_PASSWORD"]
    with env_file.open("a") as file:
        file.write("# user setting\nUNRELATED='keep ${THIS_LITERAL}'\n")
    before = env_file.read_bytes()
    second = dev.prepare_env({"postgres", "homeassistant"})
    assert all(second[key] == value for key, value in first.items())
    assert env_file.read_bytes() == before
    assert second["UNRELATED"] == "keep ${THIS_LITERAL}"
    assert env_file.stat().st_mode & 0o777 == 0o600


def test_env_missing_credentials_never_reinitialize_existing_state(
    env_file: Path,
) -> None:
    with pytest.raises(dev.DevError, match="restore the original .env"):
        dev.prepare_env({"postgres"})
    assert not env_file.exists()


def test_env_refuses_symlink(env_file: Path) -> None:
    target = env_file.parent / "private"
    target.write_text("unchanged")
    env_file.symlink_to(target)
    with pytest.raises(dev.DevError, match="symlink"):
        dev.prepare_env(set())
    assert target.read_text() == "unchanged"


def states() -> list[dict[str, str]]:
    return [{"entity_id": entity, "state": "off"} for entity in dev.DEMO_ENTITIES]


def test_fresh_onboarding_and_token_reuse(
    env_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    values = dev.prepare_env(set())
    access, refresh, token = (secrets.token_urlsafe() for _ in range(3))
    mint = AsyncMock(return_value=token)
    monkeypatch.setattr(dev, "long_lived_token", mint)
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        paths.append(path)
        if path == "/api/onboarding":
            return httpx.Response(200, json=[{"step": "user", "done": False}])
        if path == "/api/onboarding/users":
            body = json.loads(request.content)
            assert body["password"] == values["HA_PASSWORD"]
            assert body["client_id"] == dev.HA_URL + "/"
            return httpx.Response(200, json={"auth_code": "one-use-test-code"})
        if path == "/auth/token":
            return httpx.Response(
                200, json={"access_token": access, "refresh_token": refresh}
            )
        if path.startswith("/api/onboarding/"):
            assert request.headers["Authorization"] == f"Bearer {access}"
            return httpx.Response(200, json={})
        if path == "/auth/revoke":
            assert refresh.encode() in request.content
            return httpx.Response(200)
        assert path == "/api/states"
        assert request.headers["Authorization"] == f"Bearer {token}"
        return httpx.Response(200, json=states())

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await dev.provision(client, values)
            assert paths == [
                "/api/onboarding",
                "/api/onboarding/users",
                "/auth/token",
                "/api/onboarding/core_config",
                "/api/onboarding/analytics",
                "/api/onboarding/integration",
                "/auth/revoke",
                "/api/states",
            ]
            assert dev.read_env()["HA_TOKEN"] == token
            paths.clear()
            await dev.provision(client, dev.read_env())
            assert paths == ["/api/states"]

    asyncio.run(run())
    mint.assert_awaited_once_with(access)
    output = capsys.readouterr()
    assert all(
        secret not in output.out + output.err
        for secret in (
            access,
            refresh,
            token,
            values["HA_PASSWORD"],
            values["POSTGRES_PASSWORD"],
        )
    )
    assert env_file.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "status,body",
    [
        (404, {}),
        (200, [{"step": "user", "done": True}]),
    ],
)
def test_onboarded_without_token_stops(
    env_file: Path, status: int, body: object
) -> None:
    values = dev.prepare_env(set())
    before = env_file.read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(status, json=body)

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(dev.DevError, match="already onboarded"):
                await dev.provision(client, values)

    asyncio.run(run())
    assert env_file.read_bytes() == before


@pytest.mark.parametrize(
    "status,body,message",
    [
        (401, {}, "already onboarded"),
        (200, {"error": "not states"}, "malformed entity"),
        (200, [{"entity_id": 42}], "malformed entity"),
        (503, {}, "HTTP 503"),
    ],
)
def test_invalid_ha_reads_fail(status: int, body: object, message: str) -> None:
    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(status, json=body)
            )
        ) as client:
            with pytest.raises(dev.DevError, match=message):
                await dev.demo_entities(client, secrets.token_urlsafe())

    asyncio.run(run())


def test_readiness_timeout_and_late_entities(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dev, "DEADLINE", 0.03)
    monkeypatch.setattr(dev, "POLL", 0.001)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=[] if calls == 1 else states())

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert len(await dev.demo_entities(client, "test-only")) == len(
                dev.DEMO_ENTITIES
            )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(503))
        ) as client:
            with pytest.raises(TimeoutError):
                await dev.wait_http(client)
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
        ) as client:
            with pytest.raises(TimeoutError):
                await dev.demo_entities(client, "test-only")

    asyncio.run(run())


def test_onboarding_redirect_is_ready() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(302, headers={"Location": "/onboarding.html"})
        assert request.url.path == "/onboarding.html"
        return httpx.Response(200)

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await dev.wait_http(client)

    asyncio.run(run())


def test_system_sensor_does_not_satisfy_demo_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dev, "DEADLINE", 0.02)
    monkeypatch.setattr(dev, "POLL", 0.001)
    rows = [row for row in states() if not row["entity_id"].startswith("sensor.")]
    rows.append({"entity_id": "sensor.backup_backup_manager_state", "state": "idle"})

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=rows)
            )
        ) as client:
            with pytest.raises(TimeoutError):
                await dev.demo_entities(client, "test-only")

    asyncio.run(run())


def test_malformed_auth_responses_do_not_echo_payloads() -> None:
    secret = secrets.token_urlsafe()
    for data in ({"error": secret}, [], {"access_token": 42}):
        with pytest.raises(dev.DevError) as error:
            dev.string_field(data, "access_token")
        assert secret not in str(error.value)
    with pytest.raises(dev.DevError, match="malformed JSON"):
        dev.response_json(httpx.Response(200, text=secret))


def test_postgres_check_uses_password_without_argv_disclosure(
    env_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    password = dev.prepare_env(set())["POSTGRES_PASSWORD"]
    command = AsyncMock(return_value="1\n")
    monkeypatch.setattr(dev, "compose", command)
    asyncio.run(dev.check_postgres())
    assert password not in " ".join(command.call_args.args)
    assert command.call_args.kwargs["stdin"] == (password + "\n").encode()
    command.side_effect = dev.DevError("upstream details must not be echoed")
    with pytest.raises(
        dev.DevError, match="restore the original POSTGRES_PASSWORD"
    ) as error:
        asyncio.run(dev.check_postgres())
    assert "upstream" not in str(error.value)


@pytest.mark.parametrize("accepted", [True, False])
def test_websocket_token_contract(
    monkeypatch: pytest.MonkeyPatch, accepted: bool
) -> None:
    access, token = (secrets.token_urlsafe() for _ in range(2))

    async def handler(ws: ServerConnection) -> None:
        await ws.send(json.dumps({"type": "auth_required"}))
        assert json.loads(await ws.recv()) == {"type": "auth", "access_token": access}
        await ws.send(json.dumps({"type": "auth_ok" if accepted else "auth_invalid"}))
        if accepted:
            assert json.loads(await ws.recv()) == {
                "id": 1,
                "type": "auth/long_lived_access_token",
                "client_name": "Hirz local development",
                "lifespan": 365,
            }
            await ws.send(
                json.dumps(
                    {"id": 1, "type": "result", "success": True, "result": token}
                )
            )

    async def run() -> None:
        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            monkeypatch.setattr(dev, "HA_URL", f"http://127.0.0.1:{port}")
            if accepted:
                assert await dev.long_lived_token(access) == token
            else:
                with pytest.raises(dev.DevError, match="authentication failed"):
                    await dev.long_lived_token(access)

    asyncio.run(run())
