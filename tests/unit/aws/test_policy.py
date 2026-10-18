import asyncio
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from jsonschema import validate

from hirz.aws.lambdas.actions import handler
from hirz.aws.policy import Findings, Publisher, inventory, quota, tools, wire_json
from hirz.aws.routing import Route, Routing
from hirz.constitution.compiler import boundary_input, compile_policy
from hirz.constitution.preview import situation
from hirz.constitution.schema import load

HOME = load(Path("constitutions/quinn-home.yaml"))


def test_one_compiler_two_event_dialects_and_generated_contract():
    local = compile_policy(HOME)
    aws = compile_policy(HOME, engine="agentcore-policy")
    assert (
        aws.policy.replace("eventResource:", "callerResource:").replace(
            "eventPrincipal:", "callerPrincipal:"
        )
        == local.policy
    )
    assert "\n\n".join(s.text for s in aws.statements) == aws.policy
    assert len(inventory([aws])) == len(aws.statements)
    with pytest.raises(ValueError, match="Local"):
        inventory([local])
    with pytest.raises(ValueError, match="Duplicate"):
        inventory([aws, aws])
    parents = compile_policy(load(Path("constitutions/quinn-parents.yaml")))
    generated = tools([local, parents])
    stored = json.loads(Path("hirz/aws/lambdas/contract.json").read_text())
    assert stored == {
        "names": [t["name"] for t in generated],
        "inputSchema": generated[0]["inputSchema"],
        "outputSchema": generated[0]["outputSchema"],
    }


def test_schema_optional_nulls_precision_and_inert_target():
    compiled = compile_policy(HOME)
    action, facts = situation(HOME, "security.door_unlock", "owner")
    inputs = boundary_input(
        compiled, action, facts, ttl_minutes=30, session_id=str(uuid4())
    )
    tool = next(t for t in tools([compiled]) if t["name"] == "security_door_unlock")
    validate(json.loads(wire_json(inputs)), tool["inputSchema"])
    precise = Decimal("922337203685477.5807")
    assert json.loads(wire_json({"n": precise}), parse_float=Decimal)["n"] == precise
    with pytest.raises(ValueError):
        wire_json(Decimal("1.00001"))
    context = SimpleNamespace(
        client_context=SimpleNamespace(
            custom={
                "bedrockAgentCoreToolName": "HirzActions___security_door_unlock",
                "bedrockAgentCoreAwsRequestId": "test",
            }
        )
    )
    result = handler(json.loads(wire_json(inputs)), context)
    assert result == {"approved": False, "ttl_minutes": 30, "executed": False}
    with pytest.raises(ValueError):
        handler(dict(inputs, quorum_satisfied="true"), context)


def test_shared_temporal_headroom_and_explicit_routes():
    desired = {f"p{i}": "when temporal" for i in range(20)}
    quota(desired)
    with pytest.raises(ValueError, match="headroom"):
        quota(desired, {"old": "when temporal"})
    a, b = uuid4(), uuid4()
    route = Route("engine", "arn", "https://gateway.example/mcp")
    routing = Routing.parse(json.dumps({"managed": [str(a)], "local": [str(b)]}), route)
    assert routing.route(a) == route and routing.route(b) is None
    with pytest.raises(ValueError, match="Unknown"):
        routing.route(uuid4())
    with pytest.raises(ValueError, match="Conflicting"):
        Routing.parse(json.dumps({"managed": [str(a)], "local": [str(a)]}), route)
    with pytest.raises(ValueError, match="Conflicting"):
        Routing(frozenset({a}), frozenset({a}), route)


def test_async_validation_exact_inventory_and_recovery():
    async def run():
        sdk = Mock()
        sdk.list_policies.return_value = {"policies": []}
        publisher = Publisher(sdk, "engine")
        assert not await publisher.step({"p": "permit;"})
        assert (
            sdk.create_policy.call_args.kwargs["validationMode"]
            == "FAIL_ON_ANY_FINDINGS"
        )
        row = {
            "name": "p",
            "policyId": "id",
            "policyEngineId": "engine",
            "status": "CREATING",
            "definition": {"policy": {"statement": "permit;"}},
        }
        sdk.list_policies.return_value = {"policies": [row]}
        assert not await publisher.step({"p": "permit;"})
        row.update(status="CREATE_FAILED", statusReasons=["always allow"])
        with pytest.raises(Findings):
            await publisher.step({"p": "permit;"})
        assert not await publisher.step({}, recovering=True)
        sdk.delete_policy.assert_called_once()
        row.update(status="ACTIVE", statusReasons=[])
        assert await publisher.step({"p": "permit;"})
        assert not await publisher.step({"p": "changed;"})
        assert (
            sdk.update_policy.call_args.kwargs["validationMode"]
            == "FAIL_ON_ANY_FINDINGS"
        )
        from botocore.exceptions import ClientError

        response = {"Error": {"Code": "ValidationException", "Message": "finding"}}
        sdk.update_policy.side_effect = ClientError(response, "UpdatePolicy")
        with pytest.raises(Findings) as failed:
            await publisher.step({"p": "changed;"})
        assert failed.value.policy == {
            "name": "p",
            "definition": {"policy": {"statement": "changed;"}},
            "aws_response": response,
        }

    asyncio.run(run())
