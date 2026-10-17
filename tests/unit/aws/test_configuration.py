from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from hirz.aws import config
from hirz.aws.fixture import load
from hirz.aws.lambdas.actions import handler


def test_closed_gateway_has_no_action_path():
    with pytest.raises(RuntimeError, match="Action boundary unavailable"):
        handler({"action": "unlock", "bytes": "sign this"}, None)


def test_verified_tls_separate_role(monkeypatch):
    monkeypatch.setenv("HIRZ_DATABASE_NAME", "hirz_item36")
    monkeypatch.setenv("HIRZ_DATABASE_HOST", "test.us-east-1.rds.amazonaws.com")
    build = Mock()
    monkeypatch.setattr(config, "create_async_engine", build)
    config.database("private")
    url = build.call_args.args[0]
    assert url.username == "hirz" and url.database == "hirz_item36"
    assert build.call_args.kwargs["connect_args"]["sslmode"] == "verify-full"
    assert build.call_args.kwargs["hide_parameters"]
    monkeypatch.setenv("HIRZ_DATABASE_NAME", "production")
    with pytest.raises(ValueError):
        config.database("private")


def test_fixture_is_stable_twin_and_covers_window(monkeypatch):
    monkeypatch.setenv("HIRZ_FIXTURE_START", "2026-10-16T15:00:00+00:00")
    first, second = load(), load()
    assert first.world.config == second.world.config
    assert first.world.config.start == datetime(2026, 10, 16, 15, tzinfo=UTC)
    assert (first.world.config.end - first.world.config.start).total_seconds() == 86400
    assert set(first.spec.adapters.values()) == {"twin"}
    assert first.spec.timeline == ()
    assert first.execution_policy.version == 7


def test_worker_request_evidence_omits_private_paths(monkeypatch, caplog):
    import asyncio
    import logging
    from unittest.mock import AsyncMock

    import httpx
    from cryptography.hazmat.primitives.asymmetric import ec
    from fastapi import FastAPI

    from hirz.aws import app as aws_app

    secret = "ab" * 32
    monkeypatch.setenv("HIRZ_LLM", "off")
    monkeypatch.setenv("HIRZ_COMPANION_ORIGIN", "https://example.cloudfront.net")
    monkeypatch.setenv("HIRZ_COMPANION_RP_ID", "example.cloudfront.net")
    monkeypatch.setattr(aws_app.config, "secret", lambda _: secret)
    monkeypatch.setattr(aws_app.config, "database", lambda _: Mock())
    monkeypatch.setattr(
        aws_app, "signing_key", lambda _: ec.generate_private_key(ec.SECP256R1())
    )
    monkeypatch.setattr(aws_app, "Companion", Mock())
    monkeypatch.setattr(aws_app, "create_app", lambda **kw: FastAPI())
    monkeypatch.setattr(aws_app, "tick", AsyncMock())
    caplog.set_level(logging.INFO, logger="uvicorn.error")

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(aws_app.create_worker()),
            base_url="https://example.cloudfront.net",
        ) as c:
            await c.get("/private-person?token=sensitive")
            response = await c.post(
                "/internal/tick", headers={"Authorization": "Bearer " + secret}
            )
            assert response.status_code == 204

    asyncio.run(run())
    evidence = [r.message for r in caplog.records if "item36_request" in r.message]
    assert evidence == [
        "item36_request kind=other status=404",
        "item36_request kind=tick status=204",
    ]


def test_tick_lambda_ignores_event_payload_and_requires_204(monkeypatch):
    from hirz.aws.lambdas import tick

    monkeypatch.setenv("HIRZ_TICK_SECRET", "secret-arn")
    monkeypatch.setenv("HIRZ_TICK_URL", "https://example.cloudfront.net/internal/tick")
    sdk = Mock()
    sdk.get_secret_value.return_value = {"SecretString": "ab" * 32}
    monkeypatch.setattr(tick.boto3, "client", Mock(return_value=sdk))
    from unittest.mock import MagicMock

    response = MagicMock()
    response.__enter__.return_value.status = 204
    opener = Mock()
    opener.open.return_value = response
    monkeypatch.setattr(tick.urllib.request, "build_opener", Mock(return_value=opener))
    tick.handler({"action": "unlock"}, None)
    request = opener.open.call_args.args[0]
    assert request.method == "POST" and request.data is None
    assert opener.open.call_args.kwargs["timeout"] == 65
    response.__enter__.return_value.status = 503
    with pytest.raises(RuntimeError):
        tick.handler({}, None)
    sdk.get_secret_value.return_value = {"SecretString": "UNINITIALIZED"}
    with pytest.raises(ValueError):
        tick.handler({}, None)


