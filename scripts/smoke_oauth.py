"""Official SDK linking across two processes and a disposable PostgreSQL database."""

import argparse
import asyncio
import logging
import multiprocessing
import re
import socket
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import sqlalchemy as sa
import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from pydantic import AnyUrl
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from hirz import db
from hirz.api.app import create_app
from hirz.graph.models import now
from hirz.graph.seeds import load_seeds, read_seed, untouched
from hirz.local import read_env
from hirz.mcp.auth import SCOPES, KeyCache, identity_context
from hirz.mcp.dev_oauth import (
    KEY_NAME,
    DevProvider,
    create_issuer,
    registered_client,
    signing_key,
)
from hirz.twin.disposable import disposable


async def oauth_probe() -> dict[str, Any]:
    from mcp.server.auth.middleware.auth_context import get_access_token

    identity = identity_context.get()
    assert identity is not None and get_access_token() is not None
    return {
        "speakable": {
            "headline": "Your simulated account is linked.",
            "details": [],
            "options": [],
        },
        "data": {
            "household": str(identity.household_id),
            "member": identity.member.member_id,
            "role": identity.member.role,
        },
    }


def serve(listener: socket.socket, config: dict[str, Any], issuer: bool) -> None:
    logging.disable(logging.CRITICAL)
    port = listener.getsockname()[1]
    if issuer:
        app = create_issuer(
            DevProvider(
                signing_key({KEY_NAME: config["pem"]}),
                issuer=config["issuer"],
                resource=config["resource"],
                callback=config["callback"],
            ),
            port=port,
        )
    else:
        engine = create_async_engine(
            config["database"],
            hide_parameters=True,
            connect_args={"connect_timeout": 2},
        )
        app = create_app(
            port=port,
            cache=KeyCache(config["issuer"], config["resource"]),
            engine=engine,
            register=lambda server: server.add_tool(oauth_probe),
        )
    uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="critical")).run(
        sockets=[listener]
    )


@asynccontextmanager
async def process(
    listener: socket.socket, config: dict[str, Any], issuer: bool
) -> AsyncIterator[None]:
    child = multiprocessing.get_context("spawn").Process(
        target=serve, args=(listener, config, issuer)
    )
    child.start()
    try:
        url = (
            config["issuer"] + "/.well-known/oauth-authorization-server"
            if issuer
            else config["resource"].removesuffix("/mcp") + "/health"
        )
        async with httpx.AsyncClient(trust_env=False) as client:
            for _ in range(100):
                try:
                    if (await client.get(url, timeout=0.2)).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if not child.is_alive():
                    raise RuntimeError("Smoke server exited")
                await asyncio.sleep(0.1)
            else:
                raise RuntimeError("Smoke server did not start")
        yield
    finally:
        child.terminate()
        await asyncio.to_thread(child.join, 5)
        if child.is_alive():
            child.kill()
            await asyncio.to_thread(child.join)
        child.close()


@dataclass
class Storage:
    client: OAuthClientInformationFull
    tokens: OAuthToken | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self.client

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.client = client_info


class Login:
    def __init__(self, browser: bool, callback: str) -> None:
        self.browser, self.callback = browser, callback
        self.authorization_url: str | None = None
        self.returned: asyncio.Future[tuple[str, str | None]] = (
            asyncio.get_running_loop().create_future()
        )
        self.denied = asyncio.Event()
        self.decision = "approve"
        self.member = 1  # Mom at Malik's home; second SDK link selects parents' home.

    async def redirect(self, url: str) -> None:
        self.authorization_url = url
        if self.browser:
            print(
                f"Browser {self.decision}: open {self.callback.removesuffix('/callback')}/",
                flush=True,
            )
            return
        async with httpx.AsyncClient(trust_env=False) as client:
            response = await client.get(url)
            assert response.status_code == 302, "Authorization did not redirect"
            page = await client.get(response.headers["location"])
            hidden = dict(
                re.findall(r'name="(transaction|csrf)" value="([^"]+)"', page.text)
            )
            assert len(hidden) == 2 and "simulated login" in page.text
            response = await client.post(
                str(page.url).split("?", 1)[0],
                data=hidden | {"member": str(self.member), "decision": self.decision},
            )
            await client.get(response.headers["location"])

    async def callback_result(self) -> tuple[str, str | None]:
        return await asyncio.wait_for(self.returned, 300)

    async def landing(self, request: Request) -> Response:
        if self.authorization_url is None:
            return HTMLResponse("<h1>Waiting for SDK linking</h1>")
        return RedirectResponse(
            self.authorization_url, headers={"Cache-Control": "no-store"}
        )

    async def complete(self, request: Request) -> Response:
        query = request.query_params
        if "error" in query:
            self.denied.set()
            if not self.returned.done():
                self.returned.set_exception(ValueError("Consent denied"))
            return HTMLResponse(
                "<h1>Consent denied</h1><p>No household access was granted.</p>",
                headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
            )
        if not self.returned.done():
            self.returned.set_result((query["code"], query.get("state")))
        return HTMLResponse(
            "<h1>Callback complete</h1><p>The SDK is finishing simulated account linking.</p>",
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )


