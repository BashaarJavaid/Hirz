import asyncio
import json
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest

from hirz.aws.cleanup import empty_policy_engine, policy_tracing
from hirz.aws.gateway import Gateway, SessionConflict, evidence, receipt
from hirz.aws.routing import Route

ROUTE = Route(
    "engine",
    "arn:aws:bedrock-agentcore:us-east-1:123456789012:gateway/test",
    "https://gateway.test/mcp",
)


def span(trace, decision="ALLOW"):
    return {
        "traceId": trace,
        "attributes": {
            "aws.agentcore.policy.authorization_decision": decision,
            "aws.agentcore.policy.determining_policies": ["policy"]
            if decision == "ALLOW"
            else [],
            "aws.agentcore.policy.target_resource.id": ROUTE.gateway_arn,
            "aws.agentcore.gateway.policy.arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:policy-engine/engine",
            "aws.agentcore.gateway.policy.mode": "ENFORCE",
        },
    }


@pytest.mark.parametrize(
    "failure",
    [None, "no_evidence", "wrong_engine", "conflict", "executed", "ambiguous"],
)
def test_gateway_requires_correlated_evidence_and_inert_receipt(monkeypatch, failure):
    session = uuid4()
    logs = Mock()
    calls = []

    def handle(request):
        calls.append(request)
        if request.url.host == "token.test":
            return httpx.Response(
                200,
                json={"access_token": "test", "token_type": "Bearer", "expires_in": 60},
            )
        assert request.headers["x-amzn-bedrock-agentcore-policy-session-id"] == str(
            session
        )
        body = json.loads(request.content)
        trace = request.headers["X-Amzn-Trace-Id"].split(";")[0].removeprefix("Root=")
        record = span(trace)
        if failure == "wrong_engine":
            record["attributes"]["aws.agentcore.gateway.policy.arn"] = "other"
        events = [{"message": json.dumps(record)}] * (
            2 if failure == "ambiguous" else 1
        )
        logs.filter_log_events.return_value = {
            "events": [] if failure == "no_evidence" else events
        }
        return httpx.Response(
            409 if failure == "conflict" else 200,
            headers={"x-amzn-requestid": "request"},
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {
                    "structuredContent": {
                        "executed": failure == "executed",
                        "approved": False,
                        "ttl_minutes": 30,
                    }
                },
            },
        )

    real = httpx.AsyncClient
    monkeypatch.setattr(
        "hirz.aws.gateway.httpx.AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handle), **kw),
    )

    async def run():
        client = Gateway(ROUTE, "https://token.test/token", "client", "secret", logs)
        if failure:
            with pytest.raises(
                SessionConflict if failure == "conflict" else ValueError
            ):
                await client.invoke(
                    "environment.lights",
                    {"session_id": str(session), "ttl_minutes": 30},
                    session,
                )
        else:
            verdict = await client.invoke(
                "environment.lights",
                {"session_id": str(session), "ttl_minutes": 30},
                session,
            )
            assert verdict.allowed and verdict.request_id == "request"
            await client.invoke(
                "environment.lights",
                {"session_id": str(session), "ttl_minutes": 30},
                session,
            )
            assert sum(r.url.host == "token.test" for r in calls) == 1
        with pytest.raises(ValueError, match="session binding"):
            await client.invoke(
                "environment.lights", {"session_id": str(uuid4())}, session
            )

    asyncio.run(run())


def test_denial_evidence_and_receipt_validation():
    trace = "1-12345678-123456789012345678901234"
    assert not evidence(span(trace, "DENY"), trace, ROUTE, "request", None).allowed
    with pytest.raises(ValueError, match="Enforced denial"):
        evidence(
            span(trace, "DENY"),
            trace,
            ROUTE,
            "request",
            {"structuredContent": {"executed": False}},
        )
    with pytest.raises(ValueError):
        evidence(span("other"), trace, ROUTE, "request", None)
    value = {"executed": False, "approved": True, "ttl_minutes": 30}
    assert receipt({"content": [{"type": "text", "text": json.dumps(value)}]}) == value
    for bad in (None, {}, {"structuredContent": {"executed": True}}, {"isError": True}):
        with pytest.raises(ValueError):
            receipt(bad)


def test_cleanup_waits_for_owned_policies(monkeypatch):
    sdk = Mock()
    sdk.list_policies.side_effect = [
        {
            "policies": [
                {"policyId": "one", "policyEngineId": "engine", "status": "ACTIVE"}
            ]
        },
        {
            "policies": [
                {"policyId": "one", "policyEngineId": "engine", "status": "DELETING"}
            ]
        },
        {"policies": []},
    ]
    monkeypatch.setattr("hirz.aws.cleanup.time.sleep", lambda _: None)
    empty_policy_engine(sdk, "engine")
    sdk.delete_policy.assert_called_once_with(policyEngineId="engine", policyId="one")
    sdk.list_policies.side_effect = None
    sdk.list_policies.return_value = {
        "policies": [
            {"policyId": "foreign", "policyEngineId": "other", "status": "ACTIVE"}
        ]
    }
    with pytest.raises(ValueError, match="crossed"):
        empty_policy_engine(sdk, "engine")


def test_tracing_cleanup_refuses_preexisting_group(tmp_path):
    before = {
        "groups": [],
        "destination": {"Destination": "XRay"},
        "indexing": {
            "IndexingRules": [
                {
                    "Name": "Default",
                    "Rule": {"Probabilistic": {"DesiredSamplingPercentage": 0.0}},
                }
            ]
        },
    }
    (tmp_path / "tracing-before.json").write_text(json.dumps(before))
    (tmp_path / "clearance.json").write_text(
        json.dumps({"started_at": "2026-10-17T00:00:00+00:00"})
    )
    acceptance = Mock(folder=tmp_path)
    logs, xray = Mock(), Mock()
    acceptance.client.side_effect = lambda service: {"logs": logs, "xray": xray}[
        service
    ]
    group = {"logGroupName": "aws/spans", "creationTime": 1}
    logs.describe_log_groups.return_value = {"logGroups": [group]}
    with pytest.raises(ValueError, match="pre-existing"):
        policy_tracing(acceptance, restore=True)
    logs.delete_log_group.assert_not_called()
    xray.update_trace_segment_destination.assert_not_called()
    group["creationTime"] = 1792281600001
    policy_tracing(acceptance)
    logs.put_retention_policy.assert_called_once_with(
        logGroupName="aws/spans", retentionInDays=7
    )
    logs.describe_log_groups.side_effect = [{"logGroups": [group]}, {"logGroups": []}]
    xray.get_trace_segment_destination.return_value = before["destination"]
    xray.get_indexing_rules.return_value = before["indexing"]
    policy_tracing(acceptance, restore=True)
    logs.delete_log_group.assert_called_once_with(logGroupName="aws/spans")
