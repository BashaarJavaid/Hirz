"""Item 37 inert acceptance. Live mode always tears down the existing acceptance stack."""

import argparse
import asyncio
import json
import os
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
import sqlalchemy as sa
from webauthn.helpers import base64url_to_bytes

from hirz import db
from hirz.api.app import create_app
from hirz.audit import export_document, verify_database, verify_file, write_export
from hirz.aws.cleanup import destroy, policy_tracing
from hirz.aws.client import call
from hirz.aws.fixture import policy_routes, policy_seeds
from hirz.aws.gateway import Gateway, SessionConflict, Verdict
from hirz.aws.policy import Publisher, fingerprint, inventory, wire_json
from hirz.aws.publication import advance
from hirz.aws.routing import Route
from hirz.companion import auth
from hirz.companion.api import Companion
from hirz.companion.governance import constitution
from hirz.constitution.boundary import Dogwood, Event
from hirz.constitution.compiler import Statement, boundary_input, compile_policy
from hirz.constitution.evaluator import resolve
from hirz.constitution.preview import SITUATIONS, situation
from hirz.constitution.schema import dump, loads
from hirz.executor.local import policy as reload_policy
from hirz.graph.models import now
from hirz.graph.seeds import Seed, demo_id, load_seeds
from hirz.local import read_env, signing_key
from hirz.pipeline.audit import AuditWriter
from hirz.pipeline.hashing import digest
from hirz.pipeline.models import (
    ROLES,
    BoundaryEvidence,
    BoundaryRequest,
    ConstitutionEvidence,
    Decision,
    EventType,
)
from hirz.pipeline.service import Pipeline, PolicyBundle
from hirz.twin.authenticator import CONFIG, Authenticator
from hirz.twin.disposable import disposable
from scripts.smoke_aws import Acceptance, clearance


class AcceptanceGateway(Gateway):
    acceptance: Acceptance

    async def invoke(
        self, name: str, inputs: dict[str, Any], session_id: UUID
    ) -> Verdict:
        self.acceptance.within_window()
        reserve_gateway_call(self.acceptance.folder)
        return await super().invoke(name, inputs, session_id)


