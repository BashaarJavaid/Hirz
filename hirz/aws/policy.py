"""Private Gateway schema and bounded policy reconciliation. Never device execution."""

import hashlib
import json
import re
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from hirz.aws.client import call
from hirz.constitution.compiler import TEMPORAL_LIMIT, Compiled
from hirz.constitution.conditions import number
from hirz.risk import CLASSES


def tools(compiled: Sequence[Compiled]) -> list[dict[str, Any]]:
    fields: dict[str, str] = {}
    for bundle in compiled:
        for name, kind in bundle.manifest["input_fields"].items():
            if name in fields and fields[name] != kind:
                raise ValueError("Conflicting Gateway field types")
            fields[name] = kind
    if not fields:
        raise ValueError("Gateway requires a compiled contract")
    types = {
        "String": "string",
        "Long": "integer",
        "Bool": "boolean",
        "decimal": "number",
    }
    properties = {
        name.rstrip("?"): {"type": types[kind]}
        if kind != "Set<String>"
        else {"type": "array", "items": {"type": "string"}}
        for name, kind in sorted(fields.items())
    }
    inputs = {
        "type": "object",
        "properties": properties,
        "required": sorted(n for n in fields if not n.endswith("?")),
    }
    return [
        {
            "name": name.replace(".", "_"),
            "description": "Inert policy acceptance; evaluates supplied facts without executing a device action.",
            "inputSchema": inputs,
            "outputSchema": {
                "type": "object",
                "properties": {
                    "approved": {"type": "boolean"},
                    "ttl_minutes": {"type": "integer"},
                    "executed": {"type": "boolean"},
                },
                "required": ["approved", "ttl_minutes", "executed"],
            },
        }
        for name in [*CLASSES, "governance.approve_action"]
    ]


def inventory(compiled: Sequence[Compiled]) -> dict[str, str]:
    if len({c.manifest["household"] for c in compiled}) != len(compiled):
        raise ValueError("Duplicate managed household")
    if any(c.manifest["engine"] != "agentcore-policy" for c in compiled):
        raise ValueError("Local households cannot be published")
    statements = {s.name: s.text for c in compiled for s in c.statements}
    quota(statements)
    return statements


def quota(desired: dict[str, str], installed: dict[str, str] | None = None) -> None:
    # Updates reuse names; additions must fit before obsolete statements are deleted.
    peak = (installed or {}) | desired
    if (
        len(peak) > 1000
        or sum("when temporal" in s for s in peak.values()) > TEMPORAL_LIMIT
    ):
        raise ValueError("Shared engine policy quota or publication headroom exceeded")


