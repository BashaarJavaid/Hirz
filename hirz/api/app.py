"""Local MCP and liveness; dependency readiness remains later work."""

import gc
import os
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from hirz.companion.api import Companion
from hirz.companion.api import router as companion_router
from hirz.companion.auth import Config as CompanionConfig
from hirz.db import database_url
from hirz.host.simulator import Simulator
from hirz.local import read_env, signing_key
from hirz.mcp.auth import SCOPES, KeyCache, OAuthGate
from hirz.mcp.card_evidence import load as load_card_evidence
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
    companion: Companion | None = None,
    simulator: Simulator | None = None,
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
    # Preserve anonymous JSON discovery/onboarding while authenticated clients use
    # SDK-managed sessions. The OAuth gate still protects every household call.
    anonymous = create_server(security, authentication=server.authentication)
    anonymous.settings.stateless_http = True
    anonymous.settings.json_response = True
    if household is not None:
        register_household(anonymous, household)
    if register is not None:
        register(anonymous)
    anonymous_app = anonymous.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            async with AsyncExitStack() as stack:
                if household is not None:
                    await stack.enter_async_context(household.run())
                if companion is not None:
                    await stack.enter_async_context(companion.boundary.persistent())
                if cache is not None:
                    await stack.enter_async_context(cache.run())
                await stack.enter_async_context(server.session_manager.run())
                await stack.enter_async_context(anonymous.session_manager.run())
                # Startup policies, catalogs, schemas and metadata are never freed; freezing skips later full collections.
                # Collection stays enabled and thresholds are untouched.
                gc.freeze()
                yield
        finally:
            if engine is not None:
                await engine.dispose()

    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None, lifespan=lifespan)
    app.add_api_route("/health", health)
    if simulator is not None:
        from hirz.host.api import router as simulator_router

        app.include_router(simulator_router(simulator))
    if companion is not None:
        app.include_router(companion_router(companion))

        from fastapi.exceptions import RequestValidationError

        @app.exception_handler(RequestValidationError)
        async def invalid_input(
            request: Request, exc: RequestValidationError
        ) -> JSONResponse:
            return JSONResponse(
                {"detail": "Invalid request fields."},
                status_code=422,
                headers={"Cache-Control": "no-store"},
            )

        @app.exception_handler(ValueError)
        async def refused(request: Request, exc: ValueError) -> JSONResponse:
            return JSONResponse(
                {
                    "detail": "Request refused. Check your session, current rules and inputs."
                },
                status_code=403,
                headers={"Cache-Control": "no-store"},
            )

        ui = Path(__file__).parent.parent / "companion" / "ui"
        if not (ui / "index.html").is_file():
            raise ValueError("Build the companion first: pnpm --filter web build")
        app.mount(
            "/assets", StaticFiles(directory=ui / "assets"), name="companion-assets"
        )

        async def page() -> FileResponse:
            return FileResponse(
                ui / "index.html",
                headers={
                    "Cache-Control": "no-store",
                    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
                    "Referrer-Policy": "no-referrer",
                    "X-Content-Type-Options": "nosniff",
                },
            )

        for path in (
            "/",
            "/tonight",
            "/approvals",
            "/constitution",
            "/household",
            "/checkins",
            "/contact-links",
            "/audit",
            "/twin",
        ):
            app.add_api_route(path, page)

        if simulator is not None:

            async def simulator_page() -> FileResponse:
                result = await page()
                result.headers["Content-Security-Policy"] = (
                    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
                )
                return result

            app.add_api_route("/simulator", simulator_page)

        async def manifest() -> FileResponse:
            return FileResponse(
                ui / "manifest.webmanifest", media_type="application/manifest+json"
            )

        async def worker_script() -> FileResponse:
            return FileResponse(
                ui / "sw.js",
                media_type="text/javascript",
                headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
            )

        async def icon() -> FileResponse:
            return FileResponse(ui / "icon.svg", media_type="image/svg+xml")

        app.add_api_route("/manifest.webmanifest", manifest)
        app.add_api_route("/sw.js", worker_script)
        app.add_api_route("/icon.svg", icon)
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
                mcp_app,
                cache=cache,
                engine=engine,
                tool_scopes=server.tool_scopes,
                anonymous=anonymous_app,
            ),
            security,
            sessions=cache is not None and engine is not None,
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
        companion=Companion(
            engine,
            AuditWriter(signing_key(read_env(Path(".env")))),
            CompanionConfig(
                os.environ["HIRZ_COMPANION_ORIGIN"], os.environ["HIRZ_COMPANION_RP_ID"]
            ),
        )
        if os.environ.get("HIRZ_COMPANION_ORIGIN")
        else None,
        household=HouseholdRuntime(
            engine,
            AuditWriter(signing_key(read_env(Path(".env")))),
            card_evidence=load_card_evidence(
                Path(os.environ["HIRZ_CARD_EVIDENCE_FILE"])
                if os.environ.get("HIRZ_CARD_EVIDENCE_FILE")
                else None
            ),
            profiles=load_profiles(
                Path(os.environ["HIRZ_PROFILES_FILE"])
                if os.environ.get("HIRZ_PROFILES_FILE")
                else None
            ),
        ),
    )


app = create_app()
