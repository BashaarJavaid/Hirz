"""Real OAuth/MCP -> browser passkey activation -> running twin worker; offline only."""

import argparse
import asyncio
import json
import logging
import os
import socket
import sys
from pathlib import Path

import httpx
import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientMetadata
from pydantic import AnyUrl
from starlette.applications import Starlette
from starlette.routing import Route

from hirz import db
from hirz.audit import write_export
from hirz.local import read_env
from hirz.mcp.auth import SCOPES
from hirz.mcp.dev_oauth import registered_client
from scripts.smoke_household_tools import FullLogin, mcp_process
from scripts.smoke_oauth import Storage, process


async def run(folder: Path) -> None:
    if os.environ.get("HIRZ_LLM", "off") != "off":
        raise ValueError("This check requires Bedrock off")
    folder.mkdir(mode=0o700, parents=True, exist_ok=False)
    folder = folder.resolve()
    logging.disable(logging.CRITICAL)
    sockets = []
    for _ in range(4):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        sockets.append(listener)
    issuer, resource, callback, backend = [
        f"http://127.0.0.1:{s.getsockname()[1]}" for s in sockets
    ]
    port = sockets.pop().getsockname()[1]
    # The demo binds its own loopback listener.
    listener.close()
    phone = folder / "phone"
    with (folder / "demo.log").open("x") as log:
        child = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "scripts.companion_demo",
            "--origin",
            "https://hirz.example.test",
            "--port",
            str(port),
            "--artifacts-dir",
            str(phone),
            stdout=log,
            stderr=log,
            env=os.environ | {"HIRZ_LLM": "off"},
        )
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                for _ in range(300):
                    if child.returncode is not None:
                        raise RuntimeError(
                            "Disposable companion failed; inspect its private demo.log"
                        )
                    try:
                        if (
                            await client.get(backend + "/health", timeout=0.2)
                        ).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    await asyncio.sleep(0.1)
                else:
                    raise RuntimeError("Companion startup timed out")
            runtime = json.loads((phone / "runtime.json").read_text())
            config = {
                "issuer": issuer,
                "resource": resource + "/mcp",
                "callback": callback + "/callback",
                "database": db.database_url(read_env(Path(".env"))).set(
                    database=runtime["database"]
                ),
                "historical_fixture": False,
                "pem": rsa.generate_private_key(public_exponent=65537, key_size=2048)
                .private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
                .decode(),
            }
            login = FullLogin(False, str(config["callback"]))
            login.member = 0
            callback_server = uvicorn.Server(
                uvicorn.Config(
                    Starlette(routes=[Route("/callback", login.complete)]),
                    access_log=False,
                    log_level="critical",
                )
            )
            callback_task = asyncio.create_task(
                callback_server.serve(sockets=[sockets[2]])
            )
            storage = Storage(registered_client(str(config["callback"])))
            auth = OAuthClientProvider(
                str(config["resource"]),
                OAuthClientMetadata(
                    redirect_uris=[AnyUrl(str(config["callback"]))],
                    token_endpoint_auth_method="none",
                    grant_types=["authorization_code", "refresh_token"],
                    scope=" ".join(SCOPES),
                ),
                storage,
                login.redirect,
                login.callback_result,
            )
            try:
                async with (
                    process(sockets[0], config, True),
                    mcp_process(sockets[1], config),
                ):
                    async with httpx.AsyncClient(
                        auth=auth, trust_env=False, timeout=60
                    ) as http:
                        async with streamable_http_client(
                            str(config["resource"]), http_client=http
                        ) as (read, write, _):
                            async with ClientSession(read, write) as session:
                                initialized = await session.initialize()
                                await session.list_tools()
                                # Complete authenticated linking, but unactivated homes must be refused.
                                result = await session.call_tool(
                                    "get_household_context", {"scope": "people"}
                                )
                                assert result.isError and storage.tokens
                                write_export(
                                    phone / "mcp.json",
                                    {
                                        "resource": config["resource"],
                                        "token": storage.tokens.access_token,
                                        "protocol": str(initialized.protocolVersion),
                                    },
                                )
                                browser = await asyncio.create_subprocess_exec(
                                    "pnpm",
                                    "--filter",
                                    "web",
                                    "test:browser",
                                    env=os.environ
                                    | {
                                        "HIRZ_LLM": "off",
                                        "HIRZ_BROWSER_BACKEND": backend,
                                        "HIRZ_BROWSER_ARTIFACTS": str(phone),
                                        "HIRZ_BROWSER_LEGACY": "1",
                                    },
                                )
                                if await browser.wait():
                                    raise RuntimeError(
                                        "Companion browser acceptance failed"
                                    )
            finally:
                callback_server.should_exit = True
                await callback_task
        finally:
            if child.returncode is None:
                child.terminate()
            await asyncio.wait_for(child.wait(), 60)
            for listener in sockets:
                listener.close()
        if child.returncode:
            raise RuntimeError(
                "Companion export/cleanup failed; retain the database and inspect demo.log"
            )
    print(
        "PASS authenticated MCP proposal, browser passkeys, running worker and independently verified exports"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-dir", required=True, type=Path)
    asyncio.run(run(parser.parse_args().artifacts_dir))


if __name__ == "__main__":
    main()
