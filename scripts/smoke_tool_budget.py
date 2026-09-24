"""Item 26: authenticated local tool latency and isolation, with private evidence."""

import argparse
import asyncio
import json
import logging
import math
import os
import platform
import socket
import subprocess
import sys
import time
from collections import defaultdict
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import UUID, uuid4

import httpx
import jwt
import sqlalchemy as sa
import uvicorn
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.auth import OAuthClientMetadata
from pydantic import AnyUrl
from sqlalchemy.ext.asyncio import AsyncConnection
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from hirz import db
from hirz.audit import (
    export_document,
    fingerprint,
    verify_database,
    verify_file,
    write_export,
)
from hirz.constitution.boundary import Dogwood
from hirz.executor.local import compose
from hirz.executor.observations import ingest
from hirz.graph.models import ContactChannel, TrustedContact
from hirz.graph.seeds import load_seeds, read_seed
from hirz.local import read_env, signing_key
from hirz.mcp.auth import SCOPES
from hirz.mcp.contracts import TOOLS, Result
from hirz.mcp.dev_oauth import registered_client
from hirz.mcp.trust import advance
from hirz.pipeline.audit import AuditWriter
from hirz.pipeline.models import Action, Principal
from hirz.pipeline.service import Pipeline, PolicyBundle
from hirz.twin.disposable import disposable
from hirz.twin.execution import bootstrap
from hirz.twin.scenario import LoadedScenario
from scripts.smoke_household_tools import FullLogin, mcp_process
from scripts.smoke_oauth import Storage, process
from scripts.tool_selection import CASES

WARMUPS = 5
SAMPLES = 100
BUDGET_MS = 250


