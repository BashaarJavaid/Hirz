import asyncio
import threading
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from hirz.aws.cleanup import destroy, empty_bucket
from hirz.aws.client import call
from hirz.aws.evidence import seal, unseal
from scripts.smoke_aws import Acceptance, clearance


def test_cleanup_can_export_a_household_with_no_runtime_mutations(tmp_path):
    from hirz.audit import export_document

    key = ec.generate_private_key(ec.SECP256R1())
    sdk = Mock()
    sdk.get_secret_value.return_value = {
        "SecretString": key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
    }
    acceptance = Acceptance.__new__(Acceptance)
    acceptance.folder = tmp_path
    acceptance.outputs = {"AuditSecret": "test"}
    acceptance.task = Mock(
        return_value={"audit": export_document(uuid4(), key.public_key(), [])}
    )
    acceptance.client = Mock(return_value=sdk)
    result = acceptance.export()
    assert result["status"] == "empty" and result["checked_count"] == 0
    assert len(list(tmp_path.glob("*.verification.json"))) == 1


def test_evidence_is_authenticated_and_recipient_bound():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        .decode()
    )
    document = seal({"token": "private", "audit": [1, 2]}, public)
    assert "private" not in str(document)
    assert unseal(document, key) == {"token": "private", "audit": [1, 2]}
    document["nonce"] = "AAAAAAAAAAAAAAAA"
    with pytest.raises(InvalidTag):
        unseal(document, key)


def test_sdk_cancellation_waits_for_thread_exit():
    async def run():
        started, finish = threading.Event(), threading.Event()

        def sdk_method():
            started.set()
            finish.wait(timeout=1)
            return "done"

        task = asyncio.create_task(call(Mock(method=sdk_method), "method"))
        while not started.is_set():
            await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())


@pytest.mark.parametrize("governance_bypass", [False, True])
def test_cleanup_checks_per_object_errors(governance_bypass):
    sdk = Mock()
    sdk.get_paginator.return_value.paginate.return_value = [
        {"Versions": [{"Key": "head", "VersionId": "v"}]}
    ]
    sdk.delete_objects.return_value = {"Errors": [{"Code": "AccessDenied"}]}
    with pytest.raises(ValueError):
        empty_bucket(sdk, "owned", governance_bypass=governance_bypass)
    assert (
        sdk.delete_objects.call_args.kwargs.get("BypassGovernanceRetention", False)
        is governance_bypass
    )
    if not governance_bypass:
        assert "BypassGovernanceRetention" not in sdk.delete_objects.call_args.kwargs


def test_cleanup_retry_stops_tasks_when_service_and_repository_are_gone(tmp_path):
    from botocore.exceptions import ClientError

    def missing(code):
        return ClientError(
            {"Error": {"Code": code, "Message": "does not exist"}}, "test"
        )

    clients = {
        name: Mock()
        for name in (
            "cloudformation",
            "ecs",
            "lambda",
            "scheduler",
            "s3",
            "ecr",
            "bedrock-agentcore-control",
        )
    }
    cfn = clients["cloudformation"]
    cfn.get_paginator.return_value.paginate.side_effect = lambda **kw: [
        {
            "StackResourceSummaries": [
                {
                    "ResourceType": "AWS::BedrockAgentCore::PolicyEngine",
                    "PhysicalResourceId": "arn:aws:bedrock-agentcore:us-east-1:123456789012:policy-engine/owned-engine",
                }
            ]
            if kw["StackName"] == "HirzItem36"
            else [
                {
                    "ResourceType": "AWS::ECR::Repository",
                    "PhysicalResourceId": "cdk-hirzitem36-repository",
                }
            ]
        }
    ]
    cfn.describe_stacks.side_effect = missing("ValidationError")
    ecs = clients["ecs"]
    ecs.update_service.side_effect = missing("ServiceNotActiveException")
    ecs.get_paginator.return_value.paginate.return_value = [{"taskArns": ["one-off"]}]
    ecr = clients["ecr"]
    ecr.get_paginator.return_value.paginate.side_effect = missing(
        "RepositoryNotFoundException"
    )
    ecr.delete_repository.side_effect = missing("RepositoryNotFoundException")
    policies = clients["bedrock-agentcore-control"]
    policies.list_policies.side_effect = missing("ResourceNotFoundException")
    acceptance = Mock(
        folder=tmp_path, outputs={"Cluster": "owned", "WorkerService": "gone"}
    )
    acceptance.client.side_effect = clients.__getitem__
    acceptance.diagnostics.return_value = {"file": "private-diagnostics.json"}
    acceptance.export.side_effect = ValueError("Audit export unavailable")
    result = destroy(acceptance)
    assert result["status"] == "destroyed"
    assert result["evidence_export"] == {"status": "failed", "type": "ValueError"}
    ecs.stop_task.assert_called_once_with(
        cluster="owned", task="one-off", reason="End item 36 acceptance window"
    )
    assert cfn.delete_stack.call_count == 2
    policies.list_policies.assert_called_once_with(
        policyEngineId="owned-engine", maxResults=100
    )


