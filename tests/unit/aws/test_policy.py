import asyncio
import json
import re
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
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


def test_generated_policy_names_and_requests_fit_the_installed_aws_contract():
    from botocore.session import Session
    from botocore.validate import validate_parameters

    shape = (
        Session()
        .get_service_model("bedrock-agentcore-control")
        .operation_model("CreatePolicy")
        .input_shape
    )
    limits = shape.members["name"].metadata
    compiled = [
        compile_policy(
            load(Path(f"constitutions/quinn-{seed}.yaml")), engine="agentcore-policy"
        )
        for seed in ("home", "parents")
    ]
    statements = inventory(compiled)
    assert len(statements) == sum(len(c.statements) for c in compiled)
    for name, statement in statements.items():
        assert limits["min"] <= len(name) <= limits["max"]
        assert re.fullmatch(limits["pattern"], name)
        assert len(name.split("_", 2)[1]) == 16
        validate_parameters(
            {
                "policyEngineId": "engine-0123456789",
                "name": name,
                "definition": {"policy": {"statement": statement}},
                "validationMode": "FAIL_ON_ANY_FINDINGS",
                "enforcementMode": "ACTIVE",
            },
            shape,
        )


@pytest.mark.parametrize(
    "defect",
    [
        None,
        "case",
        "decision",
        "mode",
        "inventory",
        "request",
        "policy_id",
        "installed",
        "engine",
    ],
)
def test_promotion_requires_complete_evidence_for_exact_deployment(monkeypatch, defect):
    from hirz.aws.policy import fingerprint
    from hirz.pipeline.hashing import digest
    from scripts import smoke_policy

    route = Route(
        "engine",
        "arn:aws:bedrock-agentcore:us-east-1:123456789012:gateway/test",
        "https://example.test/mcp",
    )
    desired = {"p": "permit;"}
    request = {"approvals": []}
    record = {
        "case": "case",
        "local": True,
        "aws": {"allowed": True, "mode": "LOG_ONLY", "policy_ids": ["p-id"]},
        "inventory_hash": fingerprint(desired),
        "context_hash": "sha256:" + digest(request),
        "request": request,
    }
    installed = {
        "p": {
            "definition": {"policy": {"statement": "permit;"}},
            "status": "ACTIVE",
            "policyId": "p-id",
        }
    }
    current = {
        "gatewayArn": route.gateway_arn,
        "name": "gateway",
        "roleArn": "role",
        "protocolType": "MCP",
        "authorizerType": "CUSTOM_JWT",
        "authorizerConfiguration": {},
        "policyEngineConfiguration": {
            "arn": "arn:aws:bedrock-agentcore:us-east-1:123456789012:policy-engine/engine",
            "mode": "LOG_ONLY",
        },
        "status": "READY",
    }
    if defect == "case":
        record["case"] = "missing"
    if defect == "decision":
        record["aws"]["allowed"] = False
    if defect == "mode":
        record["aws"]["mode"] = "ENFORCE"
    if defect == "inventory":
        record["inventory_hash"] = "different"
    if defect == "request":
        record["request"] = {"approvals": [], "changed": True}
    if defect == "policy_id":
        record["aws"]["policy_ids"] = ["other"]
    if defect == "installed":
        installed["p"]["definition"]["policy"]["statement"] = "different"
    if defect == "engine":
        current["policyEngineConfiguration"]["arn"] += "-other"
    publisher = Mock(gateway_id="test", installed=AsyncMock(return_value=installed))
    sdk = Mock()
    sdk.get_gateway.side_effect = lambda **_: current
    sdk.update_gateway.side_effect = lambda **kw: current.update(
        policyEngineConfiguration=kw["policyEngineConfiguration"]
    )
    monkeypatch.setattr(smoke_policy, "corpus", lambda _: [("case", None, None, None)])
    if defect:
        with pytest.raises(ValueError):
            asyncio.run(
                smoke_policy.promote(publisher, sdk, route, desired, [record], [None])
            )
        sdk.update_gateway.assert_not_called()
    else:
        asyncio.run(
            smoke_policy.promote(publisher, sdk, route, desired, [record], [None])
        )
        assert (
            sdk.update_gateway.call_args.kwargs["policyEngineConfiguration"]["mode"]
            == "ENFORCE"
        )


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


