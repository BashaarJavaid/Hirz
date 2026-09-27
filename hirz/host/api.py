"""Explicitly mounted local simulator API, separate from companion authority."""

import asyncio
import json
import secrets
from collections.abc import AsyncIterator
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from hirz.host.simulator import ACCOUNTS, MODELS, Browser, Simulator
from hirz.mcp.cards import NAMES, assets

COOKIE = "hirz_simulator"


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["turn", "cancel", "account", "model", "answer", "link", "card"]
    text: str = Field(default="", max_length=2000)
    prompt_id: str | None = None
    action: Literal["accept", "decline", "cancel"] = "cancel"
    content: dict[str, str | int | float | bool] = Field(default_factory=dict)
    tool: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)


def router(service: Simulator) -> APIRouter:
    api = APIRouter(prefix="/api/simulator")
    templates = assets()

    def browser(request: Request, *, create: bool = False) -> tuple[str, Browser]:
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(403, "Cross-site simulator request")
        key, value = service.browser(
            request.cookies.get(COOKIE), create=create, touch=request.method == "POST"
        )
        if request.method == "POST" and (
            request.headers.get("origin") != service.origin
            or not secrets.compare_digest(
                request.headers.get("x-hirz-simulator-csrf", ""), value.csrf
            )
        ):
            raise HTTPException(403, "Simulator origin or CSRF mismatch")
        return key, value

    @api.get("/session")
    async def session(request: Request, response: Response) -> dict[str, Any]:
        key, value = browser(request, create=True)
        response.set_cookie(
            COOKIE,
            key,
            httponly=True,
            secure=service.origin.startswith("https:"),
            samesite="lax",
            max_age=43200,
        )
        response.headers["Cache-Control"] = "no-store"
        echo = value.echoes[value.account]
        return {
            "csrf": value.csrf,
            "account": value.account,
            "accounts": ACCOUNTS,
            "model": value.model,
            "models": MODELS if service.ledger else {"scripted": MODELS["scripted"]},
            "linked": bool(echo.tokens),
            "generation": echo.generation,
            "prompt": echo.prompt,
            "busy": echo.task is not None and not echo.task.done(),
        }

    @api.get("/callback")
    async def callback(
        request: Request, state: str, code: str = ""
    ) -> RedirectResponse:
        # OAuth redirects are cross-site navigation; state and the HttpOnly browser
        # cookie jointly bind the callback, with exact redirect URI and PKCE.
        _, value = service.browser(request.cookies.get(COOKIE))
        try:
            await service.linked(value, state, code)
        except Exception:
            return RedirectResponse(
                "/simulator?link=failed", headers={"Cache-Control": "no-store"}
            )
        return RedirectResponse("/simulator", headers={"Cache-Control": "no-store"})

    @api.post("/command")
    async def command(value: Command, request: Request) -> dict[str, Any]:
        _, owner = browser(request)
        echo = owner.echoes[owner.account]
        if value.operation == "link":
            return {"url": service.link(owner)}
        if value.operation == "cancel":
            owner.cancel()
        elif value.operation == "account":
            if value.text not in ACCOUNTS:
                raise HTTPException(400, "Unknown Echo")
            owner.cancel()
            owner.account = value.text
        elif value.operation == "model":
            if (
                value.text not in MODELS
                or value.text != "scripted"
                and not service.ledger
            ):
                raise HTTPException(400, "Model is unavailable")
            owner.cancel()
            if any(e.task and not e.task.done() for e in owner.echoes.values()):
                raise HTTPException(409, "Wait for the accepted call to settle")
            owner.model = value.text
            for account in owner.echoes.values():
                account.history.clear()
                account.results.clear()
                account.events.clear()
        elif value.operation == "answer":
            if (
                not echo.prompt
                or value.prompt_id != echo.prompt["id"]
                or echo.answer is None
                or echo.answer.done()
            ):
                raise HTTPException(409, "That prompt is no longer pending")
            if value.action == "accept":
                import jsonschema  # type: ignore[import-untyped]

                try:
                    jsonschema.Draft202012Validator(echo.prompt["schema"]).validate(
                        value.content
                    )
                except jsonschema.ValidationError:
                    raise HTTPException(422, "Supply the requested values") from None
            echo.answer.set_result(
                {
                    "action": value.action,
                    "content": value.content if value.action == "accept" else None,
                }
            )
        elif value.operation in {"turn", "card"}:
            active = service.active.get(owner.account)
            if active and not active.done():
                raise HTTPException(409, "This Echo already has an active turn")
            if not echo.tokens:
                raise HTTPException(409, "Link this Echo first")
            if value.operation == "card" and value.tool is None:
                raise HTTPException(400, "Choose a card action")
            echo.task = asyncio.create_task(
                service.turn(
                    owner,
                    value.text,
                    account=owner.account,
                    model=owner.model,
                    selected=(value.tool, value.arguments)
                    if value.tool and value.operation == "card"
                    else None,
                )
            )
            service.active[owner.account] = echo.task
            if value.operation == "card":
                await echo.task
                if echo.last_result is None:
                    raise HTTPException(409, "The card request did not complete")
                return {"result": echo.last_result}
        return {"status": "accepted"}

    @api.get("/transcript")
    async def transcript(request: Request, response: Response) -> list[dict[str, Any]]:
        _, owner = browser(request)
        response.headers["Cache-Control"] = "no-store"
        return list(owner.echoes[owner.account].events)

    @api.get("/events")
    async def events(request: Request) -> StreamingResponse:
        _, owner = browser(request)
        account = owner.account
        echo = owner.echoes[account]

        async def stream() -> AsyncIterator[str]:
            cursor = request.headers.get("last-event-id")
            backlog = list(echo.events)
            seen = {
                e["id"]
                for e in backlog[
                    : next(
                        (i + 1 for i, e in enumerate(backlog) if e["id"] == cursor), 0
                    )
                ]
            }
            replay = {e["id"] for e in backlog} if cursor is None else set()
            while not owner.expired() and owner.account == account:
                if await request.is_disconnected():
                    break
                for event in list(echo.events):
                    if event["id"] not in seen:
                        seen.add(event["id"])
                        yield (
                            "id: "
                            + event["id"]
                            + "\ndata: "
                            + json.dumps(event | {"replay": event["id"] in replay})
                            + "\n\n"
                        )
                yield ": heartbeat\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @api.get("/cards/{name}")
    async def card(name: str, request: Request) -> Response:
        browser(request)
        if name not in NAMES:
            raise HTTPException(404)
        return Response(
            templates[f"ui://hirz/{name}"],
            media_type="text/html",
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'; sandbox allow-scripts",
            },
        )

    return api