def test_diagnostics_retains_paginated_logs_privately(tmp_path):
    import json

    acceptance = Acceptance.__new__(Acceptance)
    acceptance.folder = tmp_path
    cfn, logs = Mock(), Mock()
    cfn.get_paginator.return_value.paginate.return_value = [
        {
            "StackResourceSummaries": [
                {"ResourceType": "AWS::Logs::LogGroup", "PhysicalResourceId": "owned"}
            ]
        }
    ]
    logs.get_paginator.return_value.paginate.return_value = [
        {"events": [{"message": "first"}]},
        {"events": [{"message": "second"}]},
    ]
    acceptance.client = lambda service: cfn if service == "cloudformation" else logs
    result = acceptance.diagnostics()
    path = tmp_path / result["file"]
    assert result["events"] == 2 and result["log_groups"] == 1
    assert path.stat().st_mode & 0o777 == 0o600
    assert len(json.loads(path.read_text())["logs"]["owned"]) == 2


def test_live_acceptance_requires_billing_clearance():
    with pytest.raises(ValueError, match="zero-out-of-pocket"):
        clearance(None)


def test_first_plan_cancellation_settles_solver_before_return(monkeypatch):
    from contextlib import asynccontextmanager
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from hirz.mcp.worker import prepare_plans

    async def run():
        started, finish = threading.Event(), threading.Event()
        at = datetime.now(UTC)
        home = uuid4()

        @asynccontextmanager
        async def transaction(*args):
            yield

        c = Mock()
        c.begin = transaction
        c.execute = AsyncMock(
            return_value=Mock(
                mappings=lambda: Mock(
                    all=lambda: [
                        {
                            "principal": {
                                "provider": "demo",
                                "sub": "malik",
                                "surface": "app",
                            },
                            "horizon_end": at + timedelta(hours=1),
                            "objective": "cost",
                        }
                    ]
                )
            )
        )

        p = Mock(connection=c, household_id=home, clock=lambda: at)
        p.scope = lambda _: True
        p.repo.write = transaction
        p.snapshot = AsyncMock(return_value=Mock(data={}))
        p.requester = AsyncMock(return_value=Mock())
        loaded = Mock()
        loaded.world.household.id = home
        loaded.world.config.end = at + timedelta(hours=2)
        loaded.spec.execution.ev_needed_by = None
        loaded.spec.execution.plan_at = "18:00"
        loaded.spec.execution.member = "malik"
        loaded.spec.execution.ev_target = 0.5
        monkeypatch.setattr("hirz.mcp.worker.workload_input", lambda *a, **k: Mock())

        def coordinate(*args):
            started.set()
            finish.wait(timeout=2)
            raise ValueError("Solver stopped while request was cancelled")

        monkeypatch.setattr("hirz.mcp.worker.coordinate", coordinate)
        task = asyncio.create_task(prepare_plans(p, loaded))
        while not started.is_set():
            if task.done():
                await task
                pytest.fail("Preparation did not reach the solver")
            await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
