"""Disposable twin card fixtures and optional origin-restricted OAuth relay.

The relay is test-only, binds loopback, and fixes one linked household per URL.
Tokens remain in the authenticated Python clients; production guards are unchanged.
"""

import argparse
import asyncio
import json
import logging
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import httpx
import sqlalchemy as sa
import uvicorn
import yaml
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from hirz import db
from hirz.executor.local import compose
from hirz.executor.observations import ingest
from hirz.local import read_env
from hirz.mcp.cards import TOOLS as CARD_TOOLS
from hirz.mcp.contracts import TOOLS, Result, input_schema
from hirz.pipeline.models import Principal
from hirz.twin.disposable import disposable
from scripts.smoke_household_tools import mcp_process
from scripts.smoke_tool_budget import Client, Environment


def relay(clients: dict[str, Client]) -> Starlette:
    async def forward(request: Request) -> Response:
        headers = {
            "Access-Control-Allow-Origin": "http://localhost:8080",
            "Vary": "Origin",
            "Cache-Control": "no-store",
        }
        if (
            request.headers.get("origin") != "http://localhost:8080"
            or "authorization" in request.headers
        ):
            return Response(status_code=403)
        if request.method == "OPTIONS":
            headers.update(
                {
                    "Access-Control-Allow-Methods": "POST",
                    "Access-Control-Allow-Headers": "content-type, mcp-protocol-version, accept, mcp-session-id",
                }
            )
            return Response(status_code=204, headers=headers)
        if request.method != "POST":
            return Response(status_code=405, headers=headers)
        client = clients.get(request.path_params["household"])
        if client is None:
            return Response(status_code=404, headers=headers)
        body = await request.body()
        if len(body) > 1_048_576:
            return Response(status_code=413, headers=headers)
        client.tick()
        upstream = await client.http.post(
            client.url,
            content=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": client.protocol_version,
            },
        )
        return Response(
            upstream.content,
            status_code=upstream.status_code,
            media_type="application/json",
            headers=headers,
        )

    return Starlette(
        routes=[Route("/{household}/mcp", forward, methods=["POST", "OPTIONS", "GET"])]
    )