def statistics(samples: list[float]) -> dict[str, Any]:
    """Nearest-rank percentile; preserve every sample, including outliers."""
    ordered = sorted(samples)
    assert ordered and all(math.isfinite(x) and x >= 0 for x in ordered)
    n = len(ordered)
    return dict(
        count=n,
        min_ms=ordered[0],
        median_ms=(ordered[(n - 1) // 2] + ordered[n // 2]) / 2,
        p95_ms=ordered[math.ceil(n * 0.95) - 1],
        max_ms=ordered[-1],
        samples_ms=samples,
    )


def write_json(path: Path, value: Any) -> None:
    with open(path, "x", opener=lambda p, f: os.open(p, f, 0o600)) as stream:
        json.dump(value, stream, indent=2)


class Client:
    def __init__(
        self,
        session: ClientSession,
        storage: Storage,
        tick: Callable[[], None],
        auth: OAuthClientProvider,
    ):
        self.session, self.storage = session, storage
        self.auth = auth
        self.tick = tick
        self.samples: dict[str, list[float]] = defaultdict(list)
        self.tools: dict[str, str] = {}
        self.inputs: dict[str, dict[str, Any]] = {}
        self.measuring = False

    async def call(
        self,
        case: str,
        tool: str,
        args: dict[str, Any],
        *,
        error: bool = False,
    ) -> Result:
        self.tick()
        if self.storage.tokens:
            claims = jwt.decode(
                self.storage.tokens.access_token, options={"verify_signature": False}
            )
            if claims["exp"] - time.time() < 30:
                # Refresh through the SDK before timing; server token lifetime is
                # unchanged. Expire only the client's cached expiry estimate.
                self.auth.context.token_expiry_time = time.time() - 1
                await self.session.call_tool(
                    "get_household_context", {"scope": "people"}
                )
        start = time.perf_counter_ns()
        raw = await self.session.call_tool(tool, args)
        elapsed = (time.perf_counter_ns() - start) / 1_000_000
        if self.measuring and case:
            self.samples[case].append(elapsed)
            self.tools[case] = tool
            self.inputs[case] = args
        assert bool(raw.isError) == error, (case, "unexpected MCP error status")
        result = Result.model_validate(raw.structuredContent)
        return result


class Environment:
    """One disposable database, two real linked accounts, one MCP process."""

    def __init__(self, connection: AsyncConnection, directory: Path, scenario: str):
        self.connection, self.directory, self.scenario = connection, directory, scenario
        self.config: dict[str, Any] = {}
        self.pipelines: list[Pipeline] = []
        self.contacts: list[dict[str, Any]] = []
        self.loaded: LoadedScenario
        self.listeners: list[socket.socket] = []
        self.login: FullLogin | None = None
        self.isolation_records: list[dict[str, Any]] = []
        self.mirror_records: list[dict[str, Any]] = []
        self.mirror_storage: Storage

    async def prepare_mirror(self) -> None:
        """Author-approved, initial disposable copy; never a runtime cloning API."""
        from copy import copy
        from uuid import uuid5

        from hirz.graph.models import AssetPolicy
        from hirz.graph.repository import GraphRepository
        from hirz.twin.world import TwinWorld

        home = self.pipelines[0]
        mirror_id = uuid4()
        at = home.clock() - timedelta(seconds=1)
        seed = read_seed(Path("constitutions/quinn-home.yaml"))
        models = seed.models(at)
        identities = {str(home.household_id): str(mirror_id)}
        for rows in models.values():
            for model in rows:
                if hasattr(model, "id"):
                    identities.setdefault(
                        str(model.id), str(uuid5(mirror_id, str(model.id)))
                    )

        def remap(value: Any) -> Any:
            if isinstance(value, dict):
                return {identities.get(str(k), k): remap(v) for k, v in value.items()}
            if isinstance(value, list):
                return [remap(v) for v in value]
            return identities.get(value, value) if isinstance(value, str) else value

        repository = GraphRepository(self.connection, mirror_id)
        async with repository.write(lambda: at):
            for name, rows in models.items():
                for model in rows:
                    values = remap(model.model_dump(mode="json"))
                    if name == "households":
                        values["name"] = "Explicit disposable isolation fixture"
                    if name == "member_accounts":
                        values["sub"] += "-item26"
                    if name == "assets":
                        values["room_kind"] = "other"
                    await repository.put(name, type(model).model_validate(values))
            await repository.put(
                "asset_policies",
                AssetPolicy(
                    id=uuid4(),
                    household_id=mirror_id,
                    asset_id=UUID(identities[str(self.loaded.ref("assets", "ev"))]),
                    needed_by=self.loaded.time("+1d 06:30"),
                ),
            )
            await self.connection.execute(
                db.constitution_versions.insert().values(
                    household_id=mirror_id,
                    version=seed.version,
                    yaml=seed.yaml,
                    hash=seed.hash,
                )
            )
        mirror = copy(self.loaded)
        mirror.references = {
            kind: {slug: UUID(identities[str(ident)]) for slug, ident in refs.items()}
            for kind, refs in self.loaded.references.items()
        }
        original = self.loaded.world

        def mapped(model: Any) -> Any:
            return type(model).model_validate(remap(model.model_dump(mode="json")))

        mirror.world = TwinWorld(
            mapped(original.household).model_copy(
                update={"name": "Explicit disposable isolation fixture"}
            ),
            members=tuple(mapped(m) for m in original.members.values()),
            assets=tuple(mapped(a) for a in original.assets.values()),
            bindings=tuple(mapped(b) for b in original.bindings.values()),
            contacts=tuple(mapped(c) for c in original.contacts.values()),
            channels=(),
            calendar=tuple(mapped(e) for e in original.calendar),
            config=mapped(original.config),
            clock=original.clock,
        )
        self.mirror = mirror
        boundary = Dogwood()
        p = Pipeline(
            self.connection,
            await PolicyBundle.validate(mirror_id, mirror.policy, boundary),
            boundary,
            home.audit,
            home.clock,
        )
        self.pipelines.append(p)
        registry = await compose(
            p, world=mirror.world, config="presence:twin,energy:twin"
        )
        await registry.start()
        try:
            await ingest(
                p,
                registry,
                Principal(provider="demo", sub="malik-item26", surface="scheduler"),
            )
        finally:
            await registry.close()

    async def prepare(self) -> None:
        raw = yaml.safe_load(Path(f"scenarios/{self.scenario}.yaml").read_text())
        evening = yaml.safe_load(Path("scenarios/demo-evening.yaml").read_text())
        raw["household"] = str(Path("constitutions/quinn-home.yaml").resolve())
        raw["clock"]["end"] = raw["clock"]["end"].replace("T07:00:", "T08:00:")
        # Explicit benchmark counterpart: same approved rooms/binding/deadline,
        # Hourly's original dates, rates and weather. No source scenario is edited.
        raw["execution"] = evening["execution"]
        raw["bindings"] = evening["bindings"]
        for event in raw["timeline"]:
            if event.get("patch"):
                event["patch"] = str((Path("scenarios") / event["patch"]).resolve())
        self.fixture = self.directory / "scenario.yaml"
        self.fixture.write_text(yaml.safe_dump(raw))
        self.loaded = LoadedScenario(self.fixture)
        self.loaded.world.clock.set_speed(0)
        p = await bootstrap(self.loaded, self.connection)
        self.pipelines.append(p)
        parents = read_seed(Path("constitutions/quinn-parents.yaml"))
        await load_seeds(
            self.connection, [parents], lambda: p.clock() - timedelta(seconds=2)
        )
        boundary = Dogwood()
        from hirz.constitution.schema import loads

        other = Pipeline(
            self.connection,
            await PolicyBundle.validate(
                parents.household_id, loads(parents.yaml), boundary
            ),
            boundary,
            AuditWriter(signing_key(read_env(Path(".env")))),
            p.clock,
        )
        self.pipelines.append(other)
        for pipeline in self.pipelines:
            # Item 25's explicitly verified, simulated, initial channel fixture.
            async with pipeline.repo.write(lambda: p.clock() - timedelta(seconds=1)):
                snapshot = await pipeline.snapshot(p.clock())
                if not snapshot.data["trusted_contacts"]:
                    fixture_contact = TrustedContact(
                        household_id=pipeline.household_id,
                        id=uuid4(),
                        display_name="Trusted relative",
                        relationship="relative",
                    )
                    await pipeline.repo.put("trusted_contacts", fixture_contact)
                    contact = fixture_contact.model_dump(mode="json")
                else:
                    contact = snapshot.data["trusted_contacts"][0]
                self.contacts.append(contact)
                await pipeline.repo.put(
                    "contact_channels",
                    ContactChannel(
                        household_id=pipeline.household_id,
                        id=uuid4(),
                        contact_id=UUID(str(contact["id"])),
                        kind="hirz_app",
                        value_hash=sha256(
                            b"explicit simulated item 26 fixture"
                        ).hexdigest(),
                        verified_at=p.clock() - timedelta(seconds=1),
                        source="twin",
                    ),
                )
        registry = await compose(
            p, world=self.loaded.world, config="presence:twin,energy:twin"
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
        self.clock_file = self.directory / "clock.txt"
        self.clock_file.write_text(p.clock().isoformat())
        profiles = self.directory / "profiles.yaml"
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
                                    {"action": "turn_on_light", "room": "Living room"},
                                ]
                            }
                        }
                    }
                }
            )
        )
        for _ in range(3):
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            listener.listen(128)
            self.listeners.append(listener)
        issuer, resource, callback = [
            f"http://127.0.0.1:{s.getsockname()[1]}" for s in self.listeners
        ]
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.config = dict(
            issuer=issuer,
            resource=resource + "/mcp",
            callback=callback + "/callback",
            pem=key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode(),
            database=self.connection.engine.url,
            clock_file=str(self.clock_file),
            profiles=str(profiles),
        )

    @asynccontextmanager
    async def servers(self) -> AsyncIterator[None]:
        async def complete(request: Request) -> Response:
            assert self.login
            return await self.login.complete(request)

        callback = uvicorn.Server(
            uvicorn.Config(
                Starlette(routes=[Route("/callback", complete)]),
                access_log=False,
                log_level="critical",
            )
        )
        task = asyncio.create_task(callback.serve(sockets=[self.listeners[2]]))
        try:
            async with process(self.listeners[0], self.config, True):
                yield
        finally:
            callback.should_exit = True
            await task

    @asynccontextmanager
    async def client(
        self, member: int, storage: Storage | None = None
    ) -> AsyncIterator[Client]:
        login = FullLogin(False, self.config["callback"])
        login.member = member
        self.login = login
        storage = storage or Storage(registered_client(self.config["callback"]))
        auth = OAuthClientProvider(
            self.config["resource"],
            OAuthClientMetadata(
                redirect_uris=[AnyUrl(self.config["callback"])],
                token_endpoint_auth_method="none",
                grant_types=["authorization_code", "refresh_token"],
                scope=" ".join(SCOPES),
            ),
            storage,
            login.redirect,
            login.callback_result,
        )
        async with httpx.AsyncClient(auth=auth, trust_env=False, timeout=60) as http:
            async with streamable_http_client(
                self.config["resource"], http_client=http
            ) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    assert {t.name for t in (await session.list_tools()).tools} == set(
                        TOOLS
                    )
                    client = Client(session, storage, self.tick, auth)
                    # Complete PKCE linking before timing any authenticated call.
                    if storage.tokens is None:
                        await client.call(
                            "", "get_household_context", {"scope": "people"}
                        )
                    yield client

    def tick(self) -> None:
        at = datetime.fromisoformat(self.clock_file.read_text()) + timedelta(
            microseconds=1
        )
        temporary = self.clock_file.with_suffix(".next")
        temporary.write_text(at.isoformat())
        temporary.replace(self.clock_file)
        self.loaded.world.clock.jump(at)

    async def run_worker(self) -> None:
        child = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            "from scripts.smoke_tool_budget import worker_entry; worker_entry()",
            str(self.connection.engine.url.database),
            str(self.fixture),
            self.clock_file.read_text(),
            env=os.environ | {"HIRZ_LLM": "off"},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await child.communicate()
        assert child.returncode == 0, (
            "Separate lifecycle worker failed",
            stdout.decode(),
        )
        async with self.connection.begin():
            latest = await self.connection.scalar(
                sa.select(sa.func.max(db.audit_log.c.created_at))
            )
        at = max(
            datetime.fromisoformat(self.clock_file.read_text()), latest
        ) + timedelta(microseconds=1)
        self.clock_file.write_text(at.isoformat())
        self.loaded.world.clock.jump(at)

    async def exports(self, directory: Path) -> dict[str, Any]:
        evidence = {}
        for index, p in enumerate(self.pipelines):
            summary, rows = await verify_database(
                self.connection, p.household_id, p.audit.key.public_key(), collect=True
            )
            output = directory / f"{self.scenario}-household-{index}-audit.json"
            write_export(
                output, export_document(p.household_id, p.audit.key.public_key(), rows)
            )
            trust = fingerprint(p.audit.key.public_key())
            verified = verify_file(output, p.household_id, trusted_fingerprint=trust)
            assert summary["status"] == verified["status"] == "valid"
            evidence[str(index)] = dict(
                signed_rows=len(rows), fingerprint=trust, status="valid"
            )
        return evidence

    def close(self) -> None:
        for listener in self.listeners:
            listener.close()


