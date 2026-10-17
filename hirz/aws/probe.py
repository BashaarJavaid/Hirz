"""One-off, twin-only acceptance probes using the actual task role and Pipeline."""

import argparse
import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from hirz import db
from hirz.audit import export_document, verify_database
from hirz.aws.client import client
from hirz.aws.config import database, secret
from hirz.aws.evidence import seal
from hirz.aws.fixture import load
from hirz.companion.auth import initial_invitation
from hirz.constitution.boundary import Dogwood
from hirz.executor.local import compose, policy
from hirz.executor.observations import ingest
from hirz.executor.twin import restore
from hirz.graph.models import now
from hirz.local import signing_key
from hirz.pipeline.audit import AuditWriter
from hirz.pipeline.hashing import action_hash
from hirz.pipeline.models import Action, Principal
from hirz.pipeline.service import Pipeline, PolicyBundle
from hirz.twin.clock import SimClock

PRINCIPAL = Principal(
    provider="demo", sub="malik", surface="app", requester_confirmed=True
)


def iam() -> dict[str, Any]:
    operations: list[tuple[str, str, dict[str, Any]]] = [
        (
            "kms",
            "sign",
            {
                "KeyId": os.environ["HIRZ_COMMAND_KEY"],
                "Message": b"hirz-item36-noncommand",
                "MessageType": "RAW",
                "SigningAlgorithm": "ECDSA_SHA_256",
            },
        ),
        (
            "secretsmanager",
            "get_secret_value",
            {"SecretId": os.environ["HIRZ_IDENTITY_SECRET"]},
        ),
        (
            "bedrock-agentcore",
            "get_resource_api_key",
            {
                "resourceCredentialProviderName": "hirz-item36-synthetic",
                "workloadIdentityToken": os.environ["HIRZ_PROBE_WORKLOAD_TOKEN"],
            },
        ),
    ]
    denied = []
    for service, method, kwargs in operations:
        try:
            getattr(client(service), method)(**kwargs)
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code not in {"AccessDenied", "AccessDeniedException"}:
                raise ValueError(
                    "IAM probe failed without a proven access denial"
                ) from None
            denied.append(service + ":" + method)
        else:
            raise ValueError(
                "Worker unexpectedly obtained signing or credential authority"
            )
    return {"denied": denied, "role": client("sts").get_caller_identity()["Arn"]}


