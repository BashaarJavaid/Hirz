"""Real OAuth/MCP SDK and separate workers over disposable simulated households."""

import argparse
import asyncio
import json
import logging
import multiprocessing
import os
import socket
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, AsyncIterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
import jwt
import uvicorn
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientMetadata
from pydantic import AnyUrl
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.applications import Starlette
from starlette.routing import Route

from hirz.api.app import create_app
from hirz.audit import (
    export_document,
    fingerprint,
    verify_database,
    verify_file,
    write_export,
)
from hirz.executor.local import compose
from hirz.executor.observations import ingest
from hirz.graph.seeds import load_seeds, read_seed
from hirz.local import read_env, signing_key
from hirz.mcp.auth import SCOPES, KeyCache
from hirz.mcp.contracts import TOOLS, Result
from hirz.mcp.dev_oauth import registered_client
from hirz.mcp.profiles import load as load_profiles
from hirz.mcp.runtime import HouseholdRuntime
from hirz.pipeline.audit import AuditWriter
from hirz.pipeline.models import Principal
from hirz.twin.disposable import disposable
from hirz.twin.execution import bootstrap
from hirz.twin.scenario import LoadedScenario
from scripts.smoke_oauth import Login, Storage, process


class FullLogin(Login):
    async def redirect(self, url: str) -> None:
        parts = urlsplit(url)
        query = dict(parse_qsl(parts.query)) | {"scope": " ".join(SCOPES)}
        await super().redirect(urlunsplit(parts._replace(query=urlencode(query))))


def serve(listener: socket.socket, config: dict[str, Any]) -> None:
    logging.disable(logging.CRITICAL)
    engine = create_async_engine(config["database"], hide_parameters=True)
    runtime = HouseholdRuntime(
        engine,
        AuditWriter(signing_key(read_env(Path(".env")))),
        clock=lambda: datetime.fromisoformat(Path(config["clock_file"]).read_text()),
        profiles=load_profiles(Path(config["profiles"])),
    )
    app = create_app(
        port=listener.getsockname()[1],
        cache=KeyCache(config["issuer"], config["resource"]),
        engine=engine,
        household=runtime,
    )
    uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="critical")).run(
        sockets=[listener]
    )


@asynccontextmanager
async def mcp_process(
    listener: socket.socket, config: dict[str, Any]
) -> AsyncIterator[None]:
    child = multiprocessing.get_context("spawn").Process(
        target=serve, args=(listener, config)
    )
    child.start()
    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            for _ in range(100):
                try:
                    if (
                        await client.get(
                            config["resource"].removesuffix("/mcp") + "/health",
                            timeout=0.2,
                        )
                    ).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if not child.is_alive():
                    raise RuntimeError("MCP process failed to start")
                await asyncio.sleep(0.1)
            else:
                raise RuntimeError("MCP startup timed out")
        yield
    finally:
        child.terminate()
        await asyncio.to_thread(child.join, 5)
        if child.is_alive():
            child.kill()
            await asyncio.to_thread(child.join)
        child.close()


async def worker(database: str, scenario: str) -> None:
    child = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "from hirz.cli import main; raise SystemExit(main())",
        "worker",
        "--household",
        str(read_seed(Path("constitutions/quinn-home.yaml")).household_id),
        "--once",
        "--database",
        database,
        env=os.environ
        | {
            "HIRZ_TWIN_SCENARIO": scenario,
            "HIRZ_ADAPTERS": "presence:twin,energy:twin",
            "HIRZ_SIM_SPEED": "0",
            "HIRZ_LLM": "off",
        },
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await child.communicate()
    if child.returncode:
        raise RuntimeError("Separate worker failed: " + stdout.decode()[:500])


