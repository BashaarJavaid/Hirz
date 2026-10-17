"""Inert item 37 target. A response never means that a device action executed."""

import json
import math
import re
from pathlib import Path
from typing import Any
from uuid import UUID

CONTRACT = json.loads(Path(__file__).with_name("contract.json").read_text())


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    # https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-add-target-lambda.html
    try:
        tool = context.client_context.custom["bedrockAgentCoreToolName"]
    except (AttributeError, KeyError, TypeError):
        raise ValueError("Gateway invocation context required") from None
    print(
        json.dumps(
            {
                "acceptance_only": True,
                "executed": False,
                "request_id": context.client_context.custom[
                    "bedrockAgentCoreAwsRequestId"
                ],
            }
        )
    )
    name = tool.removeprefix("HirzActions___")
    if tool == name or name not in CONTRACT["names"]:
        raise ValueError("Unknown boundary tool")
    schema = CONTRACT["inputSchema"]
    if not isinstance(event, dict) or not set(schema["required"]) <= event.keys():
        raise ValueError("Missing boundary inputs")
    for key, value in event.items():
        field = schema["properties"].get(key)
        if field is None and re.fullmatch(r"p_[0-9a-f]{16}", key):
            field = {"type": "boolean"}
        if field is None:
            raise ValueError("Unknown boundary input")
        valid = {
            "string": isinstance(value, str),
            "integer": type(value) is int,
            "boolean": type(value) is bool,
            "number": type(value) in (int, float) and math.isfinite(value),
            "array": isinstance(value, list) and all(isinstance(v, str) for v in value),
        }
        if not valid[field["type"]]:
            raise ValueError("Invalid boundary input")
    UUID(event["session_id"])
    if (
        not 1 <= event["ttl_minutes"] <= 1440
        or not event["household"]
        or not event["action_hash"]
    ):
        raise ValueError("Invalid boundary binding")
    approval = name == "governance_approve_action"
    if not approval and event["action_class"].replace(".", "_") != name:
        raise ValueError("Action class mismatch")
    return {
        "approved": approval and event["quorum_satisfied"],
        "ttl_minutes": event["ttl_minutes"],
        "executed": False,
    }