def test_iam_probe_requires_denials_with_positive_control_token(monkeypatch):
    from botocore.exceptions import ClientError

    from hirz.aws import probe

    for field in ("HIRZ_COMMAND_KEY", "HIRZ_IDENTITY_SECRET"):
        monkeypatch.setenv(field, "synthetic")
    monkeypatch.setenv("HIRZ_PROBE_WORKLOAD_TOKEN", "positive-control-token")
    sdk = Mock()
    for method in ("sign", "get_secret_value", "get_resource_api_key"):
        getattr(sdk, method).side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException"}}, method
        )
    sdk.get_caller_identity.return_value = {"Arn": "worker-role"}
    monkeypatch.setattr(probe, "client", lambda _: sdk)
    assert len(probe.iam()["denied"]) == 3
    assert (
        sdk.get_resource_api_key.call_args.kwargs["workloadIdentityToken"]
        == "positive-control-token"
    )
    sdk.get_resource_api_key.side_effect = ClientError(
        {"Error": {"Code": "ValidationException"}}, "get_resource_api_key"
    )
    with pytest.raises(ValueError, match="without a proven access denial"):
        probe.iam()
    sdk.sign.side_effect = None
    with pytest.raises(ValueError, match="unexpectedly obtained"):
        probe.iam()


def test_explicit_initialization_copies_machine_secret_and_refuses_replacement(
    monkeypatch,
):
    import asyncio
    import json
    from unittest.mock import AsyncMock, MagicMock

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    from hirz.aws import bootstrap

    values = {
        "HIRZ_MASTER_SECRET": json.dumps(
            {"username": "setup", "password": "synthetic"}
        ),
        "HIRZ_DATABASE_SECRET": "a" * 40,
        "HIRZ_AUDIT_SECRET": ec.generate_private_key(ec.SECP256R1())
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode(),
        "HIRZ_TICK_SECRET": "ab" * 32,
        "HIRZ_MACHINE_SECRET": "UNINITIALIZED",
    }
    for variable in ("HIRZ_USER_POOL", "HIRZ_MACHINE_CLIENT", "HIRZ_MACHINE_SECRET"):
        monkeypatch.setenv(variable, "synthetic")
    connection = AsyncMock()
    engine = Mock(dispose=AsyncMock())
    engine.begin.return_value = MagicMock()
    engine.begin.return_value.__aenter__.return_value = connection
    engine.connect.return_value = engine.begin.return_value
    monkeypatch.setattr(bootstrap, "database", lambda *a, **kw: engine)
    monkeypatch.setattr(bootstrap, "secret", values.__getitem__)
    sdk = Mock()
    monkeypatch.setattr(bootstrap, "client", lambda _: sdk)

    async def call(sdk, method, **kwargs):
        if method == "describe_user_pool_client":
            return {"UserPoolClient": {"ClientSecret": "nonfunctional-machine-secret"}}
        assert method == "put_secret_value"
        assert kwargs == {
            "SecretId": "synthetic",
            "SecretString": "nonfunctional-machine-secret",
        }
        return {}

    calls = AsyncMock(side_effect=call)
    monkeypatch.setattr(bootstrap, "call", calls)
    asyncio.run(bootstrap.initialize())
    assert calls.await_count == 2
    values["HIRZ_MACHINE_SECRET"] = "malformed-existing"
    with pytest.raises(ValueError, match="differs"):
        asyncio.run(bootstrap.initialize())
    assert calls.await_count == 3  # No overwrite on the failed second initialization.