async def run(
    operation: str, action_id: str | None, due: datetime | None
) -> dict[str, Any]:
    if operation == "iam":
        return iam()
    engine = database(secret("HIRZ_DATABASE_SECRET"))
    audit = AuditWriter(signing_key({"AUDIT_SIGNING_KEY": secret("HIRZ_AUDIT_SECRET")}))
    loaded = load()
    boundary = Dogwood()
    try:
        async with boundary.persistent(), engine.connect() as connection:
            await connection.run_sync(db.require_current)
            await connection.rollback()
            p = Pipeline(
                connection,
                await PolicyBundle.validate(
                    loaded.world.household.id, loaded.execution_policy, boundary
                ),
                boundary,
                audit,
                now,
                require_active=True,
            )
            p.bundle = await policy(p)
            if operation == "cancel":
                return await cancellation(p, loaded)
            if operation == "invite":
                return {
                    "origin": os.environ["HIRZ_COMPANION_ORIGIN"],
                    "token": await initial_invitation(
                        p, loaded.ref("members", "malik")
                    ),
                    "household": str(p.household_id),
                }
            if operation == "export":
                summary, rows = await verify_database(
                    connection, p.household_id, audit.key.public_key(), collect=True
                )
                return {
                    "summary": summary,
                    "audit": export_document(
                        p.household_id, audit.key.public_key(), rows
                    ),
                }
            if operation == "inspect":
                async with connection.begin():
                    row = (
                        (
                            await connection.execute(
                                sa.select(db.actions).where(
                                    p.scope(db.actions),
                                    db.actions.c.action_id == action_id,
                                )
                            )
                        )
                        .mappings()
                        .one()
                    )
                    events = (
                        (
                            await connection.execute(
                                sa.select(db.audit_log)
                                .where(
                                    p.scope(db.audit_log),
                                    db.audit_log.c.payload["action_id"].astext
                                    == action_id,
                                )
                                .order_by(db.audit_log.c.seq)
                            )
                        )
                        .mappings()
                        .all()
                    )
                return {
                    "action": dict(row),
                    "events": [dict(r) for r in events],
                    "engine": "dogwood-local",
                    "source": "twin",
                }
            if (
                operation != "schedule"
                or due is None
                or due.tzinfo is None
                or due < now() + timedelta(minutes=30)
            ):
                raise ValueError(
                    "Quiet acceptance action must be at least 30 wall-clock minutes away"
                )
            await restore(p, loaded.world)
            loaded.world.clock = SimClock(now(), 1)
            registry = await compose(
                p,
                world=loaded.world,
                config=",".join(f"{d}:twin" for d in loaded.spec.adapters),
            )
            await registry.start()
            try:
                await ingest(p, registry, PRINCIPAL)
                a = Action.model_validate(
                    {
                        "action_id": uuid4().hex,
                        "class": "environment.lights",
                        "target": {"adapter": "twin", "entity": "light.living_room"},
                        "params": {"on": True},
                        "requested_by": {
                            "member_id": None,
                            "role": "unknown",
                            "surface": "app",
                        },
                        "reason": "Explicit disposable AWS acceptance twin-light action",
                        "scheduled_for": due,
                        "expected_effect": {
                            "entity": "light.living_room",
                            "attr": "on",
                            "value": True,
                            "by": due + timedelta(seconds=90),
                        },
                        "content_hash": "",
                    }
                )
                a = a.model_copy(update={"content_hash": action_hash(a)})
                decision = await p.enqueue(a, PRINCIPAL)
                if decision.status != "executing":
                    raise ValueError(
                        "Acceptance action was not authorized; inspect the signed decision"
                    )
                return {
                    "action_id": a.action_id,
                    "household": str(p.household_id),
                    "due": due.isoformat(),
                    "decision": decision.model_dump(mode="json", by_alias=True),
                }
            finally:
                await registry.close()
    finally:
        await engine.dispose()


