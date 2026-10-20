"""The operator smoke uses the real MCP SDK and never reports private responses."""

import asyncio
import json
import sys
from uuid import uuid4

import httpx
import pytest

from hirz.mcp.contracts import TOOLS
from scripts import smoke_runtime as smoke

ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/hirz_test"
POOL = "us-east-1_test"
RESOURCE, ISSUER = smoke.endpoints(ARN, POOL)
METADATA = RESOURCE.replace(
    "/invocations?", "/invocations/.well-known/oauth-protected-resource?"
)
TOKEN = "private.synthetic.token"


def host(monkeypatch, *, failure=None):
    household = uuid4()
    requests = []
    client_type = httpx.AsyncClient

    def respond(request):
        requests.append(request)
        if request.method == "GET" and str(request.url) == METADATA:
            assert "authorization" not in request.headers
            if failure == "metadata-redirect":
                return httpx.Response(302, headers={"location": "https://evil.test/"})
            return httpx.Response(
                200,
                json={
                    "resource": RESOURCE
                    if failure != "resource"
                    else RESOURCE + "other",
                    "authorization_servers": [ISSUER]
                    if failure != "issuer"
                    else ["https://evil.test"],
                },
            )
        assert str(request.url) == RESOURCE
        if "authorization" not in request.headers:
            assert request.method == "POST"
            return httpx.Response(
                200 if failure == "public" else 401,
                headers={
                    "www-authenticate": 'Bearer resource_metadata="'
                    + ("https://evil.test" if failure == "challenge" else METADATA)
                    + '"'
                },
            )
        assert request.headers["authorization"] == "Bearer " + TOKEN
        if request.method == "GET":
            return httpx.Response(405)
        assert request.method == "POST"
        message = json.loads(request.content)
        if "id" not in message:
            return httpx.Response(202)
        if message["method"] == "initialize":
            result = {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "runtime-fixture", "version": "1"},
            }
        elif message["method"] == "tools/list":
            names = list(TOOLS)
            if failure == "catalog":
                names[-1] = names[0]
            result = {
                "tools": [
                    {"name": name, "inputSchema": {"type": "object"}} for name in names
                ]
            }
        else:
            assert message["method"] == "tools/call"
            assert message["params"] == {
                "name": "get_household_context",
                "arguments": {},
            }
            if failure == "read-error":
                result = {
                    "isError": True,
                    "content": [{"type": "text", "text": "private server error"}],
                }
            else:
                result = {
                    "content": [],
                    "structuredContent": {
                        "speakable": {
                            "headline": "Private household information",
                            "details": [],
                            "options": [],
                        },
                        "data": {
                            "status": "denied" if failure == "denied" else "ok",
                            "context": {
                                "household_id": str(
                                    uuid4() if failure == "household" else household
                                ),
                                "scope": "all",
                                "as_of": "2026-10-19T00:00:00Z",
                                "read_at": "2026-10-19T00:00:00Z",
                                "stale": False,
                                "staleness_seconds": 0,
                                "policy_status": "unvalidated",
                                "data": {"members": [{"name": "Private person"}]},
                            },
                        },
                    },
                }
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": message["id"], "result": result}
        )

    monkeypatch.setattr(
        smoke.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs),
    )
    return household, requests


def test_complete_read_smoke_redacts_and_does_not_claim_latency_acceptance(monkeypatch):
    household, requests = host(monkeypatch)
    result = asyncio.run(smoke.smoke(ARN, POOL, TOKEN, household))
    assert result["status"] == "passed"
    assert result["tool_count"] == 12
    assert result["initialization_ms"] > 0 and result["household_read_ms"] > 0
    assert "warm p95 and verified cold start" in result["not_checked"]
    output = json.dumps(result)
    assert not any(
        private in output for private in (TOKEN, str(household), "Private person")
    )
    assert len(requests) >= 6


@pytest.mark.parametrize(
    "failure",
    [
        "challenge",
        "public",
        "metadata-redirect",
        "resource",
        "issuer",
        "catalog",
        "read-error",
        "denied",
        "household",
    ],
)
def test_smoke_refuses_discovery_catalog_and_identity_failures(monkeypatch, failure):
    household, requests = host(monkeypatch, failure=failure)
    with pytest.raises(Exception) as caught:
        asyncio.run(smoke.smoke(ARN, POOL, TOKEN, household))
    error = caught.value
    while isinstance(error, ExceptionGroup):
        assert len(error.exceptions) == 1
        error = error.exceptions[0]
    expected = {
        "challenge": "401 discovery challenge",
        "public": "401 discovery challenge",
        "metadata-redirect": "302",
        "resource": "configured resource/issuer",
        "issuer": "configured resource/issuer",
        "catalog": "exact Hirz tool catalog",
        "read-error": "household read failed",
        "denied": "expected linked household",
        "household": "expected linked household",
    }
    assert expected[failure] in str(error)
    if failure in {"challenge", "public", "metadata-redirect", "resource", "issuer"}:
        assert all("authorization" not in request.headers for request in requests)


@pytest.mark.parametrize(
    "arn,pool",
    [
        ("https://evil.test", POOL),
        (ARN + "?other", POOL),
        (ARN, "us-west-2_test"),
        (ARN, POOL + "/../other"),
    ],
)
def test_endpoints_reject_untrusted_locations(arn, pool):
    with pytest.raises(ValueError):
        smoke.endpoints(arn, pool)


def test_cli_private_token_and_exclusive_redacted_evidence(
    tmp_path, monkeypatch, capsys
):
    household, requests = host(monkeypatch)
    token_file, output = tmp_path / ".env", tmp_path / "report.json"
    token_file.touch(mode=0o600)
    token_file.write_text("HIRZ_ACCEPTANCE_TOKEN='" + TOKEN + "'\n")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smoke_runtime",
            "--runtime-arn",
            ARN,
            "--user-pool",
            POOL,
            "--household",
            str(household),
            "--token-file",
            str(token_file),
            "--output",
            str(output),
        ],
    )
    assert smoke.main() == 0
    assert output.stat().st_mode & 0o777 == 0o600
    before, count = output.read_bytes(), len(requests)
    assert smoke.main() == 1
    assert output.read_bytes() == before and len(requests) == count
    output.unlink()
    token_file.chmod(0o644)
    assert smoke.main() == 1
    assert not output.exists() and len(requests) == count
    assert TOKEN not in capsys.readouterr().out


def test_cli_failure_omits_server_details_and_emits_no_pass(
    tmp_path, monkeypatch, capsys
):
    household, _ = host(monkeypatch, failure="read-error")
    token_file = tmp_path / ".env"
    token_file.touch(mode=0o600)
    token_file.write_text("HIRZ_ACCEPTANCE_TOKEN='" + TOKEN + "'\n")
    output = tmp_path / "report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smoke_runtime",
            "--runtime-arn",
            ARN,
            "--user-pool",
            POOL,
            "--household",
            str(household),
            "--token-file",
            str(token_file),
            "--output",
            str(output),
        ],
    )
    assert smoke.main() == 1 and not output.exists()
    printed = capsys.readouterr().out
    assert "FAIL Runtime read smoke" in printed
    assert "private server error" not in printed and TOKEN not in printed