async def home_round(env: Environment, client: Client, index: int) -> dict[str, float]:
    """Fresh effects followed by explicit cancellation/withdrawal, never SQL reset."""
    prefix = f"round-{index}"

    async def call(case: str, tool: str, **args: Any) -> Result:
        return await client.call(case, tool, args)

    await call("onboarding", "what_can_you_do")
    for scope in ("all", "people"):
        result = await call("context-" + scope, "get_household_context", scope=scope)
        assert (
            result.data.context
            and result.data.context.household_id == env.pipelines[0].household_id
        )
    proposal = dict(
        text="Never unlock for unexpected visitors.", request_id=prefix + "-rule"
    )
    recorded = await call("proposal-fresh", "propose_household_rule", **proposal)
    assert recorded.data.status == "recorded"
    assert (
        await call("proposal-retry", "propose_household_rule", **proposal) == recorded
    )
    requested = await call(
        "plan-first",
        "get_household_plan",
        request_id=prefix + "-plan",
        objective="cheapest",
    )
    assert requested.data.status == "preparing"
    await env.run_worker()
    ready = await call("plan-ready", "get_household_plan")
    assert ready.data.plan, "worker did not prepare the requested plan"
    plan = ready.data.plan
    for focus in ("summary", "conflicts", plan.goals[0], plan.actions[0]):
        name = (
            focus
            if focus in {"summary", "conflicts"}
            else "goal"
            if focus == plan.goals[0]
            else "action"
        )
        explained = await call(
            "explain-" + name, "explain_plan", plan_id=plan.plan_id, focus=focus
        )
        assert explained.data.plan and explained.data.plan.plan_id == plan.plan_id
    approved = await call(
        "plan-approval",
        "approve_action",
        plan_id=plan.plan_id,
        version=plan.version,
        approved=True,
        request_id=prefix + "-approve",
    )
    assert approved.data.decision and approved.data.decision.decision == "execute"
    for objective in ("most_comfortable", "greenest", "cheapest"):
        changed = await call(
            "objective-" + objective,
            "get_household_plan",
            objective=objective,
            request_id=prefix + objective,
        )
        assert changed.data.status == "preparing"
        refused = await call(
            "stale-approval-" + objective,
            "approve_action",
            plan_id=plan.plan_id,
            version=plan.version,
            approved=True,
            request_id=prefix + objective + "-stale",
        )
        assert refused.data.code == "PLAN_CHANGED"
        await env.run_worker()
        replacement = await call("", "get_household_plan")
        assert replacement.data.plan
        plan = replacement.data.plan
    constraints = []
    for name, target, change, values in (
        ("car", "car", "car_limit", {"percent": 50}),
        ("dishwasher", "Dishwasher", "appliance_after", {"at": "23:00"}),
        (
            "guest",
            "Guest room",
            "temperature",
            {"temperature_f": 72, "window_end": "07:00"},
        ),
    ):
        args = dict(
            text="Explicit scenario constraint",
            applies_to=target,
            kind="one_time",
            operation="add",
            change=change,
            request_id=prefix + name,
            **values,
        )
        revised = await call("revision-" + name, "revise_household_plan", **args)
        assert revised.data.status == "recorded" and revised.data.constraint_id, (
            name,
            revised.data.status,
            revised.data.code,
        )
        assert (
            await call("revision-retry-" + name, "revise_household_plan", **args)
            == revised
        )
        constraints.append((target, change, revised.data.constraint_id))
    stale = await call(
        "same-second-approval",
        "approve_action",
        plan_id=plan.plan_id,
        version=plan.version,
        approved=True,
        request_id=prefix + "-same-second",
    )
    assert stale.data.code == "PLAN_CHANGED"
    cancelled = await call(
        "plan-cancel",
        "approve_action",
        plan_id=plan.plan_id,
        version=plan.version,
        approved=False,
        request_id=prefix + "-cancel",
    )
    assert cancelled.data.decision and cancelled.data.decision.decision == "execute"
    for target, change, constraint in constraints:
        removed = await call(
            "",
            "revise_household_plan",
            text="Remove completed benchmark constraint",
            applies_to=target,
            kind="one_time",
            operation="remove",
            change=change,
            constraint_id=constraint,
            request_id=prefix + constraint,
        )
        assert removed.data.status == "recorded"
    for name, action, fields in (
        ("temperature", "set_temperature", dict(room="Living room", temperature_f=72)),
        ("door", "request_door_unlock", dict(minutes=10)),
        (
            "claimed-door",
            "request_door_unlock",
            dict(minutes=10, claimed_requester="Mom"),
        ),
        ("ambiguous", "set_temperature", {}),
        ("profile", "apply_profile", dict(profile="night")),
    ):
        result = await call(
            "action-" + name,
            "execute_household_action",
            action=action,
            request_id=prefix + name,
            **fields,
        )
        if name == "ambiguous":
            assert result.data.status == "clarification"
        elif name == "profile":
            assert len(result.data.decisions) == 2
            assert [d.decision for d in result.data.decisions] == ["deny", "execute"]
        elif "door" in name:
            assert result.data.status in {"phone_required", "denied"}
            if name == "door":
                assert result.data.decision
                p = env.pipelines[0]
                async with env.connection.begin():
                    door_proposal = await env.connection.scalar(
                        sa.select(db.actions.c.proposal).where(
                            p.scope(db.actions),
                            db.actions.c.action_id == result.data.decision.action_id,
                        )
                    )
                # Explicit requester confirmation uses the internal Pipeline;
                # Alexa still cannot approve the resulting security request.
                env.tick()
                d = await p.propose(
                    Action.model_validate(door_proposal),
                    Principal(
                        provider="demo",
                        sub="malik",
                        surface="alexa",
                        requester_confirmed=True,
                    ),
                )
                assert d.approval
                security = await call(
                    "security-approval",
                    "approve_action",
                    action_id=d.action_id,
                    approval_id=d.approval.approval_id,
                    approved=True,
                    request_id=prefix + name + "-approval",
                )
                assert security.data.status == "phone_required"
        else:
            assert result.data.decision and result.data.decision.decision == "deny"
    preview = await call(
        "permission-preview",
        "evaluate_permission",
        action="set_temperature",
        room="Living room",
        temperature_f=72,
        request_id=prefix + "-preview",
    )
    assert preview.data.decision and preview.data.decision.audit_id is None
    started = time.perf_counter_ns()
    light = await call(
        "light-fresh",
        "execute_household_action",
        action="turn_on_light",
        room="Living room",
        request_id=prefix + "-light",
    )
    acknowledgment = (time.perf_counter_ns() - started) / 1_000_000
    assert light.data.decision and light.data.decision.status == "executing"
    await env.run_worker()
    for _ in range(600):
        async with env.connection.begin():
            status = await env.connection.scalar(
                sa.select(db.actions.c.execution_status).where(
                    db.actions.c.household_id == env.pipelines[0].household_id,
                    db.actions.c.action_id == light.data.decision.action_id,
                )
            )
        if status == "verified":
            break
        await asyncio.sleep(0.1)
    else:
        raise AssertionError("Twin light did not reach verified state")
    outcome = (time.perf_counter_ns() - started) / 1_000_000
    assert (
        await call(
            "light-retry",
            "execute_household_action",
            action="turn_on_light",
            room="Living room",
            request_id=prefix + "-light",
        )
        == light
    )
    for window in ("today", "last_night"):
        await call("audit-" + window, "get_action_audit", window=window)
    first = await call("audit-first-page", "get_action_audit", limit=1)
    assert first.data.cursor
    second = await call(
        "audit-next-page", "get_action_audit", limit=1, cursor=first.data.cursor
    )
    assert second.data.audit
    paused = await call(
        "pause",
        "execute_household_action",
        action="pause_automation",
        request_id=prefix + "-pause",
    )
    assert paused.data.decision and paused.data.decision.decision == "execute"
    from hirz.executor.plans import governance

    p = env.pipelines[0]
    principal = Principal(provider="demo", sub="malik", surface="app")
    env.tick()
    resumed = await p.redeem(
        governance(p, "resume_automation", {}, principal),
        principal,
    )
    assert resumed.decision == "execute"
    async with env.connection.begin():
        assert not (await p.snapshot(p.clock())).data["households"][0][
            "autonomy_paused"
        ]
    return {"accurate_acknowledgment": acknowledgment, "verified_twin_outcome": outcome}


