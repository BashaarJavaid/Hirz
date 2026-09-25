"""Local MCP protocol, schema, lifecycle and adversarial request boundaries."""

import asyncio
import json
from collections import deque

import httpx
import pytest
from jsonschema import Draft202012Validator
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from starlette.types import Message, Receive, Scope, Send

from hirz.api.app import create_app
from hirz.mcp.contracts import WhatCanYouDoResult
from hirz.mcp.server import what_can_you_do
from hirz.mcp.transport import MAX_BODY_BYTES, MCPGuard, local_security

URL = "http://localhost:8000"
HEADERS = {"accept": "application/json", "content-type": "application/json"}
CALL = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {"name": "what_can_you_do", "arguments": {}},
}


def test_client_sdk_and_independent_lifecycles() -> None:
    async def run() -> None:
        # A new app owns a new manager; no singleton survives shutdown.
        for _ in range(2):
            app = create_app(port=8129)
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app)
                ) as http:

                    async def sequence() -> None:
                        async with streamable_http_client(
                            "http://127.0.0.1:8129/mcp", http_client=http
                        ) as (read, write, sid):
                            async with ClientSession(read, write) as session:
                                initialized = await session.initialize()
                                assert initialized.protocolVersion == "2025-11-25"
                                assert sid() is None
                                tools = (await session.list_tools()).tools
                                assert [tool.name for tool in tools] == [
                                    "what_can_you_do"
                                ]
                                tool = tools[0]
                                assert tool.inputSchema["properties"] == {}
                                Draft202012Validator(tool.inputSchema).validate({})
                                assert tool.outputSchema is not None
                                Draft202012Validator.check_schema(tool.outputSchema)
                                for _ in range(2):
                                    result = await session.call_tool(tool.name, {})
                                    assert not result.isError
                                    Draft202012Validator(tool.outputSchema).validate(
                                        result.structuredContent
                                    )
                                    value = WhatCanYouDoResult.model_validate(
                                        result.structuredContent
                                    )
                                    assert value == await what_can_you_do()
                                    assert len(value.speakable.headline.split()) <= 20
                                    assert len(value.speakable.details) <= 3
                                    assert len(value.speakable.options) <= 5
                                    assert (
                                        json.loads(result.content[0].text)
                                        == result.structuredContent
                                    )

                    await asyncio.gather(sequence(), sequence(), sequence())

    asyncio.run(run())


def test_http_protocol_and_liveness() -> None:
    async def run() -> None:
        app = create_app()
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=URL, headers=HEADERS
            ) as client:
                assert (await client.get("/health")).json() == {"status": "ok"}
                response = await client.post("/mcp", json=CALL)
                assert response.status_code == 200
                assert response.headers["content-type"] == "application/json"
                assert "mcp-session-id" not in response.headers
                assert "location" not in response.headers
                assert not any(
                    h.startswith("access-control-") for h in response.headers
                )
                for method in ("GET", "PUT", "PATCH", "OPTIONS", "HEAD"):
                    response = await client.request(method, "/mcp")
                    assert response.status_code == 405
                response = await client.get(
                    "/mcp", headers={"accept": "text/event-stream"}
                )
                assert response.status_code == 405
                assert response.headers["allow"] == "POST, DELETE"
                assert (await client.delete("/mcp")).status_code == 405
                assert (await client.get("/sse")).status_code == 404
                assert (
                    await client.post(
                        "/mcp",
                        json=CALL,
                        headers={"mcp-protocol-version": "1900-01-01"},
                    )
                ).status_code == 400
                assert (
                    await client.post(
                        "/mcp", json=CALL, headers={"accept": "text/plain"}
                    )
                ).status_code == 406
                assert (
                    await client.post(
                        "/mcp", content=b"{}", headers={"content-type": "text/plain"}
                    )
                ).status_code == 400
                initialize = {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                }
                assert (await client.post("/mcp", json=initialize)).json()["result"][
                    "protocolVersion"
                ] == "2025-11-25"
                initialize["params"]["protocolVersion"] = "1900-01-01"
                assert (await client.post("/mcp", json=initialize)).json()["result"][
                    "protocolVersion"
                ] == "2025-11-25"

    asyncio.run(run())


@pytest.mark.parametrize("host", ["localhost:8000", "127.0.0.1:8000", "[::1]:8000"])
@pytest.mark.parametrize("origin", [None, *local_security(8000).allowed_origins])
def test_allowed_headers(host: str, origin: str | None) -> None:
    headers = [(b"host", host.encode())]
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    assert guard_request(b"{}", headers=headers) == 204


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ([], 421),
        ([(b"host", b"")], 421),
        ([(b"host", b"localhost:8000")] * 2, 421),
        *[
            ([(b"host", value.encode())], 421)
            for value in (
                "localhost",
                "localhost:8001",
                "localhost.evil:8000",
                "127.0.0.1.evil:8000",
                "evil:8000",
                "LOCALHOST:8000",
            )
        ],
        *[
            ([(b"host", b"localhost:8000"), (b"origin", value.encode())], 403)
            for value in (
                "",
                "null",
                "https://localhost:8000",
                "http://localhost:6275",
                "http://localhost.evil:6274",
                "http://localhost:6274/",
                "http://localhost:6274@evil",
            )
        ],
        (
            [
                (b"host", b"localhost:8000"),
                (b"origin", b"http://localhost:6274"),
                (b"origin", b"http://localhost:6274"),
            ],
            403,
        ),
        (
            [
                (b"host", b"evil:8000"),
                (b"x-forwarded-host", b"localhost:8000"),
                (b"forwarded", b"host=localhost:8000"),
            ],
            421,
        ),
        (
            [
                (b"host", b"localhost:8000"),
                (b"origin", b"http://evil:8000"),
                (b"x-forwarded-origin", b"http://localhost:8000"),
            ],
            403,
        ),
    ],
)
def test_rejected_headers(headers: list[tuple[bytes, bytes]], status: int) -> None:
    assert guard_request(b"{}", headers=headers) == status


