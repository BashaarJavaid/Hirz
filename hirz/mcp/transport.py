"""Fixed local edge checks ahead of the SDK's protocol dispatch."""

from mcp.server.transport_security import (
    RequestBodyLimitMiddleware,
    TransportSecurityMiddleware,
    TransportSecuritySettings,
)
from starlette.requests import ClientDisconnect, Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_BODY_BYTES = 1_048_576
MAX_DEPTH = 32


def local_security(port: int) -> TransportSecuritySettings:
    hosts = ("localhost", "127.0.0.1", "[::1]")
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[f"{host}:{port}" for host in hosts],
        allowed_origins=[
            f"http://{host}:{origin_port}"
            for host in hosts
            for origin_port in (port, 6274)
        ],
    )


def check_text(body: bytes) -> None:
    """Bound nesting before JSON parsing, without counting string contents."""
    text = body.decode("utf-8", errors="strict")
    # UTF-16/32 without a BOM can decode as UTF-8 but contains raw NUL bytes.
    if "\x00" in text:
        raise ValueError("Invalid encoding")
    depth = 0
    in_string = escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            if depth > MAX_DEPTH:
                raise ValueError("Excessive nesting")
        elif char in "]}":
            depth -= 1


class MCPGuard:
    def __init__(self, app: ASGIApp, security: TransportSecuritySettings) -> None:
        self.app = app
        self.security = TransportSecurityMiddleware(security)
        self.bounded = RequestBodyLimitMiddleware(self.checked_body, MAX_BODY_BYTES)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive)
        hosts = request.headers.getlist("host")
        origins = request.headers.getlist("origin")
        error: Response | None
        if len(hosts) != 1 or not hosts[0]:
            error = Response("Invalid Host header", status_code=421)
        elif len(origins) > 1 or origins == [""]:
            error = Response("Invalid Origin header", status_code=403)
        else:
            error = await self.security.validate_request(request)
        if error is not None:
            await error(scope, receive, send)
            return
        await self.bounded(scope, receive, send)

    async def checked_body(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        try:
            body = await request.body()
            check_text(body)
        except (ValueError, ClientDisconnect):
            await Response("Invalid request body", status_code=400)(
                scope, receive, send
            )
            return

        if scope["method"] == "GET" and scope["path"] == "/mcp":
            await Response(status_code=405, headers={"Allow": "POST, DELETE"})(
                scope, receive, send
            )
            return

        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