async def cancellation(p: Pipeline, loaded: Any) -> dict[str, Any]:
    from hirz.executor.plans import PlanService, schedule_approved
    from hirz.executor.runtime import RuntimeInputs
    from hirz.pipeline.models import Plan, Requester
    from hirz.planner.models import Control, PlannerInput, Schedule, Slot

    start = now() + timedelta(minutes=5)
    end = start + timedelta(minutes=5)
    plan_id, action_id = uuid4().hex, uuid4().hex
    action = Action.model_validate(
        {
            "action_id": action_id,
            "plan_id": plan_id,
            "class": "environment.lights",
            "target": {"adapter": "twin", "entity": "light.living_room"},
            "params": {"on": False},
            "requested_by": {"member_id": None, "role": "unknown", "surface": "app"},
            "reason": "Explicit cancellation acceptance fixture",
            "scheduled_for": start,
            "expected_effect": {
                "entity": "light.living_room",
                "attr": "on",
                "value": False,
                "by": end,
            },
            "content_hash": "",
        }
    )
    action = action.model_copy(update={"content_hash": action_hash(action)})
    plan = Plan.model_validate(
        {
            "plan_id": plan_id,
            "household_id": p.household_id,
            "version": 1,
            "horizon": {"start": start, "end": end},
            "goals": ["Synthetic cancellation fixture"],
            "constraints": [],
            "actions": [action_id],
            "summary": {
                "estimated_savings_usd": None,
                "peak_kwh_avoided": None,
                "grid_kwh": 0,
                "solar_kwh": 0,
                "exported_kwh": 0,
                "electricity_usd": 0,
                "wear_usd": 0,
                "comfort_violations_minutes": 0,
            },
            "alternatives": [],
            "explain": {},
            "speakable": {"headline": "Synthetic cancellation fixture"},
            "method": "greedy",
            "comparison_validity": {
                "valid": False,
                "reasons": ["Synthetic fixture, no saving claimed"],
            },
        }
    )
    inputs = PlannerInput(
        household_id=p.household_id,
        requester=Requester(member_id=None, role="unknown", surface="app"),
        slots=(Slot(start=start, end=end, price=0, outdoor_f=70, solar_kw=0),),
        ev=None,
        ev_target=0,
        ev_deadline=end,
        battery=None,
        zones=(),
        appliance=None,
        appliance_release=start,
        appliance_deadline=end,
        base_load_kw=0,
        provenance=("Explicit synthetic cancellation fixture",),
    )
    runtime = RuntimeInputs.from_schedule(
        inputs,
        Schedule(
            controls=(
                Control(
                    ev_kwh=0, battery_kw=0, targets=(), modes=(), appliance_start=False
                ),
            ),
            method="greedy",
        ),
    )
    service = PlanService(p)
    for decision in (
        await service.record(plan, (action,), PRINCIPAL, runtime=runtime),
        await service.approve(plan_id, PRINCIPAL),
    ):
        if decision.decision != "execute":
            raise ValueError("Cancellation probe requires actual Pipeline grants")
    await schedule_approved(p)
    async with p.connection.begin():
        status = await p.connection.scalar(
            sa.select(db.actions.c.execution_status).where(
                p.scope(db.actions), db.actions.c.action_id == action_id
            )
        )
    if status != "scheduled":
        raise ValueError("Cancellation probe did not schedule its action")
    from hirz.aws.client import call
    from hirz.aws.schedules import name, reconcile

    sdk = client("scheduler")
    schedule_name = name(p.household_id, action_id)
    group = os.environ["HIRZ_SCHEDULE_GROUP"]

    async def synchronize() -> None:
        await reconcile(
            p.connection,
            sdk,
            group=group,
            target=os.environ["HIRZ_TICK_ARN"],
            role=os.environ["HIRZ_SCHEDULE_ROLE"],
            at=now(),
        )

    await synchronize()
    derived = await call(sdk, "get_schedule", GroupName=group, Name=schedule_name)
    if derived["Name"] != schedule_name:
        raise ValueError("Cancellation fixture has no derived schedule")
    decision = await service.cancel(plan_id, PRINCIPAL)
    if decision.decision != "execute":
        raise ValueError("Pipeline refused cancellation")
    async with p.connection.begin():
        status = await p.connection.scalar(
            sa.select(db.actions.c.execution_status).where(
                p.scope(db.actions), db.actions.c.action_id == action_id
            )
        )
    if status != "cancelled":
        raise ValueError("Cancelled action remained executable")
    await synchronize()
    try:
        await call(sdk, "get_schedule", GroupName=group, Name=schedule_name)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
    else:
        raise ValueError("Cancelled action retained its one-time schedule")
    return {
        "plan": plan_id,
        "action": action_id,
        "household": str(p.household_id),
        "status": status,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=["iam", "invite", "schedule", "inspect", "export", "cancel"],
    )
    parser.add_argument("--action-id")
    parser.add_argument("--due", type=datetime.fromisoformat)
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args.operation, args.action_id, args.due))
        encoded = json.dumps(seal(result, os.environ["HIRZ_EVIDENCE_RECIPIENT"]))
        # CloudWatch events have bounded size. Chunks carry encrypted bytes only.
        for i in range(0, len(encoded), 16000):
            print(
                "HIRZ_EVIDENCE "
                + json.dumps({"index": i // 16000, "data": encoded[i : i + 16000]}),
                flush=True,
            )
    except Exception as exc:
        print(json.dumps({"status": "failed", "type": type(exc).__name__}), flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