async def trust_samples(env: Environment, client: Client) -> None:
    """Parents corpus: fresh private assessments/starts and both terminal outcomes."""
    from types import SimpleNamespace

    from hirz.twin.people import ContactScript

    source = yaml.safe_load(Path("scenarios/parents-scam-check.yaml").read_text())
    sentence = next(e["text"] for e in source["timeline"] if e.get("event") == "voice")
    p = env.pipelines[1]
    p.clock = lambda: datetime.fromisoformat(env.clock_file.read_text())
    for outcome in ("not_genuine", "no_answer"):
        cases = []
        for index in range(WARMUPS + SAMPLES):
            client.measuring = index >= WARMUPS
            args = dict(
                text=sentence if outcome == "not_genuine" else CASES[7][0],
                claimed_party=env.contacts[1]["display_name"],
                party="person",
                request_id=f"{outcome}-assess-{index}",
            )
            assessed = await client.call("risk-" + outcome, "assess_request_risk", args)
            assert assessed.data.case and assessed.data.case.verification is None
            assert "number" not in assessed.speakable.model_dump_json()
            assert (
                await client.call("risk-retry-" + outcome, "assess_request_risk", args)
                == assessed
            )
            case = assessed.data.case.case_id
            cases.append(case)
            start_args = dict(
                operation="start", case_id=case, request_id=f"{outcome}-start-{index}"
            )
            started = await client.call(
                "verify-start-" + outcome, "verify_trusted_identity", start_args
            )
            assert started.data.case and started.data.case.verification
            assert started.data.case.verification.status == "pending"
            assert (
                await client.call(
                    "verify-retry-" + outcome, "verify_trusted_identity", start_args
                )
                == started
            )
            pending = await client.call(
                "verify-pending-" + outcome,
                "verify_trusted_identity",
                dict(operation="status", case_id=case),
            )
            assert (
                pending.data.case
                and pending.data.case.verification
                and pending.data.case.verification.status == "pending"
            )
        at = p.clock()
        script = ContactScript(
            contact_id=UUID(env.contacts[1]["id"]),
            requested_at=at,
            deadline=at + timedelta(minutes=2),
            reply_at=at + timedelta(seconds=10),
            reply="not_genuine",
        )
        env.clock_file.write_text((at + timedelta(minutes=2)).isoformat())
        world = SimpleNamespace(
            household=SimpleNamespace(id=p.household_id),
            config=SimpleNamespace(
                contact_scripts=(script,) if outcome == "not_genuine" else ()
            ),
        )
        await advance(p, world)  # type: ignore[arg-type]
        for index, case in enumerate(cases):
            client.measuring = index >= WARMUPS
            result = await client.call(
                "verify-" + outcome,
                "verify_trusted_identity",
                dict(operation="status", case_id=case),
            )
            assert (
                result.data.case
                and result.data.case.verification
                and result.data.case.verification.status == outcome
            )


def timing_report(clients: list[Client]) -> dict[str, Any]:
    cases = {}
    tools: dict[str, list[float]] = defaultdict(list)
    for client in clients:
        for name, samples in client.samples.items():
            assert name not in cases, "Case names must be unique"
            assert len(samples) == SAMPLES, (name, len(samples))
            cases[name] = statistics(samples) | {"tool": client.tools[name]}
            tools[client.tools[name]].extend(samples)
    assert set(tools) == set(TOOLS), "Every tool needs measured samples"
    assert set(cases) == REQUIRED_CASES, (
        "Missing or unexpected cases",
        sorted(set(cases) ^ REQUIRED_CASES),
    )
    return dict(cases=cases, tools={k: statistics(v) for k, v in tools.items()})


