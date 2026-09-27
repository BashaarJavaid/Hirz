"""Local browser host state. OAuth, conversation and prompts never enter cards."""

import asyncio
import base64
import hashlib
import json
import secrets
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

import httpx
from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client

from hirz.mcp.auth import SCOPES
from hirz.mcp.cards import TOOLS as CARDS
from hirz.mcp.dev_oauth import choices

ACCOUNTS = {"mom": "Mom’s Echo", "malik": "Malik’s Echo", "dad": "Dad’s Echo"}
MODELS = {"scripted": "Scripted", "haiku": "Claude Haiku 4.5", "nova": "Nova Lite"}


def commitment(name: str, args: dict[str, Any]) -> bool:
    return (
        name
        in {
            "execute_household_action",
            "approve_action",
            "revise_household_plan",
            "propose_household_rule",
            "assess_request_risk",
        }
        or name == "get_household_plan"
        and args.get("objective") is not None
        or name == "verify_trusted_identity"
        and args.get("operation") == "start"
    )


CONFIRM_SCHEMA = {
    "type": "object",
    "properties": {
        "confirmed": {"type": "boolean", "title": "Submit this exact request?"}
    },
    "required": ["confirmed"],
}


def describe(name: str, arguments: dict[str, Any]) -> str:
    labels = []
    for key, value in arguments.items():
        if (
            key.endswith("_id")
            or key in {"claimed_author", "claimed_requester"}
            or value is None
        ):
            continue
        labels.append(key.replace("_", " ") + ": " + str(value).replace("_", " "))
    return "Confirm " + name.replace("_", " ") + ". " + "; ".join(labels)


@dataclass
class Echo:
    tokens: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    results: dict[str, Any] = field(default_factory=dict)
    request_ids: dict[str, str] = field(default_factory=dict)
    last_result: dict[str, Any] | None = None
    events: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=200))
    task: asyncio.Task[None] | None = None
    prompt: dict[str, Any] | None = None
    answer: asyncio.Future[dict[str, Any]] | None = None
    generation: int = 0
    waiting_ms: int = 0
    tool_started: float | None = None


@dataclass
class Browser:
    created: float = field(default_factory=time.monotonic)
    touched: float = field(default_factory=time.monotonic)
    csrf: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    account: str = "malik"
    model: str = "scripted"
    echoes: dict[str, Echo] = field(
        default_factory=lambda: {name: Echo() for name in ACCOUNTS}
    )
    linking: dict[str, tuple[str, str, float]] = field(default_factory=dict)

    def expired(self) -> bool:
        return (
            time.monotonic() - self.touched >= 1800
            or time.monotonic() - self.created >= 43200
        )

    def cancel(self) -> None:
        echo = self.echoes[self.account]
        echo.generation += 1
        if echo.answer is not None and not echo.answer.done():
            echo.answer.set_result({"action": "cancel"})
        echo.prompt = None
        # Accepted calls are allowed to settle and retain their actual receipt.
        # The generation suppresses further calls/speech from the old turn.


