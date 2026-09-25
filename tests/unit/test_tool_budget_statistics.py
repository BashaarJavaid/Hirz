"""The benchmark cannot hide a slow path by pooling or omitting samples."""

import asyncio
import json
import sys
import time
from types import SimpleNamespace

import httpx
import jwt
import pytest
from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientMetadata, OAuthToken
from pydantic import AnyUrl

from hirz.mcp.contracts import TOOLS, Result, response
from hirz.mcp.dev_oauth import registered_client
from scripts.smoke_oauth import Storage
from scripts.smoke_tool_budget import (
    SAMPLES,
    SELECTION_CASES,
    Client,
    Environment,
    statistics,
    timing_report,
)
from scripts.tool_selection import CASES


@pytest.mark.parametrize(
    "case,tool,args",
    [
        ("onboarding", "what_can_you_do", {}),
        ("context-all", "get_household_context", {"scope": "all"}),
    ],
)
def test_raw_request_is_byte_identical_to_sdk(case, tool, args):
    async def run():
        token = jwt.encode({"exp": time.time() + 3600}, "", algorithm="none")
        captured = []
        value = response("Request identity fixture").model_dump(mode="json")

        def serve(request):
            body = json.loads(request.content)
            if body["method"] == "notifications/initialized":
                return httpx.Response(202)
            if body["method"] == "initialize":
                result = {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "serverInfo": {"name": "stateless-fixture", "version": "1"},
                }
            elif body["method"] == "tools/list":
                result = {
                    "tools": [
                        {
                            "name": tool,
                            "inputSchema": {"type": "object"},
                            "outputSchema": Result.model_json_schema(),
                        }
                    ]
                }
            else:
                assert body["method"] == "tools/call"
                captured.append(
                    (
                        request.method,
                        request.url.raw_path,
                        tuple(
                            (name, request.headers[name].encode())
                            for name in (
                                "authorization",
                                "accept",
                                "content-type",
                                "mcp-protocol-version",
                            )
                        ),
                        request.content,
                    )
                )
                result = {"content": [], "structuredContent": value, "isError": False}
            return httpx.Response(
                200, json={"jsonrpc": "2.0", "id": body["id"], "result": result}
            )

        url = "http://127.0.0.1:8000/mcp"
        callback = "http://127.0.0.1:8001/callback"
        storage = Storage(
            registered_client(callback),
            OAuthToken(
                access_token=token,
                token_type="Bearer",
                expires_in=3600,
            ),
        )

        async def unexpected_login(*args):
            raise AssertionError("Fixture already has a valid token")

        auth = OAuthClientProvider(
            url,
            OAuthClientMetadata(redirect_uris=[AnyUrl(callback)]),
            storage,
            unexpected_login,
            unexpected_login,
        )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(serve),
            auth=auth,
        ) as http:
            async with streamable_http_client(url, http_client=http) as (
                read,
                write,
                sid,
            ):
                async with ClientSession(read, write) as session:
                    initialized = await session.initialize()
                    await session.list_tools()
                    assert sid() is None
                    client = Client(
                        session,
                        storage,
                        lambda: None,
                        auth,
                        http,
                        url,
                        initialized.protocolVersion,
                    )
                    # Independent stateless request sequences: align IDs for an
                    # exact byte comparison after initialize=0 and tools/list=1.
                    client.request_id = 2
                    client.measuring = True
                    assert await client.call(case, tool, args) == Result.model_validate(
                        value
                    )
                    assert len(captured) == 2
                    assert captured[0] == captured[1]
                    assert (
                        len(client.samples[case]) == len(client.sdk_samples[case]) == 1
                    )
                    # The unchanged SDK output-schema assertion still runs on raw calls.
                    value["data"]["status"] = "invalid"
                    with pytest.raises(
                        RuntimeError, match="Invalid structured content"
                    ):
                        await client.call("", tool, args)

    asyncio.run(run())


def test_nearest_rank_retains_outliers_and_requires_complete_measurements():
    values = list(range(1, 101))
    result = statistics(values)
    assert result["count"] == SAMPLES
    assert result["p95_ms"] == 95
    assert result["median_ms"] == 50.5
    assert result["max_ms"] == 100
    assert result["samples_ms"] == values
    assert len(SELECTION_CASES) == len(CASES)
    with pytest.raises(AssertionError, match="Every tool"):
        timing_report([])
    incomplete = SimpleNamespace(
        samples={tool: [1.0] * SAMPLES for tool in TOOLS},
        tools={tool: tool for tool in TOOLS},
    )
    with pytest.raises(AssertionError, match="Missing or unexpected cases"):
        timing_report([incomplete])
    with pytest.raises(AssertionError):
        statistics([float("nan")])


def test_cancelled_benchmark_reaps_its_worker(tmp_path, monkeypatch):
    async def run():
        create = asyncio.create_subprocess_exec
        started = asyncio.Event()
        children = []

        async def worker(*args, **kwargs):
            child = await create(sys.executable, "-c", "import time; time.sleep(30)")
            children.append(child)
            started.set()
            return child

        monkeypatch.setattr(asyncio, "create_subprocess_exec", worker)
        connection = SimpleNamespace(
            engine=SimpleNamespace(url=SimpleNamespace(database="unused-disposable"))
        )
        env = Environment(connection, tmp_path, "demo-evening")
        env.fixture = tmp_path / "unused.yaml"
        env.clock_file = tmp_path / "clock.txt"
        env.clock_file.write_text("2026-09-23T00:00:00+00:00")
        task = asyncio.create_task(env.run_worker())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert children[0].returncode is not None

    asyncio.run(run())
