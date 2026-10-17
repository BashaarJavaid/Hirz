"""Authenticated request-scoped work; cancellation settles before responding."""

import asyncio
import logging
import re
import secrets
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Request, Response

log = logging.getLogger(__name__)


def router(
    secret: str, process: Callable[[], Awaitable[None]], *, deadline: float = 50
) -> APIRouter:
    if not re.fullmatch(r"[0-9a-f]{64}", secret):
        raise ValueError("A randomly initialized 32-byte tick secret is required")
    routes = APIRouter()

    @routes.post("/internal/tick")
    async def tick(request: Request) -> Response:
        auth = request.headers.getlist("authorization")
        if len(auth) != 1 or not secrets.compare_digest(
            auth[0].encode(), ("Bearer " + secret).encode()
        ):
            return Response(status_code=401)
        # Stream only until the first byte; do not buffer an untrusted body.
        async for chunk in request.stream():
            if chunk:
                return Response(status_code=400)
        try:
            async with asyncio.timeout(deadline):
                await process()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("tick_failed error=%s", type(exc).__name__)
            return Response(status_code=503)
        return Response(status_code=204)

    return routes