def guard_request(
    body: bytes,
    *,
    headers: list[tuple[bytes, bytes]] | None = None,
    streamed: bool = False,
    interrupted: bool = False,
) -> int:
    """Drive real ASGI messages, including lengths HTTP clients normally normalize."""

    async def run() -> int:
        dispatched = False
        sent: list[Message] = []

        async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
            nonlocal dispatched
            dispatched = True
            assert (await receive())["body"] == body
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "headers": headers
            if headers is not None
            else [(b"host", b"localhost:8000")],
        }
        chunks = (
            [body[: len(body) // 2], body[len(body) // 2 :]] if streamed else [body]
        )
        messages = deque(
            {
                "type": "http.request",
                "body": chunk,
                "more_body": index < len(chunks) - 1 or interrupted,
            }
            for index, chunk in enumerate(chunks)
        )
        messages.append({"type": "http.disconnect"})

        async def receive() -> Message:
            return messages.popleft()

        async def send(message: Message) -> None:
            sent.append(message)

        await MCPGuard(downstream, local_security(8000))(scope, receive, send)
        status = sent[0]["status"]
        assert dispatched == (status == 204)
        if status != 204:
            assert b"private-marker" not in sent[1]["body"]
        return status

    return asyncio.run(run())


@pytest.mark.parametrize("streamed", [False, True])
@pytest.mark.parametrize(
    "declared",
    [None, b"1", str(MAX_BODY_BYTES).encode(), str(MAX_BODY_BYTES + 1).encode()],
)
@pytest.mark.parametrize("extra", [0, 1])
def test_body_boundary(streamed: bool, declared: bytes | None, extra: int) -> None:
    body = b'"' + b"a" * (MAX_BODY_BYTES - 2 + extra) + b'"'
    headers = [(b"host", b"localhost:8000")]
    if declared is not None:
        headers.append((b"content-length", declared))
    if streamed:
        headers.append((b"transfer-encoding", b"chunked"))
    oversized = extra or declared == str(MAX_BODY_BYTES + 1).encode()
    assert guard_request(body, headers=headers, streamed=streamed) == (
        413 if oversized else 204
    )


@pytest.mark.parametrize(
    "encoding", ["utf-16", "utf-16-le", "utf-16-be", "utf-32", "utf-32-le", "utf-32-be"]
)
def test_other_encodings_rejected(encoding: str) -> None:
    assert guard_request(json.dumps(CALL).encode(encoding)) == 400


def test_interrupted_and_invalid_utf8_bodies() -> None:
    assert guard_request(b'{"private-marker":', streamed=True, interrupted=True) == 400
    assert guard_request(b"", interrupted=True) == 400
    assert guard_request(b'"private-marker\xff"') == 400


@pytest.mark.parametrize("container", ["array", "object"])
@pytest.mark.parametrize("depth", [32, 33])
def test_json_depth_and_strings(container: str, depth: int) -> None:
    value = json.dumps('Unicode café 家 🏠; brackets [[[{{{; quote " then \\"')
    opening, closing = ("[", "]") if container == "array" else ('{"a":', "}")
    assert guard_request((opening * depth + value + closing * depth).encode()) == (
        204 if depth == 32 else 400
    )


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not-json",
        b'{"private-marker":',
        b'"\xff"',
        json.dumps(CALL).encode("utf-16"),
        b"[" * 33 + b"]" * 33,
    ],
)
def test_invalid_body_through_endpoint(
    body: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def forbidden() -> WhatCanYouDoResult:
        pytest.fail("Invalid body dispatched a tool")

    monkeypatch.setattr("hirz.mcp.server.what_can_you_do", forbidden)

    async def run() -> None:
        app = create_app()
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=URL, headers=HEADERS
            ) as client:
                assert (await client.post("/mcp", content=body)).status_code == 400

    asyncio.run(run())


def test_utf8_and_exact_boundaries_through_sdk() -> None:
    async def run() -> None:
        app = create_app()
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=URL, headers=HEADERS
            ) as client:
                body = json.dumps(
                    {**CALL, "unicode": "café 家 🏠"}, ensure_ascii=False
                ).encode()
                body += b" " * (MAX_BODY_BYTES - len(body))
                assert (await client.post("/mcp", content=body)).status_code == 200
                assert (
                    await client.post("/mcp", content=body + b" ")
                ).status_code == 413
                # Root object is depth one; unknown metadata is ignored by dispatch.
                for depth in (32, 33):
                    body = (
                        json.dumps(CALL)[:-1]
                        + ', "nested":'
                        + "[" * (depth - 1)
                        + "0"
                        + "]" * (depth - 1)
                        + "}"
                    )
                    assert (await client.post("/mcp", content=body)).status_code == (
                        200 if depth == 32 else 400
                    )

    asyncio.run(run())