def worker_entry() -> None:
    import traceback

    try:
        asyncio.run(lifecycle_worker(*sys.argv[1:]))
    except Exception as exc:
        print(
            type(exc).__name__,
            [(f.name, f.lineno) for f in traceback.extract_tb(exc.__traceback__)][-6:],
        )
        raise SystemExit(1) from None


async def lifecycle_worker(database: str, fixture: str, at: str) -> None:
    """Real worker services in a fresh process, with the harness's explicit clock."""
    from hirz.executor.refresh_worker import RefreshWorker
    from hirz.executor.service import Executor
    from hirz.executor.twin import restore
    from hirz.mcp.worker import prepare_plans

    loaded = LoadedScenario(Path(fixture))
    world = loaded.world
    world.clock.set_speed(0)
    values = read_env(Path(".env"))
    async with db.connect_database(values, database=database) as connection:
        boundary = Dogwood()
        p = Pipeline(
            connection,
            await PolicyBundle.validate(world.household.id, loaded.policy, boundary),
            boundary,
            AuditWriter(signing_key(values)),
            lambda: world.clock(),
        )
        await restore(p, world)
        world.clock.jump(max(world.clock(), datetime.fromisoformat(at)))
        registry = await compose(p, world=world, config="presence:twin,energy:twin")
        await registry.start()
        try:
            await advance(p, world)
            await prepare_plans(p, loaded)
            await RefreshWorker(p, registry, world=world).batch()
            await Executor(p, registry, world=world, refresh_polls=True).sweep()
        finally:
            await registry.close()


async def failure_worker(database: str, household: str, at: str) -> None:
    """Separate worker process exercising the real missing-input failure path."""
    from hirz.constitution.schema import loads
    from hirz.mcp.worker import prepare_plans

    values = read_env(Path(".env"))
    async with db.connect_database(values, database=database) as connection:
        seed = read_seed(Path("constitutions/quinn-parents.yaml"))
        assert str(seed.household_id) == household
        boundary = Dogwood()
        p = Pipeline(
            connection,
            await PolicyBundle.validate(seed.household_id, loads(seed.yaml), boundary),
            boundary,
            AuditWriter(signing_key(values)),
            lambda: datetime.fromisoformat(at),
        )
        await prepare_plans(p, None)


async def failure_samples(env: Environment, client: Client) -> list[float]:
    samples = []
    for index in range(WARMUPS + SAMPLES):
        client.measuring = index >= WARMUPS
        start = time.perf_counter_ns()
        result = await client.call(
            "missing-input-request",
            "get_household_plan",
            {"request_id": f"failure-{index}"},
        )
        assert result.data.status == "preparing"
        child = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            "import asyncio,sys; from scripts.smoke_tool_budget import failure_worker; asyncio.run(failure_worker(*sys.argv[1:]))",
            str(env.connection.engine.url.database),
            str(env.pipelines[1].household_id),
            env.clock_file.read_text(),
            env=os.environ | {"HIRZ_LLM": "off"},
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        assert await child.wait() == 0, "Missing-input worker failed"
        for _ in range(600):
            failure = await client.call("", "get_household_plan", {})
            if failure.data.code == "PREPARATION_FAILED":
                break
            await asyncio.sleep(0.1)
        else:
            raise AssertionError(
                "Preparation failure did not become visible through MCP"
            )
        if index >= WARMUPS:
            samples.append((time.perf_counter_ns() - start) / 1_000_000)
        final = await client.call("missing-input-failure", "get_household_plan", {})
        assert final.data.code == "PREPARATION_FAILED"
    return samples


# Each existing live-selection utterance has an explicit deterministic execution
# counterpart here. Duplicate utterances intentionally map to the same case.
SELECTION_CASES = (
    "onboarding",
    "plan-ready",
    "context-people",
    "revision-car",
    "revision-dishwasher",
    "proposal-fresh",
    "risk-not_genuine",
    "risk-no_answer",
    "verify-start-not_genuine",
    "verify-pending-not_genuine",
    "pause",
    "action-profile",
    "objective-cheapest",
    "objective-most_comfortable",
    "objective-greenest",
    "action-door",
    "light-fresh",
    "action-temperature",
    "explain-summary",
    "audit-last_night",
    "permission-preview",
    "plan-approval",
    "revision-car",
    "revision-guest",
    "revision-dishwasher",
    "plan-ready",
    "light-fresh",
    "action-door",
    "action-claimed-door",
    "verify-not_genuine",
)

REQUIRED_CASES = (
    set(SELECTION_CASES)
    | {
        "context-all",
        "proposal-retry",
        "plan-first",
        "explain-conflicts",
        "explain-goal",
        "explain-action",
        "same-second-approval",
        "plan-cancel",
        "action-ambiguous",
        "security-approval",
        "light-retry",
        "audit-today",
        "audit-first-page",
        "audit-next-page",
        "missing-input-request",
        "missing-input-failure",
    }
    | {
        f"stale-approval-{goal}"
        for goal in ("cheapest", "most_comfortable", "greenest")
    }
    | {f"revision-retry-{name}" for name in ("car", "dishwasher", "guest")}
    | {
        f"{operation}-{outcome}"
        for operation in (
            "risk",
            "risk-retry",
            "verify-start",
            "verify-retry",
            "verify-pending",
            "verify",
        )
        for outcome in ("not_genuine", "no_answer")
    }
)


async def latency(env: Environment, report: dict[str, Any]) -> list[Storage]:
    interactions: dict[str, list[float]] = defaultdict(list)
    async with env.client(0) as home, env.client(3) as parents:
        try:
            for index in range(WARMUPS + SAMPLES):
                home.measuring = index >= WARMUPS
                times = await home_round(env, home, index)
                if home.measuring:
                    for name, elapsed in times.items():
                        interactions[name].append(elapsed)
                print(
                    f"PROGRESS {env.scenario} round={index + 1}/{WARMUPS + SAMPLES}",
                    flush=True,
                )
            interactions["understandable_preparation_failure"] = await failure_samples(
                env, parents
            )
            await trust_samples(env, parents)
            report.update(timing_report([home, parents]))
            assert len(CASES) == len(SELECTION_CASES)
            assert set(SELECTION_CASES) | {"action-ambiguous"} <= report["cases"].keys()
            for (_, expected, arguments), case in zip(
                CASES, SELECTION_CASES, strict=True
            ):
                assert report["cases"][case]["tool"] == expected
                actual = (home.inputs | parents.inputs)[case]
                for key, value in arguments.items():
                    if key not in {"plan_id", "version"}:
                        assert actual[key] == value, (
                            case,
                            "corpus argument mismatch",
                            key,
                        )
            report["selection_mapping"] = list(SELECTION_CASES) + ["action-ambiguous"]
            report["interactions"] = {
                name: statistics(values) for name, values in interactions.items()
            }
            return [home.storage, parents.storage]
        finally:
            report["raw_cases"] = {
                case: {"tool": client.tools[case], "samples_ms": values}
                for client in (home, parents)
                for case, values in client.samples.items()
            }
            report["raw_interactions"] = dict(interactions)