@pytest.mark.parametrize("denied_approval_reached_target", [False, True])
def test_enforcement_target_evidence_includes_approval_calls(
    tmp_path, denied_approval_reached_target
):
    from scripts.smoke_policy import target_evidence

    records = [
        {
            "aws": {"request_id": "action", "allowed": True},
            "request": {
                "approvals": [
                    {"aws": {"request_id": "approval", "allowed": True}},
                    {"aws": {"request_id": "denied-approval", "allowed": False}},
                ]
            },
        }
    ]
    logs = Mock()
    seen = ["action", "approval"]
    if denied_approval_reached_target:
        seen.append("denied-approval")
    logs.filter_log_events.return_value = {
        "events": [
            {"message": json.dumps({"request_id": request, "executed": False})}
            for request in seen
        ]
    }
    acceptance = SimpleNamespace(
        folder=tmp_path, outputs={"ActionsLog": "log"}, client=lambda _: logs
    )
    if denied_approval_reached_target:
        with pytest.raises(ValueError, match="denied ENFORCE call reached"):
            asyncio.run(target_evidence(acceptance, records))
        assert not (tmp_path / "target-enforcement.json").exists()
    else:
        asyncio.run(target_evidence(acceptance, records))
        result = json.loads((tmp_path / "target-enforcement.json").read_text())
        assert result["allowed_requests_seen"] == ["action", "approval"]
        assert result["denied_requests_absent"] == ["denied-approval"]


def test_publication_audit_does_not_disclose_other_household_rules(monkeypatch):
    from hirz.aws.policy import fingerprint
    from hirz.aws.publication import transition
    from tests.unit.test_pipeline import AT, HOME, PRINCIPAL

    decision = SimpleNamespace(audit_id=7)
    monkeypatch.setattr(
        "hirz.aws.publication.constitution", AsyncMock(return_value=decision)
    )
    p = SimpleNamespace(
        connection=AsyncMock(),
        audit=SimpleNamespace(append=AsyncMock()),
        household_id=HOME,
        clock=lambda: AT,
        scope=lambda _: True,
    )
    job = {
        "id": "draft",
        "candidate_hash": "candidate",
        "decision_seq": 3,
        "principal": PRINCIPAL.model_dump(mode="json"),
    }
    desired = {
        "own_policy": "own household rule",
        "other_policy": "private foreign rule",
    }
    asyncio.run(transition(p, job, "publishing", desired=desired))
    persisted = p.connection.execute.call_args.args[0].compile().params
    assert persisted["desired"] == desired
    payload = p.audit.append.call_args.args[4]
    assert payload["desired_inventory_hash"] == fingerprint(desired)
    assert "desired" not in payload
    assert "private foreign rule" not in json.dumps(payload)
    assert payload["candidate_hash"] == job["candidate_hash"]


def hard_deny_row():
    compiled = compile_policy(HOME, "test-gateway", engine="agentcore-policy")
    statement = next(
        s
        for s in compiled.statements
        if "HirzActions___finance_transfer_money" in s.text and "!false" in s.text
    )
    return {
        "name": statement.name,
        "policyId": "failed-id",
        "policyEngineId": "engine",
        "status": "CREATE_FAILED",
        "definition": {"policy": {"statement": statement.text}},
        "statusReasons": [
            "Overly Restrictive: Policy Engine will deny every request for the specified "
            f"principal (AgentCore::{principal}), action (HirzActions___finance_transfer_money) "
            "and resource (test-gateway) combination if the policy is added or updated"
            for principal in ("IamEntity", "OAuthUser")
        ],
    }


@pytest.mark.parametrize(
    "defect", [None, "permit", "conditional", "name", "reason", "extra", "status"]
)
def test_hard_deny_exception_matches_only_exact_compiler_shape_and_findings(defect):
    from hirz.aws.policy import hard_deny_finding

    row = hard_deny_row()
    if defect in {"permit", "conditional"}:
        row["definition"]["policy"]["statement"] = row["definition"]["policy"][
            "statement"
        ].replace(
            "forbid" if defect == "permit" else "!false",
            "permit"
            if defect == "permit"
            else '!context.input.requester_role.contains("owner")',
        )
    elif defect == "name":
        row["name"] = "arbitrary"
    elif defect == "reason":
        row["statusReasons"][0] = "Overly Permissive"
    elif defect == "extra":
        row["statusReasons"].append("Unknown finding")
    elif defect == "status":
        row["status"] = "ACTIVE"
    desired = {row["name"]: row["definition"]["policy"]["statement"]}
    assert hard_deny_finding(row, desired) is (defect is None)


