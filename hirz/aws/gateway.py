"""Machine-authenticated Gateway calls with actual correlated policy evidence."""

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID, uuid4

import httpx

from hirz.aws.client import call
from hirz.aws.policy import wire_json
from hirz.aws.routing import Route
from hirz.constitution.compiler import action_name


class SessionConflict(ValueError):
    def __init__(
        self, message: str, request_id: str | None = None, trace_id: str | None = None
    ):
        super().__init__(message)
        self.request_id, self.trace_id = request_id, trace_id


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    request_id: str
    trace_id: str
    policy_ids: tuple[str, ...]
    mode: str
    target: dict[str, Any] | None


class Gateway:
    def __init__(
        self, route: Route, token_url: str, client_id: str, secret: str, logs: Any
    ):
        if not route.gateway_url.startswith("https://") or not token_url.startswith(
            "https://"
        ):
            raise ValueError("AWS endpoints require HTTPS")
        self.route, self.token_url, self.client_id, self.secret, self.logs = (
            route,
            token_url,
            client_id,
            secret,
            logs,
        )
        self.token = ""
        self.expires = 0.0

    async def invoke(
        self, name: str, inputs: dict[str, Any], session_id: UUID
    ) -> Verdict:
        if inputs.get("session_id") != str(session_id):
            raise ValueError("Gateway session binding differs from header")
        trace = f"1-{int(time.time()):08x}-{uuid4().hex[:24]}"
        request_id = uuid4().hex
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as http:
            if time.monotonic() >= self.expires:
                token = await http.post(
                    self.token_url,
                    auth=(self.client_id, self.secret),
                    data={
                        "grant_type": "client_credentials",
                        "scope": "hirz-gateway/invoke",
                    },
                )
                token.raise_for_status()
                data = token.json()
                if (
                    data.get("token_type", "").lower() != "bearer"
                    or not isinstance(data.get("access_token"), str)
                    or not 30 < data["expires_in"] <= 3600
                ):
                    raise ValueError("Invalid machine token response")
                self.token, self.expires = (
                    data["access_token"],
                    time.monotonic() + data["expires_in"] - 30,
                )
            response = await http.post(
                self.route.gateway_url,
                headers={
                    "Authorization": "Bearer " + self.token,
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    "x-amzn-bedrock-agentcore-policy-session-id": str(session_id),
                    "X-Amzn-Trace-Id": f"Root={trace};Parent={uuid4().hex[:16]};Sampled=1",
                },
                content=wire_json(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "tools/call",
                        "params": {
                            "name": action_name(name).split('"')[1],
                            "arguments": inputs,
                        },
                    }
                ),
            )
        if response.status_code == 409:
            raise SessionConflict(
                "Policy session invalidated; new approval required",
                response.headers.get("x-amzn-requestid"),
                trace,
            )
        if response.status_code != 403:
            response.raise_for_status()
        body = response.json()
        if body.get("id") != request_id or body.get("jsonrpc") != "2.0":
            raise ValueError("Uncorrelated Gateway response")
        target = body.get("result")
        if target is not None and not isinstance(target, dict):
            raise ValueError("Malformed Gateway result")
        aws_request = response.headers.get("x-amzn-requestid")
        if not aws_request:
            raise ValueError("Gateway request evidence missing")
        for _ in range(10):
            verdicts = []
            pagination: dict[str, str] = {}
            seen: set[str] = set()
            # CloudWatch can return a continuation even for a partially empty page.
            for _ in range(10):
                page = await call(
                    self.logs,
                    "filter_log_events",
                    logGroupName="aws/spans",
                    startTime=(int(trace.split("-")[1], 16) - 5) * 1000,
                    filterPattern='"' + trace.rsplit("-", 1)[-1] + '"',
                    limit=100,
                    **pagination,
                )
                for event in page.get("events", []):
                    span = json.loads(event["message"])
                    attributes = span.get("attributes", {})
                    if (
                        attributes.get("aws.agentcore.policy.authorization_decision")
                        is not None
                    ):
                        verdicts.append(
                            evidence(span, trace, self.route, aws_request, target)
                        )
                following = page.get("nextToken")
                if following is None:
                    break
                if not isinstance(following, str) or not following or following in seen:
                    raise ValueError("Incomplete AWS policy evidence")
                seen.add(following)
                pagination = {"nextToken": following}
            else:
                raise ValueError("Incomplete AWS policy evidence")
            if len(verdicts) == 1:
                verdict = verdicts[0]
                if verdict.allowed:
                    output = receipt(target)
                    if output["ttl_minutes"] != inputs.get("ttl_minutes") or output[
                        "approved"
                    ] != (
                        name == "governance.approve_action"
                        and inputs.get("quorum_satisfied")
                    ):
                        raise ValueError(
                            "Inert receipt does not match the evaluated input"
                        )
                return verdict
            if verdicts:
                raise ValueError("Ambiguous AWS policy evidence")
            await asyncio.sleep(1)
        raise ValueError("AWS policy evidence unavailable; no authorization")


def evidence(
    span: dict[str, Any],
    trace: str,
    route: Route,
    request_id: str,
    target: dict[str, Any] | None,
) -> Verdict:
    a = span["attributes"]
    decision = a.get("aws.agentcore.policy.authorization_decision")
    policies = a.get("aws.agentcore.policy.determining_policies")
    if (
        span.get("traceId") not in {trace, trace[2:].replace("-", "")}
        or a.get("aws.agentcore.policy.target_resource.id")
        not in {route.gateway_arn, route.gateway_arn.rsplit("/", 1)[-1]}
        or a.get("aws.agentcore.gateway.policy.arn", "").rsplit("/", 1)[-1]
        != route.engine_id
        or a.get("aws.agentcore.gateway.policy.mode") not in {"LOG_ONLY", "ENFORCE"}
        or decision not in {"ALLOW", "DENY"}
        or not isinstance(policies, list)
        or not all(isinstance(v, str) for v in policies)
        or a.get("aws.agentcore.policy.mismatched_policies") not in ([], None)
        or a.get("aws.agentcore.policy.log_only_eval_incomplete") not in (None, "false")
    ):
        raise ValueError("Invalid or incomplete AWS policy evidence")
    if decision == "ALLOW" and (
        not policies or target is None or target.get("isError") is True
    ):
        raise ValueError("AWS permit lacks successful target evidence")
    if (
        decision == "DENY"
        and a["aws.agentcore.gateway.policy.mode"] == "ENFORCE"
        and target is not None
        and target.get("isError") is not True
    ):
        raise ValueError("Enforced denial returned a successful target response")
    return Verdict(
        decision == "ALLOW",
        request_id,
        trace,
        tuple(policies),
        a["aws.agentcore.gateway.policy.mode"],
        target,
    )


def receipt(target: dict[str, Any] | None) -> dict[str, Any]:
    if target is None or target.get("isError") is True:
        raise ValueError("Missing successful inert target receipt")
    value = target.get("structuredContent")
    if value is None:
        content = target.get("content", [])
        if len(content) != 1 or content[0].get("type") != "text":
            raise ValueError("Malformed inert target receipt")
        value = json.loads(content[0]["text"])
    if (
        not isinstance(value, dict)
        or value.get("executed") is not False
        or type(value.get("approved")) is not bool
        or type(value.get("ttl_minutes")) is not int
    ):
        raise ValueError("Target did not confirm inert evaluation")
    return cast(dict[str, Any], value)