async def run(output: Path, serve: bool, browser_test: bool = False) -> None:
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    logging.disable(logging.CRITICAL)
    async with disposable(read_env(Path(".env"))) as connection:
        with TemporaryDirectory(prefix="hirz-cards-") as temporary:
            env = Environment(connection, Path(temporary), "demo-evening")
            try:
                await env.prepare()
                evidence_path = Path(temporary) / "card-evidence.yaml"
                retained = Path("scripts/backtest-data/results.json").resolve()
                evidence_path.write_text(
                    yaml.safe_dump(
                        {
                            "households": {
                                str(env.pipelines[0].household_id): {
                                    "results_file": str(retained),
                                    "sha256": sha256(retained.read_bytes()).hexdigest(),
                                    "profile": "comed_time_of_day",
                                    "household_variant": "solar_battery_ev",
                                    "wear_per_internal_kwh": 0.01,
                                }
                            }
                        }
                    )
                )
                env.config["card_evidence"] = str(evidence_path)
                fixtures: dict[str, Any] = {}
                inputs: dict[str, Any] = {}
                async with env.servers(), mcp_process(env.listeners[1], env.config):
                    async with httpx.AsyncClient(trust_env=False) as anonymous:
                        for name in (
                            "plan-card",
                            "approval-card",
                            "verification-card",
                            "doorbell-card",
                            "scorecard",
                        ):
                            resource = await anonymous.post(
                                env.config["resource"],
                                headers={
                                    "Accept": "application/json, text/event-stream"
                                },
                                json={
                                    "jsonrpc": "2.0",
                                    "id": 1,
                                    "method": "resources/read",
                                    "params": {"uri": "ui://hirz/" + name},
                                },
                            )
                            assert resource.status_code == 200
                            assert (
                                resource.json()["result"]["contents"][0]["mimeType"]
                                == "text/html;profile=mcp-app"
                            )
                    async with env.client(0) as home, env.client(3) as parents:

                        async def call(
                            client: Client, name: str, **args: Any
                        ) -> Result:
                            inputs[name] = args
                            answer = await client.session.call_tool(name, args)
                            assert not answer.isError, (name, answer.structuredContent)
                            return Result.model_validate(answer.structuredContent)

                        await call(
                            home, "get_household_plan", request_id="card-prepare"
                        )
                        await env.run_worker()
                        plan = await call(home, "get_household_plan")
                        assert plan.data.plan and plan.data.presentation
                        fixtures["plan"] = plan.model_dump(mode="json", by_alias=True)
                        await call(
                            home,
                            "approve_action",
                            plan_id=plan.data.plan.plan_id,
                            version=plan.data.plan.version,
                            approved=True,
                            request_id="card-consent",
                        )
                        await env.run_worker()
                        window = await call(home, "get_action_audit")
                        assert window.data.presentation
                        print(
                            "Scorecard window counts: "
                            + window.data.presentation.model_dump_json(
                                include={"counts"}
                            ),
                            flush=True,
                        )
                        # A worker can deny more than one simultaneous opening before
                        # refresh holds the rest. Snapshot one actual denied action;
                        # whole-window count semantics are tested independently.
                        p = env.pipelines[0]
                        async with connection.begin():
                            denied_id = await connection.scalar(
                                sa.select(db.audit_log.c.payload["action_id"].astext)
                                .where(
                                    p.scope(db.audit_log),
                                    db.audit_log.c.event_type.startswith(
                                        "DENY_", autoescape=True
                                    ),
                                    db.audit_log.c.payload["action_id"].astext.in_(
                                        plan.data.plan.actions
                                    ),
                                )
                                .order_by(db.audit_log.c.seq)
                                .limit(1)
                            )
                        assert denied_id, (
                            "Fixture requires an actual denied device action"
                        )
                        fixtures["scorecard"] = (
                            await call(home, "get_action_audit", action_id=denied_id)
                        ).model_dump(mode="json", by_alias=True)
                        print(
                            "Scorecard snapshot counts: "
                            + json.dumps(
                                fixtures["scorecard"]["data"]["presentation"]["counts"]
                            ),
                            flush=True,
                        )
                        p = env.pipelines[0]
                        env.loaded.world.doorbell_event(
                            "doorbell.front_door", p.clock(), "press", None
                        )
                        registry = await compose(
                            p,
                            world=env.loaded.world,
                            config="presence:twin,energy:twin",
                        )
                        await registry.start()
                        try:
                            await ingest(
                                p,
                                registry,
                                Principal(
                                    provider="demo", sub="malik", surface="scheduler"
                                ),
                            )
                        finally:
                            await registry.close()
                        fixtures["doorbell"] = (
                            await call(
                                home, "get_household_context", scope="environment"
                            )
                        ).model_dump(mode="json", by_alias=True)
                        await call(
                            home,
                            "execute_household_action",
                            action="pause_automation",
                            request_id="card-pause",
                        )
                        fixtures["approval"] = (
                            await call(
                                home,
                                "execute_household_action",
                                action="turn_on_light",
                                room="Living room",
                                request_id="card-light",
                            )
                        ).model_dump(mode="json", by_alias=True)
                        fixtures["verification"] = (
                            await call(
                                parents,
                                "assess_request_risk",
                                text="A caller from a strange number asks for five hundred dollars urgently and says to keep it secret.",
                                claimed_party=str(env.contacts[1]["display_name"]),
                                party="person",
                                request_id="card-assess",
                            )
                        ).model_dump(mode="json", by_alias=True)
                        for name, value in fixtures.items():
                            assert value["data"]["presentation"]["kind"] == name, name
                        fixture_document = dict(
                            label="Explicit disposable twin card fixtures; no security authority",
                            at=p.clock().isoformat(),
                            results=fixtures,
                            inputs={
                                kind: inputs[tool]
                                for kind, tool in {
                                    "plan": "get_household_plan",
                                    "approval": "execute_household_action",
                                    "verification": "assess_request_risk",
                                    "doorbell": "get_household_context",
                                    "scorecard": "get_action_audit",
                                }.items()
                            },
                            tools=[
                                dict(
                                    name=name,
                                    description=description,
                                    inputSchema=input_schema(schema),
                                    outputSchema=Result.model_json_schema(),
                                    _meta={
                                        "ui": {
                                            "resourceUri": "ui://hirz/"
                                            + CARD_TOOLS[name]
                                        }
                                    },
                                )
                                for name, (schema, _, description) in TOOLS.items()
                                if name in CARD_TOOLS
                            ],
                        )
                        (output / "fixtures.json").write_text(
                            json.dumps(fixture_document, indent=2)
                        )
                        if serve or browser_test:
                            print(
                                "Card relay ready on 127.0.0.1:8082 (home/mcp and parents/mcp).",
                                flush=True,
                            )
                            server = uvicorn.Server(
                                uvicorn.Config(
                                    relay({"home": home, "parents": parents}),
                                    host="127.0.0.1",
                                    port=8082,
                                    access_log=False,
                                    log_level="critical",
                                )
                            )
                            if browser_test:
                                task = asyncio.create_task(server.serve())
                                try:
                                    child = await asyncio.create_subprocess_exec(
                                        "pnpm",
                                        "exec",
                                        "playwright",
                                        "test",
                                        "tests/live.spec.ts",
                                        cwd="apps/mcp-app",
                                    )
                                    assert await child.wait() == 0, (
                                        "Authenticated browser relay test failed"
                                    )
                                finally:
                                    server.should_exit = True
                                    await task
                            else:
                                await server.serve()
                report = await env.exports(output)
                (output / "report.json").write_text(
                    json.dumps(
                        {
                            "status": "passed",
                            "fixtures": sorted(fixtures),
                            "audit": report,
                        },
                        indent=2,
                    )
                )
            finally:
                env.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--browser-test", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.artifacts_dir, args.serve, args.browser_test))


if __name__ == "__main__":
    main()