def test_hard_deny_requires_strict_rejection_then_bound_exception_and_stops_on_retry_failure():
    from hirz.aws.policy import HardDenyFinding

    async def run():
        row = hard_deny_row()
        desired = {row["name"]: row["definition"]["policy"]["statement"]}
        sdk = Mock()
        publisher = Publisher(sdk, "engine")
        sdk.list_policies.return_value = {"policies": []}
        assert not await publisher.step(desired)
        assert (
            sdk.create_policy.call_args.kwargs["validationMode"]
            == "FAIL_ON_ANY_FINDINGS"
        )
        sdk.list_policies.return_value = {"policies": [row]}
        with pytest.raises(HardDenyFinding):
            await publisher.step(desired)
        sdk.delete_policy.assert_not_called()
        with pytest.raises(HardDenyFinding):
            await publisher.step(
                desired, exceptions=[dict(row, policyEngineId="other")]
            )
        assert not await publisher.step(desired, exceptions=[row])
        sdk.delete_policy.assert_called_once()
        sdk.list_policies.return_value = {"policies": []}
        assert not await publisher.step(desired, exceptions=[row])
        assert (
            sdk.create_policy.call_args.kwargs["validationMode"]
            == "IGNORE_ALL_FINDINGS"
        )
        sdk.list_policies.return_value = {"policies": [dict(row, policyId="retry-id")]}
        with pytest.raises(Findings) as failure:
            await publisher.step(desired, exceptions=[row])
        assert type(failure.value) is Findings
        assert sdk.delete_policy.call_count == 1
        sdk.list_policies.return_value = {
            "policies": [dict(row, status="ACTIVE", statusReasons=[])]
        }
        assert await publisher.step(desired, exceptions=[row])

    asyncio.run(run())


def test_permits_precede_forbids_independent_of_storage_order():
    async def run():
        sdk = Mock()
        publisher = Publisher(sdk, "engine")
        desired = {"a_forbid": "forbid (new);", "z_permit": "permit (new);"}
        row = {
            "name": "a_forbid",
            "policyId": "old",
            "policyEngineId": "engine",
            "status": "ACTIVE",
            "definition": {"policy": {"statement": "forbid (old);"}},
        }
        sdk.list_policies.return_value = {"policies": [row]}
        assert not await publisher.step(desired)
        sdk.delete_policy.assert_called_once()
        sdk.create_policy.assert_not_called()
        sdk.list_policies.return_value = {"policies": []}
        assert not await publisher.step(desired)
        assert sdk.create_policy.call_args.kwargs["name"] == "z_permit"
        assert (
            sdk.create_policy.call_args.kwargs["validationMode"]
            == "FAIL_ON_ANY_FINDINGS"
        )

    asyncio.run(run())


@pytest.mark.parametrize(
    ("reason", "name", "status", "expected"),
    [
        (
            "Overly Permissive: Policy Engine will allow every request",
            "isolated_faulty_compiler",
            "CREATE_FAILED",
            True,
        ),
        ("always-allow", "isolated_faulty_compiler", "UPDATE_FAILED", True),
        (
            "Overly Restrictive: Policy Engine will deny every request",
            "isolated_faulty_compiler",
            "CREATE_FAILED",
            False,
        ),
        (
            "Overly Permissive: Policy Engine will allow every request",
            "different_policy",
            "CREATE_FAILED",
            False,
        ),
        (
            "Overly Permissive: Policy Engine will allow every request",
            "isolated_faulty_compiler",
            "ACTIVE",
            False,
        ),
        ("schema error", "isolated_faulty_compiler", "CREATE_FAILED", False),
    ],
)
def test_faulty_compiler_requires_its_own_actual_always_allow_finding(
    reason, name, status, expected
):
    from scripts.smoke_policy import always_allow

    assert (
        always_allow([{"name": name, "status": status, "statusReasons": [reason]}])
        is expected
    )
    assert not always_allow([{"error": reason}])


@pytest.mark.parametrize(
    ("status", "polls", "error"),
    [
        ("committed", 1501, None),
        ("failed", 1, None),
        ("blocked", 1, None),
        ("publishing", 1, "two-hour"),
        ("publishing", 0, "work cutoff"),
    ],
)
def test_acceptance_publication_obeys_elapsed_and_global_limits(
    monkeypatch, status, polls, error
):
    from scripts import smoke_policy

    connection = Mock()
    connection.begin.return_value = AsyncMock()
    result = Mock()
    result.mappings.return_value.one.side_effect = [
        {"status": "publishing"} for _ in range(max(0, polls - 1))
    ] + [{"status": status}]
    connection.execute = AsyncMock(return_value=result)
    advance, sleep, acceptance = AsyncMock(), AsyncMock(), Mock()
    monkeypatch.setattr(smoke_policy, "advance", advance)
    monkeypatch.setattr(smoke_policy.asyncio, "sleep", sleep)
    monkeypatch.setattr(
        smoke_policy,
        "time",
        SimpleNamespace(monotonic=Mock(side_effect=[0] * (polls + 1) + [7200])),
    )
    if polls == 0:
        smoke_policy.time.monotonic.side_effect = [0, 0]
        acceptance.within_window.side_effect = ValueError("work cutoff")
    run = smoke_policy.publication(
        SimpleNamespace(connection=connection), Mock(), str(uuid4()), acceptance
    )
    if error:
        with pytest.raises(ValueError, match=error):
            asyncio.run(run)
    else:
        assert asyncio.run(run) == {"status": status}
    assert advance.await_count == polls
    assert acceptance.within_window.call_count == max(1, polls)