async def startup(env: Environment, storage: Storage) -> dict[str, Any]:
    launches, calls = [], []
    for _ in range(10):
        start = time.perf_counter_ns()
        async with mcp_process(env.listeners[1], env.config):
            launches.append((time.perf_counter_ns() - start) / 1_000_000)
            async with env.client(0, storage) as client:
                client.measuring = True
                result = await client.call(
                    "first", "get_household_context", {"scope": "all"}
                )
                assert (
                    result.data.context
                    and result.data.context.household_id
                    == env.pipelines[0].household_id
                )
                calls.append(client.samples["first"][0])
    return dict(
        label="Local process startup; not AWS cold start",
        process_to_health=statistics(launches),
        first_authenticated_context=statistics(calls),
    )


async def household_state(env: Environment, household: UUID) -> dict[str, Any]:
    """Compare complete scoped persisted rows, including receipts and audit heads."""
    result = {}
    async with env.connection.begin():
        for table in db.metadata.sorted_tables:
            column = table.c.get("household_id")
            if table.name == "households":
                column = table.c.id
            if column is not None:
                rows = (
                    (
                        await env.connection.execute(
                            sa.select(table).where(column == household)
                        )
                    )
                    .mappings()
                    .all()
                )
                result[table.name] = sorted(repr(dict(row)) for row in rows)
    return result


async def symmetric_references(env: Environment, home: Client) -> dict[str, Any]:
    """Both sides own real plans, constraints and pending approvals before probing."""
    from hirz.mcp.worker import prepare_plans

    assert home.storage.tokens
    original = home.storage.tokens
    claims = jwt.decode(original.access_token, options={"verify_signature": False})
    claims.update(
        household_id=str(env.pipelines[2].household_id),
        sub="malik-item26",
        iat=int(time.time()),
        exp=int(time.time()) + 300,
    )
    token = jwt.encode(
        claims,
        env.config["pem"],
        algorithm="RS256",
        headers=jwt.get_unverified_header(original.access_token),
    )
    storage = Storage(
        registered_client(env.config["callback"]),
        original.model_copy(update={"access_token": token}),
    )
    records: list[dict[str, Any]] = []
    async with env.client(0, storage) as mirror:
        clients = (home, mirror)
        for client, p, loaded in zip(
            clients,
            (env.pipelines[0], env.pipelines[2]),
            (env.loaded, env.mirror),
            strict=True,
        ):
            await client.call(
                "", "get_household_plan", {"request_id": "symmetric-plan"}
            )
            if client is not home:
                await prepare_plans(p, loaded)
            result = await client.call("", "get_household_plan", {})
            plan = (
                env.isolation_records[0]["plan"] if client is home else result.data.plan
            )
            assert plan, (
                "home" if client is home else "mirror",
                result.data.status,
                result.data.code,
            )
            revision = await client.call(
                "",
                "revise_household_plan",
                dict(
                    text="Symmetric ceiling",
                    applies_to="car",
                    change="car_limit",
                    percent=50,
                    operation="add",
                    kind="one_time",
                    request_id="symmetric-constraint",
                ),
            )
            assert revision.data.constraint_id
            paused = await client.call(
                "",
                "execute_household_action",
                dict(action="pause_automation", request_id="symmetric-pause"),
            )
            assert paused.data.decision and paused.data.decision.decision == "execute"
            light = await client.call(
                "",
                "execute_household_action",
                dict(
                    action="turn_on_light",
                    room="Living room",
                    request_id="symmetric-light",
                ),
            )
            assert light.data.decision and light.data.decision.approval
            records.append(
                dict(
                    plan=plan,
                    constraint=revision.data.constraint_id,
                    action=light.data.decision.action_id,
                    approval=light.data.decision.approval.approval_id,
                )
            )
        checks = 0
        for index, client in enumerate(clients):
            own, foreign = records[index], records[1 - index]
            before = [
                await household_state(env, p.household_id)
                for p in (env.pipelines[0], env.pipelines[2])
            ]
            for tool, args, error in (
                ("explain_plan", dict(plan_id=foreign["plan"].plan_id), True),
                (
                    "approve_action",
                    dict(
                        plan_id=foreign["plan"].plan_id,
                        version=foreign["plan"].version,
                        approved=True,
                        request_id="symmetric-foreign-plan",
                    ),
                    True,
                ),
                (
                    "approve_action",
                    dict(
                        action_id=foreign["action"],
                        approval_id=foreign["approval"],
                        approved=True,
                        request_id="symmetric-foreign-approval",
                    ),
                    True,
                ),
                (
                    "approve_action",
                    dict(
                        action_id=own["action"],
                        approval_id=foreign["approval"],
                        approved=True,
                        request_id="symmetric-mixed-approval",
                    ),
                    True,
                ),
                (
                    "revise_household_plan",
                    dict(
                        text="Remove foreign constraint",
                        applies_to="car",
                        operation="remove",
                        kind="one_time",
                        change="car_limit",
                        constraint_id=foreign["constraint"],
                        request_id="symmetric-foreign-constraint",
                    ),
                    False,
                ),
            ):
                refused = await client.call("", tool, args, error=error)
                assert refused.data.code == ("REQUEST_REFUSED" if error else "CLARIFY")
                assert (
                    not refused.data.plan
                    and not refused.data.decision
                    and not refused.data.constraint_id
                )
                checks += 1
            after = [
                await household_state(env, p.household_id)
                for p in (env.pipelines[0], env.pipelines[2])
            ]
            assert after == before, "A foreign reference produced a persisted effect"
        env.mirror_records = records
        env.mirror_storage = storage
    return dict(
        checks=checks,
        fixture="Explicit disposable home copy; distinct household/account; Pipeline-created records",
    )