async def link(
    config: dict[str, Any], login: Login
) -> tuple[dict[str, Any], OAuthToken]:
    storage = Storage(registered_client(config["callback"]))
    auth = OAuthClientProvider(
        config["resource"],
        OAuthClientMetadata(
            redirect_uris=[AnyUrl(config["callback"])],
            token_endpoint_auth_method="none",
            grant_types=["authorization_code", "refresh_token"],
            scope=" ".join(SCOPES),
        ),
        storage,
        login.redirect,
        login.callback_result,
    )
    async with httpx.AsyncClient(auth=auth, trust_env=False, timeout=310) as client:
        async with streamable_http_client(config["resource"], http_client=client) as (
            read,
            write,
            sid,
        ):
            async with ClientSession(read, write) as session:
                await session.initialize()
                assert sid() is None
                assert {t.name for t in (await session.list_tools()).tools} == {
                    "what_can_you_do",
                    "oauth_probe",
                }
                result = await session.call_tool("oauth_probe", {})
                assert not result.isError and result.structuredContent is not None
                assert auth.context.protected_resource_metadata is not None
                assert auth.context.oauth_metadata is not None
                assert storage.tokens is not None
                first_refresh = storage.tokens.refresh_token
                # Exercise the official SDK's automatic refresh without waiting five minutes.
                auth.context.token_expiry_time = time.time() - 1
                again = await session.call_tool("oauth_probe", {})
                assert again.structuredContent == result.structuredContent
                assert storage.tokens.refresh_token != first_refresh
                print(
                    "PASS SDK discovery -> simulated consent -> S256 exchange -> authenticated MCP -> SDK refresh",
                    flush=True,
                )
                print("resolved=" + str(result.structuredContent["data"]), flush=True)
                return result.structuredContent, storage.tokens


async def run(browser: bool) -> None:
    logging.disable(logging.CRITICAL)
    listeners = []
    try:
        for _ in range(3):
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            listener.listen(128)
            listeners.append(listener)
        issuer_url, resource_base, callback_base = [
            f"http://127.0.0.1:{s.getsockname()[1]}" for s in listeners
        ]
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        values = read_env(Path(".env"))
        async with disposable(values) as connection:
            seeds = [
                read_seed(Path(f"constitutions/{name}.yaml"))
                for name in ("quinn-home", "quinn-parents")
            ]
            at = now()
            await load_seeds(connection, seeds, lambda: at)
            config: dict[str, Any] = {
                "issuer": issuer_url,
                "resource": resource_base + "/mcp",
                "callback": callback_base + "/callback",
                "pem": pem,
                "database": connection.engine.url,
            }
            login = Login(browser, config["callback"])
            callback_app = Starlette(
                routes=[Route("/", login.landing), Route("/callback", login.complete)]
            )
            callback_server = uvicorn.Server(
                uvicorn.Config(callback_app, access_log=False, log_level="critical")
            )
            callback_task = asyncio.create_task(
                callback_server.serve(sockets=[listeners[2]])
            )
            try:
                async with process(listeners[0], config, True):
                    async with process(listeners[1], config, False):
                        first, issued = await link(config, login)
                        assert (
                            first["data"]["household"] == str(seeds[0].household_id)
                            and first["data"]["role"] == "adult"
                        )
                        login.returned = asyncio.get_running_loop().create_future()
                        login.member = 3
                        # Browser verification covers approval and denial; the second home's
                        # link is driven through the same SDK and HTML form automatically.
                        login.browser = False
                        second, _ = await link(config, login)
                        assert (
                            second["data"]["household"] == str(seeds[1].household_id)
                            and second["data"]["role"] == "owner"
                        )
                        login.returned = asyncio.get_running_loop().create_future()
                        login.decision, login.browser = "deny", browser
                        try:
                            await link(config, login)
                        except Exception:
                            assert login.denied.is_set()
                        else:
                            raise AssertionError("Denied consent linked an account")
                        print(
                            "PASS SDK denial; same subject resolves adult/owner in two homes",
                            flush=True,
                        )
                        async with httpx.AsyncClient(trust_env=False) as client:
                            headers = {
                                "accept": "application/json, text/event-stream",
                                "authorization": "Bearer " + issued.access_token,
                            }
                            call = {
                                "jsonrpc": "2.0",
                                "id": 1,
                                "method": "tools/call",
                                "params": {"name": "oauth_probe", "arguments": {}},
                            }
                            import jwt

                            forged_claims = jwt.decode(
                                issued.access_token, options={"verify_signature": False}
                            ) | {"aud": resource_base + "/wrong"}
                            bad = jwt.encode(
                                forged_claims,
                                key,
                                algorithm="RS256",
                                headers={
                                    "kid": jwt.get_unverified_header(
                                        issued.access_token
                                    )["kid"],
                                    "typ": "at+jwt",
                                },
                            )
                            response = await client.post(
                                config["resource"],
                                json=call,
                                headers=headers | {"authorization": "Bearer " + bad},
                            )
                            assert response.status_code == 401
                            print("PASS wrong audience -> 401", flush=True)
                        assert all(
                            [await untouched(connection, seed, at) for seed in seeds]
                        )
                        assert (
                            await connection.scalar(
                                sa.select(sa.func.count()).select_from(db.actions)
                            )
                            == 0
                        )
                        print(
                            "PASS zero household changes, audit events and device actions",
                            flush=True,
                        )
            finally:
                callback_server.should_exit = True
                await callback_task
    finally:
        for listener in listeners:
            listener.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Wait for browser approval and denial via the SDK callback harness",
    )
    args = parser.parse_args()
    try:
        asyncio.run(run(args.browser))
    except Exception:
        parser.exit(
            1,
            "FAIL OAuth smoke; credentials and upstream exception details withheld.\n",
        )


if __name__ == "__main__":
    main()
