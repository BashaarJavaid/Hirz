"""Local MCP and liveness; dependency readiness remains later work."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from hirz.mcp.server import create_server
from hirz.mcp.transport import MCPGuard, local_security


async def health() -> dict[str, str]:
    return {"status": "ok"}


def create_app(*, port: int = 8000) -> FastAPI:
    """Own one SDK manager per app; tests may supply an allocated loopback port."""
    security = local_security(port)
    server = create_server(security)
    mcp_app = server.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with server.session_manager.run():
            yield

    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None, lifespan=lifespan)
    app.add_api_route("/health", health)
    app.mount("/", MCPGuard(mcp_app, security))
    return app


app = create_app()
