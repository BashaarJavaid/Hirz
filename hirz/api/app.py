"""Local MCP and liveness; dependency readiness remains later work."""

import os
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from hirz.db import database_url
from hirz.local import read_env, signing_key
from hirz.mcp.auth import SCOPES, KeyCache, OAuthGate
from hirz.mcp.profiles import load as load_profiles
from hirz.mcp.runtime import HouseholdRuntime
from hirz.mcp.runtime import register as register_household
from hirz.mcp.server import HirzMCP, create_server
from hirz.mcp.transport import MCPGuard, local_security
from hirz.pipeline.audit import AuditWriter


async def health() -> dict[str, str]:
    return {"status": "ok"}


def create_app(
    *,
    port: int = 8000,
    cache: KeyCache | None = None,
    engine: AsyncEngine | None = None,
    register: Callable[[HirzMCP], None] | None = None,
    household: HouseholdRuntime | None = None,
) -> FastAPI:
    """One SDK manager per app; only tests/smoke register diagnostic tools."""
    security = local_security(port)
    server = create_server(
        security, authentication=cache is not None and engine is not None
    )
    if household is not None:
        register_household(server, household)
    if register is not None:
        register(server)
    mcp_app = server.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            async with AsyncExitStack() as stack:
                if household is not None:
                    await stack.enter_async_context(household.run())
                if cache is not None:
                    await stack.enter_async_context(cache.run())
                await stack.enter_async_context(server.session_manager.run())
                yield
        finally:
            if engine is not None:
                await engine.dispose()

    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None, lifespan=lifespan)
    app.add_api_route("/health", health)
    if cache is not None:

        async def metadata() -> dict[str, object]:
            return {
                "resource": cache.resource,
                "authorization_servers": [cache.issuer],
                "scopes_supported": list(SCOPES),
                "bearer_methods_supported": ["header"],
            }

        app.add_api_route("/.well-known/oauth-protected-resource", metadata)
        app.add_api_route("/.well-known/oauth-protected-resource/mcp", metadata)
    app.mount(
        "/",
        MCPGuard(
            OAuthGate(
                mcp_app, cache=cache, engine=engine, tool_scopes=server.tool_scopes
            ),
            security,
        ),
    )
    return app


def create_local_oauth_app() -> FastAPI:
    engine = create_async_engine(
        database_url(read_env(Path(".env"))),
        hide_parameters=True,
        connect_args={"connect_timeout": 2},
    )
    return create_app(
        cache=KeyCache(),
        engine=engine,
        household=HouseholdRuntime(
            engine,
            AuditWriter(signing_key(read_env(Path(".env")))),
            profiles=load_profiles(
                Path(os.environ["HIRZ_PROFILES_FILE"])
                if os.environ.get("HIRZ_PROFILES_FILE")
                else None
            ),
        ),
    )


app = create_app()
