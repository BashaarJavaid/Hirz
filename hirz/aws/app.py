"""AWS entrypoints: authenticated generic Runtime, passkey companion worker."""

import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from mcp.server.transport_security import TransportSecuritySettings

from hirz import db
from hirz.api.app import create_app
from hirz.aws import config
from hirz.aws.tick import router
from hirz.aws.worker import tick
from hirz.companion.api import Companion
from hirz.companion.auth import Config
from hirz.local import signing_key
from hirz.mcp.server import create_server
from hirz.pipeline.audit import AuditWriter


def create_worker() -> FastAPI:
    if os.environ.get("HIRZ_LLM") != "off":
        raise ValueError("Item 36 acceptance requires inference disabled")
    service = Companion(
        config.database(config.secret("HIRZ_DATABASE_SECRET")),
        AuditWriter(
            signing_key({"AUDIT_SIGNING_KEY": config.secret("HIRZ_AUDIT_SECRET")})
        ),
        Config(os.environ["HIRZ_COMPANION_ORIGIN"], os.environ["HIRZ_COMPANION_RP_ID"]),
    )
    app = create_app(companion=service, engine=service.engine)

    @app.middleware("http")
    async def request_evidence(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        kind = {"/internal/tick": "tick", "/health": "health"}.get(
            request.url.path, "other"
        )
        logging.getLogger("uvicorn.error").info(
            "item36_request kind=%s status=%d", kind, response.status_code
        )
        return response

    original = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with service.engine.connect() as connection:
            await connection.run_sync(db.require_current)
        async with original(app):
            yield

    app.router.lifespan_context = lifespan
    # The shared app's catch-all MCP mount is last, so tick must precede it.
    app.router.routes[0:0] = router(
        config.secret("HIRZ_TICK_SECRET"), lambda: tick(service)
    ).routes
    return app


def create_runtime() -> FastAPI:
    # Runtime CUSTOM_JWT authenticates before the private container listener.
    server = create_server(
        TransportSecuritySettings(enable_dns_rebinding_protection=False)
    )
    mcp_app = server.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with server.session_manager.run():
            yield

    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None, lifespan=lifespan)

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"status": "Healthy"}

    app.mount("/", mcp_app)
    return app