async def isolation(env: Environment) -> tuple[dict[str, Any], list[Storage]]:
    checks = 0
    storages = []
    async with env.client(0) as home, env.client(3) as parents:
        clients = [home, parents]
        records: list[dict[str, Any]] = []
        for index, client in enumerate(clients):
            own, other = (
                env.pipelines[index].household_id,
                env.pipelines[1 - index].household_id,
            )
            before = await household_state(env, other)
            context = await client.call("", "get_household_context", {"scope": "all"})
            assert context.data.context and context.data.context.household_id == own
            for rows in context.data.context.data.values():
                if isinstance(rows, list):
                    for row in rows:
                        if isinstance(row, dict) and "household_id" in row:
                            assert str(row["household_id"]) == str(own)
            proposal_args = dict(
                text=f"Item 26 private household {index} rule",
                request_id="iso-shared-proposal",
            )
            proposal = await client.call("", "propose_household_rule", proposal_args)
            assert proposal.data.status == "recorded"
            assessed = await client.call(
                "",
                "assess_request_risk",
                dict(
                    text=f"Private household {index} request: send money urgently",
                    party="person",
                    claimed_party=env.contacts[index]["display_name"],
                    request_id="iso-shared-risk",
                ),
            )
            assert assessed.data.case
            case = assessed.data.case.case_id
            verification = await client.call(
                "",
                "verify_trusted_identity",
                dict(operation="start", case_id=case, request_id="iso-shared-start"),
            )
            assert verification.data.case and verification.data.case.verification
            assert verification.data.case.verification.status == "pending"
            permission = await client.call(
                "",
                "evaluate_permission",
                dict(action="pause_automation", request_id="iso-shared-preview"),
            )
            assert (
                permission.data.decision and permission.data.decision.audit_id is None
            )
            door = await client.call(
                "",
                "execute_household_action",
                dict(
                    action="request_door_unlock",
                    minutes=10,
                    request_id="iso-shared-door",
                ),
            )
            assert door.data.decision
            audit = await client.call("", "get_action_audit", {"limit": 1})
            assert audit.data.cursor
            requested = await client.call(
                "", "get_household_plan", {"request_id": "iso-shared-plan"}
            )
            if index == 0:
                await env.run_worker()
                requested = await client.call("", "get_household_plan", {})
                assert requested.data.plan
            explanation = await client.call("", "explain_plan", {})
            assert bool(explanation.data.plan) == (index == 0)
            revision = await client.call(
                "",
                "revise_household_plan",
                dict(
                    text="Isolation car ceiling",
                    applies_to="car",
                    kind="one_time",
                    operation="add",
                    change="car_limit",
                    percent=50,
                    request_id="iso-shared-revision",
                ),
            )
            assert revision.data.status == (
                "recorded" if index == 0 else "clarification"
            )
            rejected = await client.call(
                "",
                "approve_action",
                dict(
                    action_id=door.data.decision.action_id,
                    approval_id="nonexistent-approval",
                    approved=True,
                    request_id="iso-shared-approval",
                ),
                error=True,
            )
            assert rejected.data.code == "REQUEST_REFUSED"
            onboarding = await client.call("", "what_can_you_do", {})
            assert set(onboarding.data.available_tools) == set(TOOLS)
            assert await household_state(env, other) == before, (
                "A tool mutated the other household"
            )
            records.append(
                dict(
                    context=context.data.context,
                    proposal=proposal,
                    proposal_args=proposal_args,
                    case=case,
                    action=door.data.decision.action_id,
                    cursor=audit.data.cursor,
                    plan=requested.data.plan,
                    constraint=revision.data.constraint_id,
                )
            )
            storages.append(client.storage)
            checks += len(TOOLS)

        for index, client in enumerate(clients):
            foreign = records[1 - index]
            before = await household_state(env, env.pipelines[1 - index].household_id)
            foreign_member = str(foreign["context"].data["members"][0]["id"])
            foreign_asset = str(foreign["context"].data["assets"][0]["id"])
            attacks = [
                (
                    "get_household_context",
                    dict(scope="member", member=foreign_member),
                    False,
                    "clarification",
                ),
                (
                    "verify_trusted_identity",
                    dict(operation="status", case_id=foreign["case"]),
                    True,
                    "failed",
                ),
                (
                    "verify_trusted_identity",
                    dict(
                        operation="start",
                        case_id=foreign["case"],
                        request_id="foreign-case",
                    ),
                    True,
                    "failed",
                ),
                (
                    "verify_trusted_identity",
                    dict(
                        operation="start",
                        contact=env.contacts[1 - index]["id"],
                        text="Foreign contact",
                        request_id="foreign-contact",
                    ),
                    False,
                    "clarification",
                ),
                ("get_action_audit", dict(cursor=foreign["cursor"]), True, "failed"),
                (
                    "execute_household_action",
                    dict(
                        action="turn_on_light",
                        room=foreign_asset,
                        request_id="foreign-room",
                    ),
                    False,
                    "clarification",
                ),
                (
                    "evaluate_permission",
                    dict(
                        action="set_temperature",
                        room=foreign_asset,
                        temperature_f=72,
                        request_id="foreign-preview",
                    ),
                    False,
                    "clarification",
                ),
                (
                    "approve_action",
                    dict(
                        action_id=foreign["action"],
                        approval_id="nonexistent-approval",
                        approved=True,
                        request_id="foreign-approval",
                    ),
                    True,
                    "failed",
                ),
            ]
            if foreign["plan"]:
                plan = foreign["plan"]
                attacks += [
                    ("explain_plan", dict(plan_id=plan.plan_id), True, "failed"),
                    (
                        "approve_action",
                        dict(
                            plan_id=plan.plan_id,
                            version=plan.version,
                            approved=True,
                            request_id="foreign-plan",
                        ),
                        True,
                        "failed",
                    ),
                ]
            if foreign["constraint"]:
                attacks.append(
                    (
                        "revise_household_plan",
                        dict(
                            text="Remove foreign constraint",
                            applies_to="car",
                            kind="one_time",
                            operation="remove",
                            change="car_limit",
                            constraint_id=foreign["constraint"],
                            request_id="foreign-constraint",
                        ),
                        False,
                        "clarification",
                    )
                )
            for tool, arguments, error, status in attacks:
                result = await client.call("", tool, arguments, error=error)
                assert result.data.status == status, (tool, "foreign reference outcome")
                assert (
                    not result.data.plan
                    and not result.data.case
                    and not result.data.context
                    and not result.data.action
                )
                checks += 1
            foreign_audit = await client.call(
                "", "get_action_audit", {"action_id": foreign["action"]}
            )
            assert not foreign_audit.data.audit
            for field, value in (
                ("household_id", str(env.pipelines[1 - index].household_id)),
                ("role", "owner"),
                ("surface", "app"),
            ):
                invalid = await client.call(
                    "",
                    "propose_household_rule",
                    dict(
                        text="Injected authority",
                        request_id="injection",
                        **{field: value},
                    ),
                    error=True,
                )
                assert invalid.data.code == "INVALID_INPUT"
                checks += 1
            assert (
                await household_state(env, env.pipelines[1 - index].household_id)
                == before
            ), "Foreign-reference call changed its target household"
            # A guessed key cannot retrieve another household's persisted response.
            assert (
                await client.call(
                    "", "propose_household_rule", records[index]["proposal_args"]
                )
                == records[index]["proposal"]
            )
            conflict = await client.call(
                "",
                "propose_household_rule",
                records[1 - index]["proposal_args"],
                error=True,
            )
            assert conflict.data.code == "REQUEST_CONFLICT"
            checks += 3
        for member, index in ((2, 0), (4, 1)):
            async with env.client(member) as other_member:
                denied = await other_member.call(
                    "",
                    "verify_trusted_identity",
                    dict(operation="status", case_id=records[index]["case"]),
                    error=True,
                )
                assert denied.data.code == "REQUEST_REFUSED"
                checks += 1
        # Overlap requests with the same keys and different payloads through the
        # same process. The context variable, DB scope and receipt scope all matter.
        for number in range(20):
            for tool, args in (
                ("get_household_context", [{"scope": "all"}, {"scope": "all"}]),
                (
                    "propose_household_rule",
                    [
                        dict(
                            text=f"Concurrent household {i}",
                            request_id=f"concurrent-{number}",
                        )
                        for i in range(2)
                    ],
                ),
                (
                    "verify_trusted_identity",
                    [dict(operation="status", case_id=r["case"]) for r in records],
                ),
            ):
                responses = await asyncio.gather(
                    *(c.call("", tool, a) for c, a in zip(clients, args, strict=True))
                )
                for index, response in enumerate(responses):
                    if tool == "get_household_context":
                        assert (
                            response.data.context
                            and response.data.context.household_id
                            == env.pipelines[index].household_id
                        )
                    elif tool == "verify_trusted_identity":
                        assert (
                            response.data.case
                            and response.data.case.case_id == records[index]["case"]
                        )
                    else:
                        assert response.data.status == "recorded"
                        async with env.connection.begin():
                            owner = await env.connection.scalar(
                                sa.select(db.rule_proposals.c.household_id).where(
                                    db.rule_proposals.c.id == response.data.reference
                                )
                            )
                        assert owner == env.pipelines[index].household_id
                    checks += 1
        env.isolation_records = records
        symmetric = await symmetric_references(env, home)
    return dict(
        status="passed",
        checks=checks,
        concurrent_rounds=20,
        symmetric_references=symmetric,
    ), storages