def fingerprint(statements: dict[str, str]) -> str:
    return hashlib.sha256(
        json.dumps(statements, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def wire_json(value: Any) -> str:
    """Emit exact Cedar decimals as JSON numbers, without binary float rounding."""
    if isinstance(value, Decimal):
        return format(number(value), "f")
    if isinstance(value, dict):
        return (
            "{"
            + ",".join(json.dumps(k) + ":" + wire_json(v) for k, v in value.items())
            + "}"
        )
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(wire_json(v) for v in value) + "]"
    return json.dumps(value, allow_nan=False)


class Findings(ValueError):
    def __init__(self, policy: dict[str, Any]):
        self.policy = policy
        super().__init__("AWS policy validation or reconciliation failed")


class Publisher:
    def __init__(
        self,
        sdk: Any,
        engine_id: str,
        *,
        gateway_id: str | None = None,
        target_id: str | None = None,
    ):
        self.sdk, self.engine_id = sdk, engine_id
        self.gateway_id, self.target_id = gateway_id, target_id

    async def contract(self, statements: dict[str, str]) -> bool:
        if self.gateway_id is None or self.target_id is None:
            raise ValueError("Gateway target must be configured for publication")
        target = await call(
            self.sdk,
            "get_gateway_target",
            gatewayIdentifier=self.gateway_id,
            targetId=self.target_id,
        )
        if target["status"] in {"CREATING", "UPDATING", "SYNCHRONIZING"}:
            return False
        if target["status"] != "READY" or target["name"] != "HirzActions":
            raise ValueError("Gateway target is unavailable")
        base = json.loads(
            Path(__file__).with_name("lambdas").joinpath("contract.json").read_text()
        )
        for statement in statements.values():
            for field in re.findall(r"context\.input\.(p_[0-9a-f]{16})", statement):
                base["inputSchema"]["properties"][field] = {"type": "boolean"}
        config = target["targetConfiguration"]
        definitions = config["mcp"]["lambda"]["toolSchema"]["inlinePayload"]
        if {t["name"] for t in definitions} != set(base["names"]):
            raise ValueError("Unexpected private Gateway tools")
        if all(
            t["inputSchema"] == base["inputSchema"]
            and t.get("outputSchema") == base["outputSchema"]
            for t in definitions
        ):
            return True
        for tool in definitions:
            tool.update(
                inputSchema=base["inputSchema"], outputSchema=base["outputSchema"]
            )
        await call(
            self.sdk,
            "update_gateway_target",
            gatewayIdentifier=self.gateway_id,
            targetId=self.target_id,
            name="HirzActions",
            targetConfiguration=config,
            credentialProviderConfigurations=target["credentialProviderConfigurations"],
        )
        return False

    async def installed(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        token = None
        seen: set[str] = set()
        for _ in range(11):
            page = await call(
                self.sdk,
                "list_policies",
                policyEngineId=self.engine_id,
                maxResults=100,
                **({"nextToken": token} if token else {}),
            )
            for policy in page["policies"]:
                if (
                    policy["name"] in result
                    or policy["policyEngineId"] != self.engine_id
                ):
                    raise ValueError("Ambiguous policy inventory")
                result[policy["name"]] = policy
            token = page.get("nextToken")
            if not token:
                return result
            if token in seen:
                break
            seen.add(token)
        raise ValueError("Incomplete policy inventory")

    async def step(self, desired: dict[str, str], *, recovering: bool = False) -> bool:
        """One mutation per tick. True only for the exact, fully active inventory."""
        rows = await self.installed()
        current = {
            name: row.get("definition", {})
            .get("policy", row.get("definition", {}).get("cedar", {}))
            .get("statement", "")
            for name, row in rows.items()
        }
        quota(desired, current)
        for name, row in rows.items():
            status = row["status"]
            if status in {"CREATING", "UPDATING", "DELETING"}:
                return False
            if status != "ACTIVE" or row.get("statusReasons"):
                if not recovering or status not in {"CREATE_FAILED", "UPDATE_FAILED"}:
                    raise Findings(row)
                await call(
                    self.sdk,
                    "delete_policy",
                    policyEngineId=self.engine_id,
                    policyId=row["policyId"],
                )
                return False
        for name, statement in desired.items():
            existing = rows.get(name)
            if (
                existing
                and current[name] == statement
                and existing.get("enforcementMode", "ACTIVE") == "ACTIVE"
            ):
                continue
            args = dict(
                policyEngineId=self.engine_id,
                definition={"policy": {"statement": statement}},
                validationMode="FAIL_ON_ANY_FINDINGS",
                enforcementMode="ACTIVE",
            )
            try:
                if existing:
                    await call(
                        self.sdk, "update_policy", policyId=existing["policyId"], **args
                    )
                else:
                    await call(self.sdk, "create_policy", name=name, **args)
            except ClientError as exc:
                raise Findings(
                    {
                        "name": name,
                        "definition": args["definition"],
                        "aws_response": exc.response,
                    }
                ) from exc
            return False
        for name, row in rows.items():
            if name not in desired:
                await call(
                    self.sdk,
                    "delete_policy",
                    policyEngineId=self.engine_id,
                    policyId=row["policyId"],
                )
                return False
        return True
