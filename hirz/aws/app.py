"""AWS entrypoints: authenticated household Runtime, passkey companion worker."""

import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import sqlalchemy as sa
from fastapi import FastAPI, Request, Response
from mcp.server.transport_security import TransportSecuritySettings

from hirz import db
from hirz.api.app import create_app
from hirz.aws import config
from hirz.aws.auth import CognitoCache
from hirz.aws.fixture import policy_routes
from hirz.aws.routing import Route
from hirz.aws.tick import router
from hirz.aws.worker import tick
from hirz.companion.api import Companion
from hirz.companion.auth import Config
from hirz.local import signing_key
from hirz.mcp.runtime import HouseholdRuntime
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
        account_verifier=CognitoCache(
            os.environ["HIRZ_COGNITO_ISSUER"],
            os.environ["HIRZ_RUNTIME_RESOURCE"],
            os.environ["HIRZ_HUMAN_CLIENT"],
        )
        if os.environ.get("HIRZ_RUNTIME_RESOURCE")
        else None,
        policy_routes=policy_routes(
            Route(
                os.environ["HIRZ_POLICY_ENGINE"],
                os.environ["HIRZ_GATEWAY_ARN"],
                os.environ["HIRZ_GATEWAY_URL"],
            )
        ),
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
            assert service.policy_routes is not None
            for household in (
                await connection.execute(sa.select(db.households.c.id))
            ).scalars():
                service.policy_routes.route(household)
        async with original(app):
            yield

    app.router.lifespan_context = lifespan
    # The shared app's catch-all MCP mount is last, so tick must precede it.
    app.router.routes[0:0] = router(
        config.secret("HIRZ_TICK_SECRET"), lambda: tick(service)
    ).routes
    return app


def create_runtime() -> FastAPI:
    resource = os.environ["HIRZ_RUNTIME_RESOURCE"]
    url = urlsplit(resource)
    if (
        url.scheme != "https"
        or not url.netloc
        or not url.path.endswith("/invocations")
        or url.fragment
    ):
        raise ValueError(
            "Configure the exact Runtime protected resource before invocation"
        )
    cache = CognitoCache(
        os.environ["HIRZ_COGNITO_ISSUER"],
        resource,
        os.environ["HIRZ_HUMAN_CLIENT"],
        metadata_url=url._replace(
            path=url.path + "/.well-known/oauth-protected-resource"
        ).geturl(),
    )
    engine = config.database(config.secret("HIRZ_DATABASE_SECRET"))
    household = HouseholdRuntime(
        engine,
        AuditWriter(
            signing_key({"AUDIT_SIGNING_KEY": config.secret("HIRZ_AUDIT_SECRET")})
        ),
        policy_routes=policy_routes(
            Route(
                os.environ["HIRZ_POLICY_ENGINE"],
                os.environ["HIRZ_GATEWAY_ARN"],
                os.environ["HIRZ_GATEWAY_URL"],
            )
        ),
    )
    # Runtime owns public ingress; its private listener receives Authorization
    # through the explicit header allowlist and independently verifies it.
    app = create_app(
        cache=cache,
        engine=engine,
        household=household,
        security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    async def ping() -> dict[str, str]:
        return {"status": "Healthy"}

    # The shared MCP catch-all mount must remain last.
    app.add_api_route("/ping", ping)
    app.router.routes.insert(0, app.router.routes.pop())
    return app