def reserve_gateway_call(folder: Path) -> None:
    count = len(list(folder.glob("gateway-call-*.json"))) + 1
    if count > 5000:
        raise ValueError("Acceptance Gateway allowance exhausted; tear down")
    path = folder / f"gateway-call-{count:04d}.json"
    write_export(path, {"reserved_call": count, "failures_count": True})
    with path.open("rb") as handle:
        os.fsync(handle.fileno())
    descriptor = os.open(folder, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def corpus(
    seed: Seed,
) -> list[tuple[str, Event, tuple[Event, ...], ConstitutionEvidence]]:
    policy = loads(seed.yaml)
    compiled = compile_policy(policy)
    cases = []
    for name, spec in SITUATIONS.items():
        situations = [
            (role, case) for case in [{}, *spec.get("cases", [])] for role in ROLES
        ]
        for index, (role, case) in enumerate(situations):
            action, facts = situation(policy, name, cast(Any, role), case)
            outcome = resolve(policy, action, facts)
            details = ConstitutionEvidence(
                version=policy.version,
                rule=outcome.selected_rule,
                mode=outcome.effective_mode,
                conditions_met=outcome.conditions_met,
            )
            ttl = outcome.approval.ttl_minutes
            inputs = boundary_input(
                compiled,
                action,
                facts,
                ttl_minutes=ttl,
                session_id=str(uuid4()),
                approver_role="owner",
                approval_channel="app_push",
                quorum_satisfied=True,
            )
            current = Event(1, name, inputs)
            prior = Event(0, "governance.approve_action", inputs)
            key = f"{policy.household}:{name}:{index}"
            cases.extend(
                [
                    (key + ":absent", current, (), details),
                    (key + ":approval", current, (prior,), details),
                ]
            )
    action, facts = situation(policy, "security.door_unlock")
    inputs = boundary_input(
        compiled,
        action,
        facts,
        ttl_minutes=resolve(policy, action, facts).approval.ttl_minutes,
        session_id=str(uuid4()),
        approver_role="owner",
        approval_channel="app_push",
        quorum_satisfied=True,
    )
    outcome = resolve(policy, action, facts)
    details = ConstitutionEvidence(
        version=policy.version,
        rule=outcome.selected_rule,
        mode=outcome.effective_mode,
        conditions_met=outcome.conditions_met,
    )
    for field, value in {
        "household": "foreign-household",
        "action_class": "environment.lights",
        "action_hash": "wrong-hash",
        "session_id": str(uuid4()),
        "ttl_minutes": 1,
        "approver_role": "guest",
        "approval_channel": "alexa",
        "quorum_satisfied": False,
    }.items():
        cases.append(
            (
                f"{policy.household}:wrong:{field}",
                Event(1, action.action_class, inputs),
                (
                    Event(
                        0, "governance.approve_action", dict(inputs, **{field: value})
                    ),
                ),
                details,
            )
        )
    cases.append(
        (
            f"{policy.household}:rejected",
            Event(1, action.action_class, inputs),
            (
                Event(
                    0,
                    "governance.approve_action",
                    dict(inputs, quorum_satisfied=False),
                    approved=False,
                ),
            ),
            details,
        )
    )
    from hirz.constitution.compiler import field as boundary_field

    changed = dict(inputs)
    changed[boundary_field("context.unexpected_visitor")] = True
    changed_action, changed_facts = situation(
        policy,
        action.action_class,
        case={
            "values": {
                "context": {**dict(facts.values["context"]), "unexpected_visitor": True}
            }
        },
    )
    changed_outcome = resolve(policy, changed_action, changed_facts)
    cases.append(
        (
            f"{policy.household}:changed_conditions",
            Event(1, action.action_class, changed),
            (Event(0, "governance.approve_action", inputs),),
            details.model_copy(
                update={
                    "mode": changed_outcome.effective_mode,
                    "conditions_met": changed_outcome.conditions_met,
                }
            ),
        )
    )
    return cases


async def phone(
    service: Companion, p: Pipeline, seed: Seed
) -> tuple[httpx.AsyncClient, Authenticator]:
    member = next(row["id"] for row in seed.graph["members"] if row["role"] == "owner")
    invitation = await auth.initial_invitation(p, demo_id(seed.slug, "members", member))
    http = httpx.AsyncClient(
        transport=httpx.ASGITransport(create_app(companion=service)),
        base_url=CONFIG.origin,
        headers={"origin": CONFIG.origin},
    )
    key = Authenticator()
    response = await http.get("/api/auth/session")
    response.raise_for_status()
    answer = await ceremony(http, key, {"operation": "enroll", "token": invitation})
    http.headers["x-hirz-csrf"] = answer["csrf"]
    return http, key


async def ceremony(
    http: httpx.AsyncClient, key: Authenticator, binding: dict[str, Any]
) -> dict[str, Any]:
    response = await http.post("/api/auth/begin", json=binding)
    response.raise_for_status()
    options = response.json()
    response = await http.post(
        "/api/auth/finish",
        json={
            "id": options["id"],
            "credential": key.response(
                base64url_to_bytes(options["publicKey"]["challenge"]),
                register=binding["operation"] == "enroll",
            ),
        },
    )
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


async def activate(http: httpx.AsyncClient, key: Authenticator, candidate: str) -> str:
    response = await http.post("/api/constitution/draft", json={"yaml": candidate})
    response.raise_for_status()
    draft = response.json()
    response = await http.post("/api/constitution/review", json={"id": draft["id"]})
    response.raise_for_status()
    answer = await ceremony(
        http,
        key,
        {
            "operation": "activate",
            "draft_id": draft["id"],
            "candidate_hash": draft["candidate_hash"],
        },
    )
    if answer != {"status": "pending"}:
        raise ValueError("AWS activation must return pending")
    return str(draft["id"])


async def publication(
    p: Pipeline, publisher: Publisher, reference: str, acceptance: Acceptance
) -> dict[str, Any]:
    for _ in range(1500):
        acceptance.within_window()
        await advance(p, publisher)
        async with p.connection.begin():
            row = dict(
                (
                    await p.connection.execute(
                        sa.select(db.policy_publications).where(
                            db.policy_publications.c.id == reference
                        )
                    )
                )
                .mappings()
                .one()
            )
        if row["status"] in {"failed", "blocked", "committed"}:
            return row
        await asyncio.sleep(1)
    raise ValueError(
        "Publication did not finish within the bounded acceptance attempts"
    )


async def compare(
    p: Pipeline,
    seed: Seed,
    gateway: Gateway,
    expected_inventory: dict[str, str],
    acceptance: Acceptance,
    mode: str,
) -> list[dict[str, Any]]:
    folder = acceptance.folder
    compiled = compile_policy(loads(seed.yaml))
    native = Dogwood()
    await native.validate(compiled)
    records = []
    owner = next(row["id"] for row in seed.graph["members"] if row["role"] == "owner")
    async with p.connection.begin():
        generation = await p.connection.scalar(
            sa.select(db.policy_engines.c.generation).where(
                db.policy_engines.c.id == gateway.route.engine_id
            )
        )
        if generation is None:
            raise ValueError("Missing committed engine generation")
        actor = (
            await auth.account(
                p.connection, p.household_id, demo_id(seed.slug, "members", owner)
            )
        ).model_copy(update={"surface": "scheduler"})
    for key, event, approvals, details in corpus(seed):
        acceptance.within_window()
        # Every test gets a new real UUID; altered session inputs retain their mismatch.
        session = uuid4()
        original = event.inputs["session_id"]
        event = replace(event, inputs=dict(event.inputs, session_id=str(session)))
        approvals = tuple(
            replace(
                a,
                inputs=dict(
                    a.inputs,
                    session_id=str(session)
                    if a.inputs["session_id"] == original
                    else a.inputs["session_id"],
                ),
            )
            for a in approvals
        )
        expected = await native.authorize(compiled, event, approvals)
        if expected.diagnostic:
            raise ValueError("Native reference failed")
        approval_records = []
        for prior in approvals:
            expected_approval = await native.authorize(compiled, prior)
            observed = await gateway.invoke(
                "governance.approve_action",
                prior.inputs,
                UUID(prior.inputs["session_id"]),
            )
            approval_records.append(
                {
                    "inputs_json": wire_json(prior.inputs),
                    "local": expected_approval.allowed,
                    "aws": asdict(observed),
                }
            )
            if (
                expected_approval.diagnostic
                or observed.allowed != expected_approval.allowed
                or observed.mode != mode
            ):
                write_export(
                    folder / (mode + "-approval-disagreement.json"),
                    {"case": key, "approvals": approval_records},
                )
                raise ValueError("AWS/native approval disagreement or missing evidence")
        verdict = await gateway.invoke(event.action_class, event.inputs, session)
        request = {
            "class": event.action_class,
            "inputs_json": wire_json(event.inputs),
            "approvals": approval_records,
        }
        context_hash = "sha256:" + digest(request)
        record = {
            "case": key,
            "local": expected.allowed,
            "aws": asdict(verdict),
            "inventory_hash": fingerprint(expected_inventory),
            "request": request,
            "context_hash": context_hash,
        }
        records.append(record)
        write_export(
            folder / (mode + "-" + seed.slug + "-" + str(len(records)) + ".json"),
            record,
        )
        if verdict.allowed != expected.allowed or verdict.mode != mode:
            raise ValueError("AWS/native disagreement or unexpected enforcement mode")
        evidence = BoundaryRequest(
            request_id=verdict.request_id,
            trace_id=verdict.trace_id,
            session_id=session,
            policy_ids=verdict.policy_ids,
            inventory_hash=fingerprint(expected_inventory),
            generation=generation,
            result="allow" if verdict.allowed else "deny",
            mode=cast(Any, mode),
        )
        async with p.repo.write(p.clock):
            await constitution(p, actor, "publish", key)
            await p.audit.append(
                p.connection,
                p.household_id,
                p.clock(),
                EventType.DRY_RUN,
                Decision(
                    decision="execute" if verdict.allowed else "deny",
                    event_type=EventType.DRY_RUN,
                    action_id=key,
                    constitution=details.model_copy(
                        update={"version": p.bundle.policy().version}
                    ),
                    boundary=BoundaryEvidence(
                        engine="agentcore-policy",
                        result=evidence.result,
                        reason="Inert acceptance only; no device action executed",
                        context_hash=context_hash,
                        requests=(evidence,),
                    ),
                ),
            )
    return records


async def promote(
    publisher: Publisher,
    sdk: Any,
    route: Route,
    desired: dict[str, str],
    records: list[dict[str, Any]],
    seeds: list[Seed],
) -> None:
    required = {key for seed in seeds for key, _, _, _ in corpus(seed)}
    if (
        {r["case"] for r in records} != required
        or len(records) != len(required)
        or any(
            r["local"] != r["aws"]["allowed"]
            or r["aws"]["mode"] != "LOG_ONLY"
            or r["inventory_hash"] != fingerprint(desired)
            or r["context_hash"] != "sha256:" + digest(r["request"])
            or any(
                a["local"] != a["aws"]["allowed"] or a["aws"]["mode"] != "LOG_ONLY"
                for a in r["request"]["approvals"]
            )
            for r in records
        )
    ):
        raise ValueError("Incomplete or mismatched promotion evidence")
    installed = await publisher.installed()
    if {
        n: r["definition"]["policy"]["statement"] for n, r in installed.items()
    } != desired or any(
        r["status"] != "ACTIVE" or r.get("statusReasons") for r in installed.values()
    ):
        raise ValueError("Promotion policies differ from the tested inventory")
    policy_ids = {r["policyId"] for r in installed.values()}
    if any(
        not set(v["policy_ids"]).issubset(policy_ids)
        for r in records
        for v in [r["aws"], *(a["aws"] for a in r["request"]["approvals"])]
    ):
        raise ValueError(
            "Promotion evidence names policies outside the deployed inventory"
        )
    current = await call(sdk, "get_gateway", gatewayIdentifier=publisher.gateway_id)
    if current["policyEngineConfiguration"]["mode"] != "LOG_ONLY":
        raise ValueError("Acceptance must begin in LOG_ONLY")
    args = {
        k: current[k]
        for k in (
            "name",
            "roleArn",
            "protocolType",
            "authorizerType",
            "authorizerConfiguration",
        )
    }
    await call(
        sdk,
        "update_gateway",
        gatewayIdentifier=publisher.gateway_id,
        **args,
        policyEngineConfiguration={
            "arn": current["policyEngineConfiguration"]["arn"],
            "mode": "ENFORCE",
        },
    )
    for _ in range(60):
        current = await call(sdk, "get_gateway", gatewayIdentifier=publisher.gateway_id)
        if (
            current["status"] == "READY"
            and current["policyEngineConfiguration"]["mode"] == "ENFORCE"
        ):
            return
        await asyncio.sleep(1)
    raise ValueError("Gateway enforcement promotion did not finish")


async def invalidation(
    p: Pipeline,
    phone: tuple[httpx.AsyncClient, Authenticator],
    seed: Seed,
    gateway: Gateway,
    publisher: Publisher,
    acceptance: Acceptance,
) -> None:
    original = loads(seed.yaml)
    action, facts = situation(original, "security.door_unlock")
    session = uuid4()
    ttl = resolve(original, action, facts).approval.ttl_minutes
    inputs = boundary_input(
        compile_policy(original),
        action,
        facts,
        ttl_minutes=ttl,
        session_id=str(session),
        approver_role="owner",
        approval_channel="app_push",
        quorum_satisfied=True,
    )
    if not (await gateway.invoke("governance.approve_action", inputs, session)).allowed:
        raise ValueError("Invalidation needs an allowed approval control")
    if not (await gateway.invoke(action.action_class, inputs, session)).allowed:
        raise ValueError("Invalidation needs an allowed action control")
    candidate = original.model_copy(
        update={
            "defaults": original.defaults.model_copy(
                update={"approval_ttl_minutes": ttl + 1}
            )
        }
    )
    reference = await activate(*phone, dump(candidate))
    job = await publication(p, publisher, reference, acceptance)
    write_export(
        acceptance.folder / "invalidation-publication.json",
        json.loads(json.dumps(job, default=str)),
    )
    if job["status"] != "committed":
        raise ValueError("Policy update invalidation fixture was rejected")
    p.bundle = await reload_policy(p)
    try:
        await gateway.invoke(action.action_class, inputs, session)
    except SessionConflict as conflict:
        if not conflict.request_id:
            raise ValueError(
                "Session conflict lacks correlated AWS request evidence"
            ) from conflict
        write_export(
            acceptance.folder / "session-invalidation.json",
            {
                "request_id": conflict.request_id,
                "trace_id": conflict.trace_id,
                "session_id": str(session),
                "http_status": 409,
                "prior_approval_reused": False,
            },
        )
    else:
        raise ValueError("Policy update did not invalidate the prior session")
    new_session = uuid4()
    new_inputs = dict(inputs, session_id=str(new_session), ttl_minutes=ttl + 1)
    if (await gateway.invoke(action.action_class, new_inputs, new_session)).allowed:
        raise ValueError("Replacement session reused prior consent")
    reference = await activate(*phone, seed.yaml)
    job = await publication(p, publisher, reference, acceptance)
    write_export(
        acceptance.folder / "invalidation-restoration.json",
        json.loads(json.dumps(job, default=str)),
    )
    if job["status"] != "committed":
        raise ValueError("Original seed restoration failed")
    p.bundle = await reload_policy(p)


async def target_evidence(
    acceptance: Acceptance, records: list[dict[str, Any]]
) -> None:
    allowed = {r["aws"]["request_id"] for r in records if r["aws"]["allowed"]}
    denied = {r["aws"]["request_id"] for r in records if not r["aws"]["allowed"]}
    if not allowed or not denied:
        raise ValueError(
            "Enforcement requires both positive and negative target controls"
        )
    logs = acceptance.client("logs")
    for _ in range(12):
        seen = set()
        token: dict[str, str] = {}
        for _ in range(100):
            page = await call(
                logs,
                "filter_log_events",
                logGroupName=acceptance.outputs["ActionsLog"],
                filterPattern="{ $.acceptance_only = true }",
                **token,
            )
            for event in page.get("events", []):
                value = json.loads(event["message"])
                if value.get("executed") is not False:
                    raise ValueError("Target evidence is not inert")
                seen.add(value["request_id"])
            if not page.get("nextToken"):
                break
            token = {"nextToken": page["nextToken"]}
        else:
            raise ValueError("Incomplete target invocation evidence")
        if denied & seen:
            raise ValueError("A denied ENFORCE call reached the target")
        if allowed <= seen:
            write_export(
                acceptance.folder / "target-enforcement.json",
                {
                    "allowed_requests_seen": sorted(allowed),
                    "denied_requests_absent": sorted(denied),
                    "device_execution": False,
                },
            )
            return
        await asyncio.sleep(5)
    raise ValueError("Target positive controls were not observed")


async def expiry(
    seed: Seed, gateway: Gateway, acceptance: Acceptance
) -> dict[str, Any]:
    policy = loads(seed.yaml)
    compiled = compile_policy(policy)
    action, facts = situation(policy, "security.door_unlock")
    session = uuid4()
    ttl = resolve(policy, action, facts).approval.ttl_minutes
    inputs = boundary_input(
        compiled,
        action,
        facts,
        ttl_minutes=ttl,
        session_id=str(session),
        approver_role="owner",
        approval_channel="app_push",
        quorum_satisfied=True,
    )
    approved = await gateway.invoke("governance.approve_action", inputs, session)
    if not approved.allowed:
        raise ValueError("Live expiry requires an allowed approval")
    start = time.monotonic()
    while time.monotonic() - start <= ttl * 60 + 1:
        acceptance.within_window()
        await asyncio.sleep(
            min(30, max(0.1, ttl * 60 + 2 - (time.monotonic() - start)))
        )
        print("Waiting for real Gateway approval expiry", flush=True)
    verdict = await gateway.invoke(action.action_class, inputs, session)
    if verdict.allowed:
        raise ValueError("Gateway accepted an expired approval")
    return {
        "elapsed_seconds": time.monotonic() - start,
        "ttl_minutes": ttl,
        "decision": asdict(verdict),
        "synthetic_time": False,
    }


async def live(acceptance: Acceptance) -> None:
    route = Route(
        acceptance.outputs["PolicyEngine"],
        acceptance.outputs["GatewayArn"],
        acceptance.outputs["Gateway"],
    )
    sdk = acceptance.client("bedrock-agentcore-control")
    publisher = Publisher(
        sdk,
        route.engine_id,
        gateway_id=route.gateway_arn.rsplit("/", 1)[-1],
        target_id=acceptance.outputs["GatewayTarget"],
    )
    secret = await call(
        acceptance.client("secretsmanager"),
        "get_secret_value",
        SecretId=acceptance.outputs["MachineSecret"],
    )
    gateway = AcceptanceGateway(
        route,
        "https://hirz-item36-661550216013.auth.us-east-1.amazoncognito.com/oauth2/token",
        acceptance.outputs["MachineClient"],
        secret["SecretString"],
        acceptance.client("logs"),
    )
    gateway.acceptance = acceptance
    writer = AuditWriter(signing_key(read_env(Path(".env"))))
    seeds = policy_seeds()
    desired = inventory(
        [
            compile_policy(
                loads(seed.yaml), route.gateway_arn, engine="agentcore-policy"
            )
            for seed in seeds
        ]
    )
    async with disposable(read_env(Path(".env"))) as connection:
        await load_seeds(connection, seeds, now)
        service = Companion(
            connection.engine, writer, CONFIG, policy_routes=policy_routes(route)
        )
        pipelines = []
        phones = []
        try:
            for seed in seeds:
                p = Pipeline(
                    connection,
                    await PolicyBundle.validate(
                        seed.household_id, loads(seed.yaml), Dogwood()
                    ),
                    Dogwood(),
                    writer,
                    now,
                    require_active=True,
                    policy_route=route,
                )
                http, key = await phone(service, p, seed)
                phones.append((http, key))
                reference = await activate(http, key, seed.yaml)
                job = await publication(p, publisher, reference, acceptance)
                write_export(
                    acceptance.folder / (seed.slug + "-publication.json"),
                    json.loads(json.dumps(job, default=str)),
                )
                if job["status"] != "committed":
                    raise ValueError(
                        "AWS rejected the production compiler; revise the decision without bypassing findings"
                    )
                p.bundle = await reload_policy(p)
                pipelines.append(p)
            if not await publisher.step(desired):
                raise ValueError("Installed policy inventory differs")
            # Deliberately broken compiler is scoped to this disposable acceptance only.
            real_compile = compile_policy

            def faulty(*args: Any, **kwargs: Any) -> Any:
                compiled = real_compile(*args, **kwargs)
                bad = Statement(
                    "isolated_faulty_compiler",
                    f'permit (principal, action, resource == AgentCore::Gateway::"{route.gateway_arn}");',
                )
                return replace(compiled, statements=(*compiled.statements, bad))

            http, key = phones[0]
            reference = await activate(http, key, seeds[0].yaml)
            with patch("hirz.aws.publication.compile_policy", side_effect=faulty):
                rejected = await publication(
                    pipelines[0], publisher, reference, acceptance
                )
            write_export(
                acceptance.folder / "faulty-compiler.json",
                json.loads(json.dumps(rejected, default=str)),
            )
            findings = json.dumps(rejected["findings"]).lower()
            if (
                rejected["status"] != "failed"
                or "always" not in findings
                or "allow" not in findings
                or not await publisher.step(desired)
            ):
                raise ValueError(
                    "Faulty-compiler refusal and restoration are unverified"
                )
            await invalidation(
                pipelines[0], phones[0], seeds[0], gateway, publisher, acceptance
            )
            if not await publisher.step(desired):
                raise ValueError(
                    "Post-invalidation inventory differs from original seeds"
                )
            records = []
            for p, seed in zip(pipelines, seeds, strict=True):
                records.extend(
                    await compare(p, seed, gateway, desired, acceptance, "LOG_ONLY")
                )
            write_export(
                acceptance.folder / "log-only.json",
                {"records": records, "inventory_hash": fingerprint(desired)},
            )
            await promote(publisher, sdk, route, desired, records, seeds)
            enforced = []
            for p, seed in zip(pipelines, seeds, strict=True):
                enforced.extend(
                    await compare(p, seed, gateway, desired, acceptance, "ENFORCE")
                )
            await target_evidence(acceptance, enforced)
            write_export(
                acceptance.folder / "expiry.json",
                await expiry(seeds[0], gateway, acceptance),
            )
            write_export(
                acceptance.folder / "policy-result.json",
                {
                    "disagreements": 0,
                    "cases_per_mode": len(records),
                    "inventory_hash": fingerprint(desired),
                    "device_execution": False,
                    "randomized_and_exact_time_endpoints": "local native tests only",
                },
            )
        finally:
            for http, _ in phones:
                await http.aclose()
            for seed in seeds:
                async with connection.begin():
                    _, rows = await verify_database(
                        connection,
                        seed.household_id,
                        writer.key.public_key(),
                        collect=True,
                    )
                path = acceptance.folder / (seed.slug + "-audit.json")
                write_export(
                    path,
                    export_document(seed.household_id, writer.key.public_key(), rows),
                )
                verify_file(path, seed.household_id, key=writer.key.public_key())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["offline", "live"])
    parser.add_argument("--artifacts-dir", type=Path)
    parser.add_argument("--billing-clearance", type=Path)
    args = parser.parse_args()
    if args.mode == "offline":
        seeds = policy_seeds()
        print(
            json.dumps(
                {
                    "cases": sum(len(corpus(seed)) for seed in seeds),
                    "live": "not run",
                    "device_execution": False,
                }
            )
        )
        return
    clearance(args.billing_clearance)
    if args.artifacts_dir is None:
        parser.error("Live acceptance requires private artifacts")
    acceptance = Acceptance(args.artifacts_dir)
    try:
        acceptance.within_window()
        policy_tracing(acceptance)
        asyncio.run(live(acceptance))
    finally:
        write_export(acceptance.folder / "policy-cleanup.json", destroy(acceptance))


if __name__ == "__main__":
    main()