def recorded(text: str, results: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Exact recorded utterances, never a guessed free-text interpreter."""
    text = text.strip().removeprefix("Alexa, ")
    if text in {"What's going on tonight?", "What’s going on tonight?"}:
        return [("get_household_plan", {})]
    if text in {
        "from now on, never unlock the door for someone we're not expecting.",
        "From now on, never unlock the door for someone we're not expecting.",
        "Never unlock for an unexpected visitor",
    }:
        return [("propose_household_rule", {"text": text})]
    if (
        text
        == "Malik just called from a strange number. He says he's in trouble and needs five hundred dollars. Is it really him?"
    ):
        return [
            (
                "assess_request_risk",
                {"text": text, "claimed_party": "Malik", "party": "person"},
            ),
            (
                "verify_trusted_identity",
                {"operation": "start", "contact": "Malik", "text": text},
            ),
        ]
    if text in {"is it him?", "Is it him?"}:
        return [
            ("verify_trusted_identity", {"operation": "status", "contact": "Malik"})
        ]
    if text.lower() in {"do it", "do it.", "approve the plan"}:
        plan = results.get("get_household_plan", {}).get("data", {}).get("plan")
        if plan:
            return [
                (
                    "approve_action",
                    {
                        "approved": True,
                        "plan_id": plan["plan_id"],
                        "version": plan["version"],
                    },
                )
            ]
    if text.rstrip(".") in {"Approve the pending action", "Decline the pending action"}:
        data = results.get("get_household_plan", {}).get("data", {})
        plan, decisions = data.get("plan"), data.get("decisions", [])
        if plan and decisions and decisions[0].get("approval"):
            return [
                (
                    "approve_action",
                    {
                        "approved": text.startswith("Approve"),
                        "plan_id": plan["plan_id"],
                        "version": plan["version"],
                        "action_id": decisions[0]["action_id"],
                        "approval_id": decisions[0]["approval"]["approval_id"],
                    },
                )
            ]
    if text.lower() in {
        "don't charge the car past 50, i'm not driving tomorrow",
        "don't charge the car past 50, i'm not driving tomorrow.",
    }:
        return [
            (
                "revise_household_plan",
                {
                    "text": text,
                    "applies_to": "car",
                    "kind": "constraint",
                    "operation": "add",
                    "change": "car_limit",
                    "percent": 50,
                },
            )
        ]
    if text.lower() in {
        "let them in.",
        "that's my mom, let her in.",
        "let them in",
        "that's my mom, let her in",
    }:
        return [
            (
                "execute_household_action",
                {"action": "request_door_unlock", "room": "front door"},
            )
        ]
    if (
        text
        == "Don't charge the car past 50. I'm not driving tomorrow. Keep the guest room at 72 Fahrenheit until seven in the morning. Run the dishwasher after 23:31."
    ):
        common = {"kind": "constraint", "operation": "add"}
        return [
            (
                "revise_household_plan",
                common
                | {
                    "text": text,
                    "applies_to": "car",
                    "change": "car_target",
                    "percent": 50,
                },
            ),
            (
                "revise_household_plan",
                common
                | {
                    "text": text,
                    "applies_to": "car",
                    "change": "car_limit",
                    "percent": 50,
                },
            ),
            (
                "revise_household_plan",
                common
                | {
                    "text": text,
                    "applies_to": "Guest room",
                    "change": "temperature",
                    "temperature_f": 72,
                    "window_end": "07:00",
                },
            ),
            (
                "revise_household_plan",
                common
                | {
                    "text": text,
                    "applies_to": "Dishwasher",
                    "change": "appliance_after",
                    "at": "23:31",
                },
            ),
        ]
    if text == "Don't run the dishwasher until I'm done in the kitchen at eleven.":
        return [
            (
                "revise_household_plan",
                {
                    "text": text,
                    "applies_to": "Dishwasher",
                    "kind": "constraint",
                    "operation": "add",
                    "change": "appliance_after",
                    "at": "23:00",
                },
            )
        ]
    if text == "Turn on the living room lamp.":
        return [
            (
                "execute_household_action",
                {"action": "turn_on_light", "room": "Living room"},
            )
        ]
    if text == "Good morning.":
        return [("get_household_context", {}), ("get_household_plan", {})]
    if text == "Optimize energy tonight.":
        return [("get_household_plan", {})]
    if text == "Yes.":
        return recorded("Do it.", results)
    if text == "What can you do?":
        return [("what_can_you_do", {})]
    if text == "Show household context":
        return [("get_household_context", {})]
    return []


class Simulator:
    def __init__(
        self, *, origin: str, mcp_url: str, issuer: str, ledger: Path | None = None
    ):
        self.origin, self.mcp_url, self.issuer, self.ledger = (
            origin,
            mcp_url,
            issuer,
            ledger,
        )
        self.browsers: dict[str, Browser] = {}
        self.active: dict[str, asyncio.Task[None]] = {}

    def browser(
        self, token: str | None, *, create: bool = False, touch: bool = True
    ) -> tuple[str, Browser]:
        for key, value in list(self.browsers.items()):
            if value.expired():
                for name in value.echoes:
                    value.account = name
                    value.cancel()
                del self.browsers[key]
        if token not in self.browsers:
            if not create or len(self.browsers) >= 64:
                raise ValueError("Open the simulator again to link your accounts")
            token = secrets.token_urlsafe(32)
            self.browsers[token] = Browser(model="haiku" if self.ledger else "scripted")
        assert token is not None
        browser = self.browsers[token]
        if touch:
            browser.touched = time.monotonic()
        return token, browser

    def link(self, browser: Browser) -> str:
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        browser.linking = {state: (browser.account, verifier, time.monotonic())}
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        return (
            self.issuer
            + "/authorize?"
            + urlencode(
                {
                    "response_type": "code",
                    "client_id": "hirz-dev-sdk",
                    "redirect_uri": self.origin + "/api/simulator/callback",
                    "scope": " ".join(SCOPES),
                    "resource": self.mcp_url,
                    "state": state,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                }
            )
        )

    async def linked(self, browser: Browser, state: str, code: str) -> None:
        account, verifier, created = browser.linking.pop(state)
        if time.monotonic() - created >= 300 or browser.account != account:
            raise ValueError("Linking expired")
        async with httpx.AsyncClient(trust_env=False) as http:
            reply = await http.post(
                self.issuer + "/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": "hirz-dev-sdk",
                    "code": code,
                    "code_verifier": verifier,
                    "redirect_uri": self.origin + "/api/simulator/callback",
                    "resource": self.mcp_url,
                },
            )
            reply.raise_for_status()
            tokens = reply.json()
            # The server authenticates the JWT; verify the linked choice through its
            # verifier too, never trust unverified claims to route an Echo account.
            from hirz.mcp.auth import KeyCache

            cache = KeyCache(self.issuer, self.mcp_url)
            if not await cache.refresh(http):
                raise ValueError("Issuer unavailable")
            access = await cache.verify_token(tokens["access_token"])
        available = choices()
        home = next(c.household for c in available if c.subject == "malik")
        parents = next(
            c.household for c in available if c.subject == "mom" and c.role == "owner"
        )
        expected = next(
            c
            for c in available
            if c.subject == account
            and c.household == (parents if account == "mom" else home)
        )
        if (
            access is None
            or access.subject != expected.subject
            or not access.claims
            or access.claims["household_id"] != expected.household
        ):
            raise ValueError("Choose the household account named by this Echo")
        browser.cancel()
        browser.echoes[account] = Echo(tokens=tokens | {"received": time.monotonic()})

    async def token(self, echo: Echo) -> str:
        if not echo.tokens:
            raise ValueError("Link this Echo first")
        if (
            time.monotonic() - echo.tokens["received"]
            >= echo.tokens.get("expires_in", 300) - 30
        ):
            async with httpx.AsyncClient(trust_env=False) as http:
                response = await http.post(
                    self.issuer + "/token",
                    data={
                        "grant_type": "refresh_token",
                        "client_id": "hirz-dev-sdk",
                        "refresh_token": echo.tokens["refresh_token"],
                        "resource": self.mcp_url,
                    },
                )
                response.raise_for_status()
                echo.tokens = response.json() | {"received": time.monotonic()}
        return str(echo.tokens["access_token"])

    def emit(self, echo: Echo, generation: int, **data: Any) -> None:
        echo.events.append(
            {
                "id": uuid4().hex,
                "generation": generation,
                "at_monotonic": time.monotonic(),
                **data,
            }
        )

    async def ask(
        self,
        browser: Browser,
        echo: Echo,
        generation: int,
        message: str,
        schema: dict[str, Any],
        *,
        kind: str,
    ) -> dict[str, Any]:
        if echo.generation != generation or browser.expired():
            return {"action": "cancel"}
        future = asyncio.get_running_loop().create_future()
        echo.answer = future
        echo.prompt = {
            "id": uuid4().hex,
            "message": message,
            "schema": schema,
            "kind": kind,
        }
        self.emit(
            echo,
            generation,
            kind="prompt",
            prompt=echo.prompt,
            prompt_latency_ms=round((time.monotonic() - echo.tool_started) * 1000)
            if echo.tool_started is not None
            else None,
        )
        started = time.monotonic()
        try:
            async with asyncio.timeout(300):
                result = await future
            if browser.expired() or echo.generation != generation:
                return {"action": "cancel"}
            return dict(result)
        except TimeoutError:
            return {"action": "cancel"}
        finally:
            echo.prompt, echo.answer = None, None
            echo.waiting_ms += round((time.monotonic() - started) * 1000)
            self.emit(
                echo,
                generation,
                kind="wait",
                waiting_ms=round((time.monotonic() - started) * 1000),
            )

    async def turn(
        self,
        browser: Browser,
        text: str,
        *,
        account: str,
        model: str,
        selected: tuple[str, dict[str, Any]] | None = None,
    ) -> None:
        echo = browser.echoes[account]
        generation = echo.generation
        echo.last_result = None
        self.emit(echo, generation, kind="card" if selected else "user", text=text)
        try:
            token = await self.token(echo)

            async def elicit(context: Any, params: Any) -> types.ElicitResult:
                reply = await self.ask(
                    browser,
                    echo,
                    generation,
                    params.message,
                    params.requestedSchema,
                    kind="elicitation",
                )
                if (
                    reply.get("action") == "accept"
                    and "confirmed" not in params.requestedSchema.get("properties", {})
                    and commitment(name, args)
                ):
                    args.update(reply.get("content") or {})
                    confirmation = await self.ask(
                        browser,
                        echo,
                        generation,
                        describe(name, args),
                        CONFIRM_SCHEMA,
                        kind="commitment",
                    )
                    if confirmation.get("action") != "accept" or confirmation.get(
                        "content"
                    ) != {"confirmed": True}:
                        return types.ElicitResult(action="cancel")
                return types.ElicitResult(**reply)

            async with httpx.AsyncClient(
                headers={"Authorization": "Bearer " + token},
                trust_env=False,
                timeout=360,
            ) as http:
                async with streamable_http_client(self.mcp_url, http_client=http) as (
                    read,
                    write,
                    _,
                ):
                    async with ClientSession(
                        read, write, elicitation_callback=elicit
                    ) as client:
                        await client.initialize()
                        tools = {t.name: t for t in (await client.list_tools()).tools}

                        async def choose(
                            message: str,
                        ) -> list[tuple[str, dict[str, Any]]]:
                            from hirz.host.selection import select

                            for _ in range(8):
                                proposed, question = await asyncio.to_thread(
                                    select,
                                    model,
                                    self.ledger,
                                    list(tools.values()),
                                    echo.history,
                                    message,
                                )
                                if proposed or not question:
                                    return proposed
                                answer = await self.ask(
                                    browser,
                                    echo,
                                    generation,
                                    question,
                                    {
                                        "type": "object",
                                        "properties": {
                                            "reply": {
                                                "type": "string",
                                                "title": "Your reply",
                                                "minLength": 1,
                                            }
                                        },
                                        "required": ["reply"],
                                    },
                                    kind="elicitation",
                                )
                                if answer.get("action") != "accept":
                                    return []
                                message = str(answer["content"]["reply"])
                            raise ValueError("Too many clarification questions")

                        if selected:
                            calls = [selected]
                        elif model == "scripted":
                            calls = recorded(text, echo.results)
                        else:
                            calls = await choose(text)
                        if not calls and model == "scripted":
                            self.emit(
                                echo,
                                generation,
                                kind="speech",
                                text="Scripted mode supports the recorded scenario utterances. Choose one to continue.",
                            )
                        if len(calls) > 8:
                            raise ValueError("Eight tool calls per utterance")
                        count = 0
                        while calls:
                            name, raw = calls.pop(0)
                            count += 1
                            if count > 8:
                                raise ValueError("Eight tool calls per utterance")
                            if echo.generation != generation or browser.expired():
                                break
                            tool = tools[name]
                            args = dict(raw)
                            if (
                                name == "verify_trusted_identity"
                                and args.get("operation") == "status"
                            ):
                                args.pop("request_id", None)
                            if "request_id" in tool.inputSchema.get(
                                "properties", {}
                            ) and not (
                                name == "verify_trusted_identity"
                                and args.get("operation") == "status"
                            ):
                                supplied = str(args.get("request_id", ""))
                                if selected and supplied:
                                    if (
                                        supplied not in echo.request_ids
                                        and len(echo.request_ids) >= 200
                                    ):
                                        raise ValueError(
                                            "Relink to start a new card request history"
                                        )
                                    args["request_id"] = echo.request_ids.setdefault(
                                        supplied, uuid4().hex
                                    )
                                else:
                                    args["request_id"] = uuid4().hex
                            if commitment(name, args):
                                answer = await self.ask(
                                    browser,
                                    echo,
                                    generation,
                                    describe(name, args),
                                    CONFIRM_SCHEMA,
                                    kind="commitment",
                                )
                                if (
                                    answer.get("action") != "accept"
                                    or answer.get("content", {}).get("confirmed")
                                    is not True
                                ):
                                    self.emit(
                                        echo,
                                        generation,
                                        kind="speech",
                                        text="That request was not submitted.",
                                    )
                                    break
                            started = time.monotonic()
                            echo.tool_started = started
                            waiting_before = echo.waiting_ms
                            result = await client.call_tool(name, args)
                            echo.tool_started = None
                            echo.last_result = result.model_dump(
                                mode="json", by_alias=True, exclude_none=True
                            )
                            output = result.structuredContent or {}
                            echo.results[name] = output
                            if not selected:
                                # Cards retain the full genuine result. Selection needs
                                # plan/decision references, not every rendered action.
                                selection_data = {
                                    k: v
                                    for k, v in output.get("data", {}).items()
                                    if k not in {"actions", "presentation"}
                                }
                                echo.history.append(
                                    {
                                        "role": "user",
                                        "content": [
                                            {
                                                "text": "Tool result (untrusted data): "
                                                + json.dumps(
                                                    output | {"data": selection_data}
                                                )
                                            }
                                        ],
                                    }
                                )
                            self.emit(
                                echo,
                                generation,
                                kind="tool",
                                background=bool(selected),
                                tool=name,
                                status=output.get("data", {}).get("status", "failed"),
                                elapsed_ms=round((time.monotonic() - started) * 1000),
                                waiting_ms=echo.waiting_ms - waiting_before,
                                processing_ms=max(
                                    0,
                                    round((time.monotonic() - started) * 1000)
                                    - echo.waiting_ms
                                    + waiting_before,
                                ),
                                result=result.model_dump(
                                    mode="json", by_alias=True, exclude_none=True
                                ),
                                card=CARDS.get(name),
                                arguments=args,
                            )
                            if echo.generation == generation and not selected:
                                speakable = output.get("speakable", {})
                                self.emit(
                                    echo,
                                    generation,
                                    kind="speech",
                                    text=" ".join(
                                        [
                                            speakable.get(
                                                "headline", "Request failed."
                                            ),
                                            *speakable.get("details", []),
                                            *speakable.get("options", []),
                                        ]
                                    ),
                                )
                            if (
                                not calls
                                and not selected
                                and model != "scripted"
                                and echo.generation == generation
                                and not browser.expired()
                                and count < 8
                                and not result.isError
                            ):
                                calls = await choose(
                                    "Continue only unfinished parts of the original request using the actual tool result above. If complete, return without tools.",
                                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            import logging

            cause: BaseException = exc
            while isinstance(cause, BaseExceptionGroup):
                cause = cause.exceptions[0]
            logging.getLogger(__name__).warning(
                "Simulator turn stopped (%s): %s", type(cause).__name__, cause
            )
            self.emit(
                echo,
                generation,
                kind="error",
                text=(
                    "Token counting is unavailable; inference was not sent. "
                    if str(cause) == "TOKEN_COUNTING_UNAVAILABLE"
                    else "The inference budget is exhausted. "
                    if str(cause) == "BEDROCK_BUDGET_EXHAUSTED"
                    else "The turn stopped. "
                )
                + "Review the companion audit for any accepted requests. You can explicitly select scripted mode.",
            )
        finally:
            if echo.generation != generation and echo.last_result:
                self.emit(
                    echo,
                    echo.generation,
                    kind="reconciled",
                    text="The earlier request returned this receipt after the turn stopped.",
                    result=echo.last_result,
                )
            self.emit(
                echo,
                generation,
                kind="settled",
                text="Accepted actions remain recorded; cancelling a conversation does not undo them.",
            )