async def isolation_restart(env: Environment, storages: list[Storage]) -> None:
    for index, member in enumerate((0, 3)):
        async with env.client(member, storages[index]) as client:
            own = env.isolation_records[index]
            foreign = env.isolation_records[1 - index]
            assert (
                await client.call("", "propose_household_rule", own["proposal_args"])
                == own["proposal"]
            )
            denied = await client.call(
                "",
                "verify_trusted_identity",
                dict(operation="status", case_id=foreign["case"]),
                error=True,
            )
            assert denied.data.code == "REQUEST_REFUSED"
            context = await client.call("", "get_household_context", {"scope": "all"})
            assert (
                context.data.context
                and context.data.context.household_id
                == env.pipelines[index].household_id
            )

    async with env.client(0, env.mirror_storage) as mirror:
        foreign = env.mirror_records[0]
        denied = await mirror.call(
            "",
            "approve_action",
            dict(
                action_id=foreign["action"],
                approval_id=foreign["approval"],
                approved=True,
                request_id="restart-foreign-approval",
            ),
            error=True,
        )
        assert denied.data.code == "REQUEST_REFUSED"


async def run(
    mode: str, directory: Path, *, scenario: str | None = None
) -> dict[str, Any]:
    assert scenario is None or (
        mode == "latency" and scenario in {"demo-evening", "demo-evening-hourly"}
    )
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    logging.disable(logging.CRITICAL)
    report: dict[str, Any] = dict(
        status="failed",
        mode=mode,
        platform=platform.platform(),
        python=sys.version,
        versions={
            name: version(name) for name in ("mcp", "sqlalchemy", "psycopg", "scipy")
        },
        commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        tracked_diff_sha256=sha256(
            subprocess.check_output(["git", "diff", "HEAD"])
        ).hexdigest(),
        runner_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        warmups=WARMUPS,
        samples=SAMPLES,
        budget_ms=BUDGET_MS,
        scenarios={},
    )
    try:
        scenarios = (
            (scenario,)
            if scenario
            else (
                ("demo-evening", "demo-evening-hourly")
                if mode != "isolation"
                else ("demo-evening",)
            )
        )
        for scenario in scenarios:
            async with disposable(read_env(Path(".env"))) as connection:
                with TemporaryDirectory(prefix="hirz-budget-") as temporary:
                    env = Environment(connection, Path(temporary), scenario)
                    try:
                        await env.prepare()
                        if mode != "latency":
                            await env.prepare_mirror()
                        result: dict[str, Any] = {}
                        report["scenarios"][scenario] = result
                        async with env.servers():
                            async with mcp_process(env.listeners[1], env.config):
                                if mode != "isolation":
                                    result["latency"] = {}
                                    storages = await latency(env, result["latency"])
                                if mode != "latency":
                                    result["isolation"], storages = await isolation(env)
                            if mode != "isolation":
                                result["startup"] = await startup(env, storages[0])
                            if mode != "latency":
                                async with mcp_process(env.listeners[1], env.config):
                                    await isolation_restart(env, storages)
                        result["audit"] = await env.exports(directory)
                        async with connection.begin():
                            result["row_counts"] = {
                                table.name: await connection.scalar(
                                    sa.select(sa.func.count()).select_from(table)
                                )
                                for table in (
                                    db.actions,
                                    db.audit_log,
                                    db.plans,
                                    db.tool_requests,
                                    db.verification_cases,
                                )
                            }
                        if mode != "isolation":
                            slow = [
                                name
                                for group in ("cases", "tools")
                                for name, row in result["latency"][group].items()
                                if row["p95_ms"] > BUDGET_MS
                            ]
                            assert not slow, ("Warm p95 budget exceeded", slow)
                    finally:
                        env.close()
        report["status"] = "passed"
        return report
    finally:
        write_json(directory / "report.json", report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=("latency", "isolation", "all"), default="all"
    )
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args.mode, args.artifacts_dir))
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "mode": args.mode,
                    "report": str(args.artifacts_dir / "report.json"),
                }
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
                    ][-8:],
                )
                if isinstance(error, AssertionError):
                    print(str(error))

        diagnostic(exc)
        parser.exit(
            1,
            "FAIL item 26; private evidence retained; development database unchanged.\n",
        )


if __name__ == "__main__":
    main()
