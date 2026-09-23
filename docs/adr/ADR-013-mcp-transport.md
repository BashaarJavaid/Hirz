# ADR-013: Local stateless MCP transport

**Status:** Accepted, 2026-09-23. The author approved the item 23 implementation
plan and explicitly approved rejecting GET with 405 after inspection showed the
pinned SDK still offers a GET event stream in stateless JSON mode.

## Decision

Pin the official Python SDK to `mcp==1.30.0`, without CLI extras; retain all
existing direct dependency pins. `hirz.api.app.create_app()` creates its own
FastMCP instance and owns its session manager through FastAPI lifespan. Mount the
SDK ASGI app at the root, after `/health`, with its path set to `/mcp`. This serves
canonical `/mcp` directly without the `/mcp/` mount redirect. The exported `app`
and Uvicorn/Docker entrypoint remain intact. `/health` is still liveness only.

Use `stateless_http=True` and `json_response=True`: independent request transports,
JSON replies, no server session ID, replay store or persistent event stream.
GET `/mcp` returns 405 with `Allow: POST, DELETE`; the SDK owns other method and
protocol responses (including stateless DELETE rejection). No legacy SSE endpoint
is mounted. Negotiation remains SDK-owned, with 2025-11-25 explicitly verified.

The only registered tool is the no-input, generic `what_can_you_do` function.
Pydantic return types generate its output schema and the SDK serializes structured
output plus its text representation. The existing `Speakable` validates speech.
Its detail states that household tools are not connected. No identity, household
read, UI resource, model call, database write or audit event is involved.

## Local boundary

Before dispatch, `hirz/mcp/transport.py` applies these fixed checks:

- Exactly one Host: `localhost:8000`, `127.0.0.1:8000`, or `[::1]:8000`; otherwise 421.
- Origin may be absent. If present, exactly one nonempty value must be an HTTP
  origin for those three hosts on port 8000 or 6274; otherwise 403. No wildcards,
  suffix matches, null origin, forwarded-header trust or CORS.
- Explicit SDK security settings enforce the allowlists, supplemented by header
  cardinality/empty-value checks. The SDK body limiter then rejects declared or
  received bodies exceeding 1,048,576 bytes with 413, including chunked bodies.
- After limiting, strict UTF-8 decoding and a string/escape-aware scan reject
  invalid encoding or more than 32 nested containers with generic 400 responses.
  The root container counts as one. Raw NUL is rejected because BOM-less UTF-16/32
  can otherwise decode as UTF-8; escaped JSON Unicode remains valid. An interrupted
  body is rejected before dispatch. JSON grammar and MCP validation stay in the SDK.

The SDK retains its own inner limiter; the same SDK limiter is also used ahead of
the Hirz text guard, so the latter never buffers an unbounded body. Test app
instances may supply their allocated loopback port explicitly. Deployment has no
allowlist environment variables, and Compose retains its loopback port binding.

## Rejected alternatives and deferrals

- A custom JSON-RPC dispatcher or a second FastMCP package duplicates the official
  SDK and its negotiation behavior.
- Stateful sessions, persistent GET streams, replay and elicitation add lifecycle
  state that the onboarding-only tool does not need. JSON mode alone does not
  disable the SDK's GET stream, hence the explicitly approved 405 guard.
- Mounting at `/mcp` with a child `/` introduces a redirect on the canonical URL.
- A Content-Length-only check misses chunked or understated bodies; decoding before
  bounding allocates untrusted input. Parsing JSON twice is unnecessary for depth.
- Wildcard ports, configurable deployment allowlists, forwarded headers and CORS
  widen the fixed local boundary without a current client requirement.
- OAuth, household tools, rate limits, readiness, AWS and UI resources remain later
  roadmap items. No threat-model claim changes with this transport-only work.

Inspector is pinned to 2.7.0 and run through `pnpm dlx`, outside project dependencies,
with temporary state and authentication enabled. Procedures and recorded results
live in [development](../development.md#item-23-local-mcp-transport) and the
[verification log](../verification-log.md#item-23--2026-09-23).

## Sources

- [Official SDK ASGI integration and structured output](https://py.sdk.modelcontextprotocol.io/v1/server/).
- [Pinned SDK transport security and body limiter](https://github.com/modelcontextprotocol/python-sdk/blob/v1.30.0/src/mcp/server/transport_security.py).
- [Pinned SDK HTTP method behavior](https://github.com/modelcontextprotocol/python-sdk/blob/v1.30.0/src/mcp/server/streamable_http.py).
- [Inspector 2.7.0 CLI checks](https://github.com/modelcontextprotocol/inspector/blob/2.7.0/docs/cli-smoke-testing.md).
- [Inspector authentication and state controls](https://github.com/modelcontextprotocol/inspector/blob/2.7.0/docs/environment-variables.md).