async def smoke(
    output: Path, *, live_selection: bool = False, budget_path: Path | None = None
) -> None:
    logging.disable(logging.CRITICAL)
    if output.exists() or output.is_symlink():
        raise ValueError("Audit export requires a new path")
    values = read_env(Path(".env"))
    listeners = []
    try:
        for _ in range(3):
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            sock.listen(128)
            listeners.append(sock)
        issuer, resource, callback = [
            f"http://127.0.0.1:{s.getsockname()[1]}" for s in listeners
        ]
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        async with disposable(values) as connection:
            fixture_dir = TemporaryDirectory(prefix="hirz-household-tools-")
            fixture = Path(fixture_dir.name) / "scenario.yaml"
            raw = yaml.safe_load(Path("scenarios/demo-evening.yaml").read_text())
            raw["household"] = str(Path("constitutions/quinn-home.yaml").resolve())
            raw["clock"]["end"] = "2026-10-14T08:00:00-05:00"
            for event in raw["timeline"]:
                if event.get("patch"):
                    event["patch"] = str((Path("scenarios") / event["patch"]).resolve())
            fixture.write_text(yaml.safe_dump(raw))
            loaded = LoadedScenario(fixture)
            loaded.world.clock.set_speed(0)
            p = await bootstrap(loaded, connection)
            profiles = Path(fixture_dir.name) / "profiles.yaml"
            profiles.write_text(
                yaml.safe_dump(
                    {
                        "households": {
                            str(p.household_id): {
                                "night": {
                                    "settings": [
                                        {
                                            "action": "set_temperature",
                                            "room": "Living room",
                                            "temperature_f": 72,
                                        },
                                        {
                                            "action": "turn_on_light",
                                            "room": "Living room",
                                        },
                                    ]
                                }
                            }
                        }
                    }
                )
            )  # Explicit disposable test bundle; not product defaults.
            await load_seeds(
                connection,
                [read_seed(Path("constitutions/quinn-parents.yaml"))],
                lambda: p.clock() - timedelta(seconds=2),
            )
            registry = await compose(
                p, world=loaded.world, config="presence:twin,energy:twin"
            )
            await registry.start()
            try:
                await ingest(
                    p,
                    registry,
                    Principal(provider="demo", sub="malik", surface="scheduler"),
                )
            finally:
                await registry.close()
            clock_file = Path(fixture_dir.name) / "clock.txt"
            clock_file.write_text(p.clock().isoformat())
            config: dict[str, Any] = dict(
                issuer=issuer,
                resource=resource + "/mcp",
                callback=callback + "/callback",
                pem=pem,
                database=connection.engine.url,
                at=p.clock().isoformat(),
                clock_file=str(clock_file),
                profiles=str(profiles),
            )
            login = FullLogin(False, config["callback"])
            login.member = 0
            callback_app = Starlette(routes=[Route("/callback", login.complete)])
            callback_server = uvicorn.Server(
                uvicorn.Config(callback_app, access_log=False, log_level="critical")
            )
            callback_task = asyncio.create_task(
                callback_server.serve(sockets=[listeners[2]])
            )
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
            try:
                async with (
                    process(listeners[0], config, True),
                    mcp_process(listeners[1], config),
                ):
                    async with httpx.AsyncClient(
                        auth=auth, trust_env=False, timeout=60
                    ) as http:
                        async with streamable_http_client(
                            config["resource"], http_client=http
                        ) as (read, write, _):
                            async with ClientSession(read, write) as session:
                                await session.initialize()
                                tools = (await session.list_tools()).tools
                                assert {t.name for t in tools} == set(TOOLS)

                                async def call(
                                    name: str, arguments: dict[str, Any]
                                ) -> Result:
                                    result = await session.call_tool(name, arguments)
                                    if result.isError:
                                        print(
                                            "TOOL_FAILURE",
                                            name,
                                            result.structuredContent,
                                            flush=True,
                                        )
                                    assert not result.isError, (name, result)
                                    Draft202012Validator(
                                        Result.model_json_schema()
                                    ).validate(result.structuredContent)
                                    return Result.model_validate(
                                        result.structuredContent
                                    )

                                context = await call(
                                    "get_household_context", {"scope": "all"}
                                )
                                assert (
                                    context.data.context
                                    and context.data.context.household_id
                                    == p.household_id
                                )
                                print(
                                    "PASS SDK OAuth linking; twelve typed tools; scoped context",
                                    flush=True,
                                )
                                proposal = dict(
                                    text="Never unlock for unexpected visitors.",
                                    request_id="proposal",
                                )
                                recorded = await call(
                                    "propose_household_rule", proposal
                                )
                                assert recorded.data.status == "recorded"
                                assert (
                                    await call("propose_household_rule", proposal)
                                    == recorded
                                )
                                request = await call(
                                    "get_household_plan",
                                    {
                                        "request_id": "first-plan",
                                        "objective": "cheapest",
                                    },
                                )
                                assert request.data.status == "preparing"
                                await worker(
                                    str(connection.engine.url.database), str(fixture)
                                )
                                current = await call("get_household_plan", {})
                                assert current.data.plan, current
                                plan = current.data.plan
                                assert plan.goals[0] == "minimize_cost_and_wear"
                                await call("explain_plan", {"plan_id": plan.plan_id})
                                for focus in (
                                    plan.goals[0],
                                    plan.actions[0],
                                    "conflicts",
                                ):
                                    await call(
                                        "explain_plan",
                                        {"plan_id": plan.plan_id, "focus": focus},
                                    )
                                invalid = await session.call_tool(
                                    "propose_household_rule",
                                    {
                                        "text": "A proposal",
                                        "request_id": "invalid",
                                        "role": "owner",
                                    },
                                )
                                assert invalid.isError
                                assert (
                                    Result.model_validate(
                                        invalid.structuredContent
                                    ).data.code
                                    == "INVALID_INPUT"
                                )
                                await call(
                                    "evaluate_permission",
                                    {
                                        "action": "pause_automation",
                                        "request_id": "preview",
                                    },
                                )
                                print(
                                    "PASS first plan prepared by separate worker; source=simulated",
                                    flush=True,
                                )
                                await call(
                                    "get_household_plan",
                                    {"objective": "greenest", "request_id": "priority"},
                                )
                                old_consent = await call(
                                    "approve_action",
                                    dict(
                                        plan_id=plan.plan_id,
                                        version=plan.version,
                                        approved=True,
                                        request_id="old-priority-consent",
                                    ),
                                )
                                assert old_consent.data.code == "PLAN_CHANGED"
                                await worker(
                                    str(connection.engine.url.database), str(fixture)
                                )
                                updated = await call("get_household_plan", {})
                                assert (
                                    updated.data.plan
                                    and updated.data.plan.goals[0]
                                    == "minimize_grid_import"
                                ), updated
                                plan = updated.data.plan
                                print(
                                    "PASS objective change survived worker restart; exact old consent refused",
                                    flush=True,
                                )
                                constraint = await call(
                                    "revise_household_plan",
                                    dict(
                                        text="Don't charge past fifty",
                                        applies_to="car",
                                        kind="one_time",
                                        operation="add",
                                        change="car_limit",
                                        percent=50,
                                        request_id="revise",
                                    ),
                                )
                                assert constraint.data.status == "recorded"
                                stale = await call(
                                    "approve_action",
                                    dict(
                                        plan_id=plan.plan_id,
                                        version=plan.version,
                                        approved=True,
                                        request_id="stale",
                                    ),
                                )
                                assert stale.data.code == "PLAN_CHANGED", stale
                                await worker(
                                    str(connection.engine.url.database), str(fixture)
                                )
                                print(
                                    "PASS revision/approval race refused; separate worker restarted",
                                    flush=True,
                                )
                                ambiguous = await call(
                                    "execute_household_action",
                                    dict(
                                        action="set_temperature", request_id="clarify"
                                    ),
                                )
                                assert ambiguous.data.status == "clarification"
                                assessed = await call(
                                    "assess_request_risk",
                                    dict(
                                        text="Send five hundred dollars immediately from a strange number",
                                        claimed_party="Malik",
                                        party="person",
                                        request_id="risk",
                                    ),
                                )
                                assert (
                                    assessed.data.case
                                    and assessed.data.case.verification is None
                                )
                                assert (
                                    "number" not in assessed.speakable.model_dump_json()
                                )
                                await call(
                                    "verify_trusted_identity",
                                    {
                                        "operation": "status",
                                        "case_id": assessed.data.case.case_id,
                                    },
                                )
                                door = await call(
                                    "execute_household_action",
                                    dict(
                                        action="request_door_unlock",
                                        minutes=10,
                                        request_id="door",
                                    ),
                                )
                                assert door.data.status in {"phone_required", "denied"}
                                light = await call(
                                    "execute_household_action",
                                    {
                                        "action": "turn_on_light",
                                        "room": "Living room",
                                        "request_id": "light",
                                    },
                                )
                                assert (
                                    light.data.decision
                                    and light.data.decision.status == "executing"
                                ), light
                                profile = await call(
                                    "execute_household_action",
                                    dict(
                                        action="apply_profile",
                                        profile="night",
                                        request_id="profile",
                                    ),
                                )
                                assert len(profile.data.decisions) == 2, profile
                                # This fixture has no sleeping observation: the
                                # thermostat fails closed; the light can proceed.
                                assert [d.decision for d in profile.data.decisions] == [
                                    "deny",
                                    "execute",
                                ], profile
                                await worker(
                                    str(connection.engine.url.database), str(fixture)
                                )
                                import sqlalchemy as sa

                                from hirz import db

                                async with connection.begin():
                                    assert (
                                        await connection.scalar(
                                            sa.select(
                                                db.actions.c.execution_status
                                            ).where(
                                                db.actions.c.household_id
                                                == p.household_id,
                                                db.actions.c.action_id
                                                == light.data.decision.action_id,
                                            )
                                        )
                                        == "verified"
                                    )
                                    for device in profile.data.decisions:
                                        assert await connection.scalar(
                                            sa.select(
                                                db.actions.c.execution_status
                                            ).where(
                                                db.actions.c.household_id
                                                == p.household_id,
                                                db.actions.c.action_id
                                                == device.action_id,
                                            )
                                        ) == (
                                            "verified"
                                            if device.status == "executing"
                                            else None
                                        )
                                # Device writes advance the twin by microseconds.
                                # The MCP test clock must move beyond those events.
                                clock_file.write_text(
                                    (p.clock() + timedelta(seconds=1)).isoformat()
                                )
                                assert (
                                    await call(
                                        "execute_household_action",
                                        dict(
                                            action="apply_profile",
                                            profile="night",
                                            request_id="profile",
                                        ),
                                    )
                                    == profile
                                )
                                print(
                                    "PASS profile device denial/execution verified; retry repeated no effects",
                                    flush=True,
                                )
                                paused = await call(
                                    "execute_household_action",
                                    dict(action="pause_automation", request_id="pause"),
                                )
                                assert (
                                    paused.data.decision
                                    and paused.data.decision.decision == "execute"
                                )
                                await call("get_action_audit", {"limit": 20})
                                print(
                                    "PASS proposal retries, ambiguity, advisory privacy, security and pause",
                                    flush=True,
                                )
                                assert storage.tokens
                                read_claims = jwt.decode(
                                    storage.tokens.access_token,
                                    options={"verify_signature": False},
                                )
                                read_claims["scope"] = "hirz:read"
                                read_token = jwt.encode(
                                    read_claims,
                                    pem,
                                    algorithm="RS256",
                                    headers=jwt.get_unverified_header(
                                        storage.tokens.access_token
                                    ),
                                )
                                async with httpx.AsyncClient(
                                    trust_env=False
                                ) as limited:
                                    refused = await limited.post(
                                        config["resource"],
                                        headers={
                                            "Authorization": "Bearer " + read_token,
                                            "Accept": "application/json, text/event-stream",
                                        },
                                        json={
                                            "jsonrpc": "2.0",
                                            "id": 99,
                                            "method": "tools/call",
                                            "params": {
                                                "name": "execute_household_action",
                                                "arguments": {
                                                    "action": "pause_automation",
                                                    "request_id": "read-only",
                                                },
                                            },
                                        },
                                    )
                                assert refused.status_code == 403
                                print(
                                    "PASS read-only OAuth token refused act tool with HTTP 403",
                                    flush=True,
                                )
                                if live_selection:
                                    assert storage.tokens and budget_path
                                    from scripts.tool_selection import run_selection

                                    await asyncio.to_thread(
                                        run_selection,
                                        config["resource"],
                                        storage.tokens.access_token,
                                        budget_path,
                                    )
                # A fresh MCP process reads the same durable receipt with a still-valid token.
                assert storage.tokens
                async with (
                    process(listeners[0], config, True),
                    mcp_process(listeners[1], config),
                ):
                    async with httpx.AsyncClient(
                        headers={
                            "Authorization": "Bearer " + storage.tokens.access_token
                        },
                        trust_env=False,
                    ) as http:
                        async with streamable_http_client(
                            config["resource"], http_client=http
                        ) as (read, write, _):
                            async with ClientSession(read, write) as session:
                                await session.initialize()
                                result = await session.call_tool(
                                    "propose_household_rule", proposal
                                )
                                assert (
                                    Result.model_validate(result.structuredContent)
                                    == recorded
                                )
                print("PASS durable retry after MCP process restart", flush=True)
            finally:
                callback_server.should_exit = True
                await callback_task
            summary, rows = await verify_database(
                connection, p.household_id, p.audit.key.public_key(), collect=True
            )
            write_export(
                output, export_document(p.household_id, p.audit.key.public_key(), rows)
            )
            trust = fingerprint(p.audit.key.public_key())
            verified = verify_file(output, p.household_id, trusted_fingerprint=trust)
            assert summary["status"] == verified["status"] == "valid"
            fixture_dir.cleanup()
            print(
                json.dumps(
                    dict(
                        household_tools="PASS",
                        signed_rows=len(rows),
                        offline="valid",
                        trusted_fingerprint=trust,
                        audit_export=str(output),
                        development_database="unchanged",
                    )
                ),
                flush=True,
            )
    finally:
        for sock in listeners:
            sock.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-output", type=Path, required=True)
    parser.add_argument("--live-selection", action="store_true")
    parser.add_argument("--budget-ledger", type=Path)
    args = parser.parse_args()
    if args.live_selection and not args.budget_ledger:
        parser.error("Live selection needs the retained task budget ledger")
    try:
        asyncio.run(
            smoke(
                args.audit_output,
                live_selection=args.live_selection,
                budget_path=args.budget_ledger,
            )
        )
    except Exception as exc:
        import traceback

        def diagnostic(error: BaseException) -> None:
            if isinstance(error, BaseExceptionGroup):
                for child in error.exceptions:
                    diagnostic(child)
            else:
                print(
                    type(error).__name__,
                    [
                        (f.name, f.lineno)
                        for f in traceback.extract_tb(error.__traceback__)
                    ][-5:],
                )
                if isinstance(error, AssertionError):
                    print(str(error))

        diagnostic(exc)
        parser.exit(
            1,
            f"FAIL household tools smoke ({type(exc).__name__}); private exception details withheld.\n",
        )


if __name__ == "__main__":
    main()
