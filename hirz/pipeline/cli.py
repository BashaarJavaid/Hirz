"""Hypothetical local decisions against stored, unactivated demo policies."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa

from hirz import db
from hirz.constitution.boundary import Dogwood
from hirz.constitution.schema import loads
from hirz.graph.models import now, utc
from hirz.graph.seeds import demo_id
from hirz.local import LocalError, read_env, signing_key
from hirz.pipeline.audit import AuditWriter
from hirz.pipeline.hashing import action_hash, digest
from hirz.pipeline.models import Action, Principal
from hirz.pipeline.preview import PreviewEvidence
from hirz.pipeline.service import Pipeline, PolicyBundle, estimate

HOMES = {demo_id(s, "households", s): s for s in ("quinn-home", "quinn-parents")}


def add_decide(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = commands.add_parser(
        "decide",
        help="Dry-run a hypothetical action; stored policy remains unactivated",
    )
    # Validate values ourselves so argparse never echoes private input on type errors.
    for name, help_text in {
        "household": "Seeded demo household UUID",
        "as": "Hypothetical demo account subject; not authentication",
        "surface": "alexa, app, or scheduler",
        "action": "Canonical action class",
        "adapter": "Target adapter from the household binding",
        "entity": "Target entity from the household binding, or scoped UUID",
        "params": "Action parameters as a JSON object",
    }.items():
        parser.add_argument("--" + name, required=True, help=help_text)
    parser.add_argument("--zone", help="Household HVAC zone UUID")
    parser.add_argument(
        "--cost", help="Exact nonnegative dollar estimate; omitted = unknown"
    )
    parser.add_argument(
        "--at",
        help="Aware ISO timestamp; current graph at this clock, not historical replay",
    )
    parser.add_argument(
        "--evidence",
        help="JSON file of explicit source=twin preview observations, asset_rooms and scam_pattern",
    )
    parser.add_argument(
        "--requester-confirmed",
        action="store_true",
        help="Hypothetical confirmation only",
    )


def json_input(text: str) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    value = json.loads(text, object_pairs_hook=unique)
    digest(value)  # Reject nonfinite numbers and values outside canonical JSON limits.
    return value


async def decide_command(args: argparse.Namespace) -> int:
    try:
        evidence_text = Path(args.evidence).read_text() if args.evidence else "{}"
    except (OSError, UnicodeError):
        print(
            "Cannot read evidence file; check its path and encoding.", file=sys.stderr
        )
        return 1
    try:
        household = UUID(args.household)
        if household not in HOMES:
            raise ValueError("Only seeded demo households are supported")
        at = utc(datetime.fromisoformat(args.at)) if args.at else now()
        cost = Decimal(args.cost) if args.cost is not None else None
        estimate(cost)
        params = json_input(args.params)
        if not isinstance(params, dict):
            raise ValueError("Parameters must be an object")
        principal = Principal(
            provider="demo",
            sub=vars(args)["as"],
            surface=args.surface,
            requester_confirmed=args.requester_confirmed,
        )
        action = Action.model_validate(
            {
                "action_id": "act_" + uuid4().hex,
                "class": args.action,
                "target": {
                    "adapter": args.adapter,
                    "entity": args.entity,
                    "zone": str(UUID(args.zone)) if args.zone is not None else None,
                },
                "params": params,
                "requested_by": {
                    "member_id": None,
                    "role": "unknown",
                    "surface": args.surface,
                },
                "reason": "Hypothetical CLI dry run",
                "content_hash": "",
            }
        )
        action = action.model_copy(update={"content_hash": action_hash(action)})
        raw = json_input(evidence_text)
        preview = PreviewEvidence.model_validate(raw) if raw else None
        if not isinstance(raw, dict):
            raise ValueError("Evidence must be an object")
    except (ValueError, TypeError, ArithmeticError):
        print(
            "Invalid decide input; check --help, UUIDs, aware timestamps, exact cost, "
            "canonical JSON parameters and source=twin evidence. Input values withheld.",
            file=sys.stderr,
        )
        return 2

    try:
        values = read_env(Path(".env"))
        writer = AuditWriter(signing_key(values))
        boundary = Dogwood()
        async with db.connect_database(values) as connection:
            await connection.run_sync(db.require_current)
            row = (
                (
                    await connection.execute(
                        sa.select(db.constitution_versions)
                        .join(
                            db.households,
                            sa.and_(
                                db.households.c.id
                                == db.constitution_versions.c.household_id,
                                db.households.c.constitution_version
                                == db.constitution_versions.c.version,
                            ),
                        )
                        .where(db.households.c.id == household)
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise LocalError("Stored demo policy is missing; no preview returned.")
            if (
                row["status"] != "unvalidated"
                or row["hash"] != sha256(row["yaml"].encode()).hexdigest()
                or row["compiled_cedar"] is not None
                or row["activated_at"] is not None
            ):
                raise LocalError(
                    "Stored policy integrity check failed; no preview returned."
                )
            policy = loads(row["yaml"])
            if policy.household != HOMES[household] or policy.version != row["version"]:
                raise LocalError(
                    "Stored policy household/version mismatch; no preview returned."
                )
            await connection.rollback()
            bundle = await PolicyBundle.validate(household, policy, boundary)
            decision = await Pipeline(
                connection, bundle, boundary, writer, lambda: at
            ).evaluate(action, principal, cost=cost, preview=preview)
        print(
            f"Hypothetical dry run; policy v{policy.version} is unactivated "
            f"(stored: unvalidated); clock={at.isoformat()}; current graph, not historical replay. "
            "No authentication, approval, execution grant, device operation, or audit write. "
            "Supplied evidence is simulated; boundary is dogwood-local.",
            file=sys.stderr,
        )
        print(decision.model_dump_json(by_alias=True))
        return 0
    except LocalError as exc:
        print(str(exc), file=sys.stderr)
    except Exception:
        print(
            "Decision preview failed; check Postgres, migrations, the stored policy, "
            "and native Dogwood. No policy was replaced; private values withheld.",
            file=sys.stderr,
        )
    return 1
