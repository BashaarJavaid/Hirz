"""Manual item 36 acceptance; never deploys or treats budget alerts as a cap."""

import argparse
import base64
import io
import json
import os
import subprocess
import sys
import time
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from hirz.audit import verify_file, write_export
from hirz.aws.evidence import unseal
from hirz.aws.schedules import name
from hirz.local import signing_key

ACCOUNT = "661550216013"
STACK = "HirzItem36"


def clearance(path: Path | None) -> None:
    if path is None:
        raise ValueError(
            "Live acceptance blocked: account-specific zero-out-of-pocket billing exposure is unresolved"
        )
    document = json.loads(path.read_text())
    if not (
        document.get("account") == ACCOUNT
        and document.get("zero_out_of_pocket_resolved") is True
        and document.get("incremental_budget_usd") == 10
        and document.get("maximum_hours") == 24
        and document.get("evidence")
        and datetime.fromisoformat(document["expires_at"]) > datetime.now(UTC)
    ):
        raise ValueError(
            "Billing clearance must resolve exposure for this account, budget and window"
        )


class Acceptance:
    def __init__(self, folder: Path, *, missing_ok: bool = False):
        self.folder = folder
        self.session = boto3.Session(profile_name="hirz", region_name="us-east-1")
        caller = self.client("sts").get_caller_identity()
        if caller["Account"] != ACCOUNT or not caller["Arn"].startswith(
            f"arn:aws:sts::{ACCOUNT}:assumed-role/HirzDeploy/"
        ):
            raise ValueError(
                "Use temporary assumed credentials for HirzDeploy in the hirz profile"
            )
        try:
            self.stack = self.client("cloudformation").describe_stacks(StackName=STACK)[
                "Stacks"
            ][0]
        except ClientError as exc:
            if (
                not missing_ok
                or exc.response["Error"]["Code"] != "ValidationError"
                or "does not exist" not in exc.response["Error"]["Message"]
            ):
                raise
            self.stack = {}
        self.outputs = {
            r["OutputKey"]: r["OutputValue"] for r in self.stack.get("Outputs", [])
        }
        self.parameters = {
            r["ParameterKey"]: r["ParameterValue"]
            for r in self.stack.get("Parameters", [])
        }
        folder.mkdir(parents=True, mode=0o700, exist_ok=True)
        if folder.is_symlink() or folder.stat().st_mode & 0o077:
            raise ValueError(
                "Acceptance artifacts require a private nonsymlink directory"
            )
        private = folder / "recipient.pem"
        if not private.exists():
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            with os.fdopen(
                os.open(private, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb"
            ) as file:
                file.write(
                    key.private_bytes(
                        serialization.Encoding.PEM,
                        serialization.PrivateFormat.PKCS8,
                        serialization.NoEncryption(),
                    )
                )
        if private.is_symlink() or private.stat().st_mode & 0o077:
            raise ValueError("Evidence recipient key must be private and nonsymlink")
        loaded_key = serialization.load_pem_private_key(
            private.read_bytes(), password=None
        )
        if not isinstance(loaded_key, rsa.RSAPrivateKey):
            raise ValueError("Invalid evidence recipient")
        self.key = loaded_key
        self.public = (
            loaded_key.public_key()
            .public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode()
        )

    def client(self, service: str) -> Any:
        return self.session.client(
            service,
            config=Config(
                connect_timeout=5, read_timeout=80, retries={"max_attempts": 2}
            ),
        )

    def within_window(self) -> None:
        start = min(
            self.stack["CreationTime"],
            datetime.fromisoformat(self.parameters["FixtureStart"]),
        )
        if datetime.now(UTC) >= start + timedelta(hours=24):
            raise ValueError(
                "Acceptance window expired; export and destroy immediately"
            )

    def task(
        self,
        operation: str,
        *args: str,
        setup: bool = False,
        workload_token: str | None = None,
    ) -> dict[str, Any]:
        ecs = self.client("ecs")
        module = "hirz.aws.bootstrap" if setup else "hirz.aws.probe"
        environment = [{"name": "HIRZ_EVIDENCE_RECIPIENT", "value": self.public}]
        if workload_token is not None:
            environment.append(
                {"name": "HIRZ_PROBE_WORKLOAD_TOKEN", "value": workload_token}
            )
        response = ecs.run_task(
            cluster=self.outputs["Cluster"],
            taskDefinition=self.outputs["SetupTask" if setup else "WorkerTask"],
            launchType="FARGATE",
            count=1,
            networkConfiguration={
                "awsvpcConfiguration": {
                    "subnets": self.outputs["PrivateSubnets"].split(","),
                    "securityGroups": [self.outputs["WorkerSecurity"]],
                    "assignPublicIp": "DISABLED",
                }
            },
            overrides={
                "containerOverrides": [
                    {
                        "name": "hirz",
                        "command": ["python", "-m", module, operation, *args],
                        "environment": environment,
                    }
                ]
            },
            tags=[
                {"key": "Project", "value": "Hirz"},
                {"key": "Environment", "value": "item36"},
            ],
        )
        if response.get("failures") or len(response.get("tasks", [])) != 1:
            raise ValueError("One-off ECS task did not start")
        arn = response["tasks"][0]["taskArn"]
        deadline = time.monotonic() + 600
        while True:
            task = ecs.describe_tasks(cluster=self.outputs["Cluster"], tasks=[arn])[
                "tasks"
            ][0]
            if task["lastStatus"] == "STOPPED":
                break
            if time.monotonic() > deadline:
                ecs.stop_task(
                    cluster=self.outputs["Cluster"],
                    task=arn,
                    reason="Acceptance probe deadline",
                )
                raise ValueError(
                    "One-off task timed out; collect diagnostics before teardown"
                )
            time.sleep(5)
        if any(c.get("exitCode") != 0 for c in task["containers"]):
            raise ValueError(
                "One-off task failed; inspect private CloudWatch diagnostics"
            )
        if setup:
            return {"operation": operation, "task": arn, "status": "passed"}
        stream = "worker/hirz/" + arn.rsplit("/", 1)[-1]
        logs = self.client("logs")
        chunks: dict[int, str] = {}
        token: dict[str, str] = {}
        for _ in range(60):
            page = logs.get_log_events(
                logGroupName=self.outputs["WorkerLog"],
                logStreamName=stream,
                startFromHead=True,
                **token,
            )
            for entry in page["events"]:
                if entry["message"].startswith("HIRZ_EVIDENCE "):
                    value = json.loads(entry["message"][14:])
                    chunks[value["index"]] = value["data"]
            try:
                return unseal(
                    json.loads("".join(chunks[i] for i in range(len(chunks)))), self.key
                )
            except (json.JSONDecodeError, KeyError):
                token = {"nextToken": page["nextForwardToken"]}
                time.sleep(1)
        raise ValueError(
            "Evidence export failed; task succeeded but encrypted output is incomplete"
        )

    def tick(self) -> None:
        result = self.client("lambda").invoke(
            FunctionName=self.outputs["TickFunction"], Payload=b"{}"
        )
        if result.get("FunctionError"):
            raise ValueError("Tick Lambda reported a processing failure")

    def diagnostics(self) -> dict[str, Any]:
        resources = [
            row
            for page in self.client("cloudformation")
            .get_paginator("list_stack_resources")
            .paginate(StackName=STACK)
            for row in page["StackResourceSummaries"]
        ]
        groups = {}
        for resource in resources:
            if resource["ResourceType"] != "AWS::Logs::LogGroup" or not resource.get(
                "PhysicalResourceId"
            ):
                continue
            group = resource["PhysicalResourceId"]
            groups[group] = [
                event
                for page in self.client("logs")
                .get_paginator("filter_log_events")
                .paginate(logGroupName=group)
                for event in page["events"]
            ]
        path = self.folder / ("diagnostics-" + str(time.time_ns()) + ".json")
        write_export(
            path,
            json.loads(
                json.dumps({"resources": resources, "logs": groups}, default=str)
            ),
        )
        return {
            "file": path.name,
            "log_groups": len(groups),
            "events": sum(len(v) for v in groups.values()),
        }

    def export(self) -> dict[str, Any]:
        result = self.task("export")
        path = self.folder / (
            "audit-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + ".json"
        )
        write_export(path, result["audit"])
        # Trust the independently fetched infrastructure key, not the export wrapper.
        pem = self.client("secretsmanager").get_secret_value(
            SecretId=self.outputs["AuditSecret"]
        )["SecretString"]
        key = signing_key({"AUDIT_SIGNING_KEY": pem}).public_key()
        verification = verify_file(path, UUID(result["audit"]["household_id"]), key=key)
        if verification["status"] != "valid":
            raise ValueError("Independent signed audit verification failed")
        write_export(path.with_suffix(".verification.json"), verification)
        return verification

    def positive_control(self) -> dict[str, Any]:
        function = "hirz-item36-positive-control"
        source = """import base64, boto3, json, os

def handler(event, context):
    client = boto3.client("bedrock-agentcore")
    token = client.get_workload_access_token(workloadName="hirz-item36-actions")["workloadAccessToken"]
    key = client.get_resource_api_key(workloadIdentityToken=token, resourceCredentialProviderName="hirz-item36-synthetic")["apiKey"]
    direct = json.loads(boto3.client("secretsmanager").get_secret_value(SecretId=os.environ["SECRET"])["SecretString"])["api_key"]
    if key != direct or key != "NONFUNCTIONAL-ITEM36-SYNTHETIC-CREDENTIAL":
        raise ValueError("Unexpected synthetic credential")
    signed = boto3.client("kms").sign(KeyId=os.environ["KEY"], Message=b"hirz-item36-noncommand", MessageType="RAW", SigningAlgorithm="ECDSA_SHA_256")
    return {"signature": base64.b64encode(signed["Signature"]).decode(), "identity_api": True, "backing_secret": True, "workload_token": token}
"""
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("probe.py", source)
        sdk = self.client("lambda")
        sdk.create_function(
            FunctionName=function,
            Role=self.outputs["SignerRole"],
            Runtime="python3.12",
            Handler="probe.handler",
            Architectures=["arm64"],
            Code={"ZipFile": archive.getvalue()},
            Timeout=30,
            Environment={
                "Variables": {
                    "KEY": self.outputs["CommandKey"],
                    "SECRET": self.outputs["IdentitySecret"],
                }
            },
            LoggingConfig={"LogGroup": self.outputs["ActionsLog"]},
            Tags={"Project": "Hirz", "Environment": "item36"},
        )
        try:
            sdk.get_waiter("function_active_v2").wait(
                FunctionName=function, WaiterConfig={"Delay": 2, "MaxAttempts": 30}
            )
            result = sdk.invoke(FunctionName=function, Payload=b"{}")
            if result.get("FunctionError"):
                raise ValueError("Signer-role positive control failed")
            document = json.loads(result["Payload"].read())
            public = serialization.load_der_public_key(
                self.client("kms").get_public_key(KeyId=self.outputs["CommandKey"])[
                    "PublicKey"
                ]
            )
            if not isinstance(public, ec.EllipticCurvePublicKey):
                raise ValueError("Command key is not ECC")
            public.verify(
                base64.b64decode(document.pop("signature")),
                b"hirz-item36-noncommand",
                ec.ECDSA(hashes.SHA256()),
            )
            return dict(document) | {"test_signature_verified": True}
        finally:
            sdk.delete_function(FunctionName=function)

    def quiet(self) -> dict[str, Any]:
        self.within_window()
        due = (datetime.now(UTC) + timedelta(minutes=33)).replace(microsecond=0)
        if due + timedelta(minutes=5) >= datetime.fromisoformat(
            self.parameters["FixtureStart"]
        ) + timedelta(hours=24):
            raise ValueError("Not enough acceptance lifetime remains")
        queued = self.task("schedule", "--due", due.isoformat())
        write_export(self.folder / "quiet-action.json", queued)
        # Remove the derived schedule and restart before the quiet interval starts.
        self.tick()
        key = name(queued["household"], queued["action_id"])
        self.client("scheduler").delete_schedule(
            GroupName=self.outputs["ScheduleGroup"], Name=key
        )
        ecs = self.client("ecs")
        ecs.update_service(
            cluster=self.outputs["Cluster"],
            service=self.outputs["WorkerService"],
            forceNewDeployment=True,
        )
        ecs.get_waiter("services_stable").wait(
            cluster=self.outputs["Cluster"],
            services=[self.outputs["WorkerService"]],
            WaiterConfig={"Delay": 10, "MaxAttempts": 60},
        )
        start = datetime.now(UTC)
        if (due - start).total_seconds() < 1800:
            raise ValueError("Restart consumed the quiet window; this run cannot pass")
        print(
            "Quiet interval started; no companion requests or probes until due + 90 seconds.",
            flush=True,
        )
        while datetime.now(UTC) < due + timedelta(seconds=90):
            time.sleep(
                min(
                    30,
                    max(
                        0.01,
                        (
                            due + timedelta(seconds=90) - datetime.now(UTC)
                        ).total_seconds(),
                    ),
                )
            )
        traffic = [
            entry
            for page in self.client("logs")
            .get_paginator("filter_log_events")
            .paginate(
                logGroupName=self.outputs["WorkerLog"],
                filterPattern='"item36_request"',
                startTime=int(start.timestamp() * 1000),
                endTime=int((due + timedelta(seconds=90)).timestamp() * 1000),
            )
            for entry in page["events"]
        ]
        if any("kind=other" in event["message"] for event in traffic):
            raise ValueError(
                "Non-tick application traffic entered during the quiet interval"
            )
        if sum("kind=tick status=204" in event["message"] for event in traffic) < 30:
            raise ValueError(
                "Insufficient retained tick request evidence for the quiet interval"
            )
        result = self.task("inspect", "--action-id", queued["action_id"])
        if result["action"]["execution_status"] != "verified":
            raise ValueError("Quiet-window action did not verify")
        verified = [
            event for event in result["events"] if event["event_type"] == "VERIFIED"
        ]
        if not verified or not due <= datetime.fromisoformat(
            verified[-1]["created_at"]
        ) <= due + timedelta(seconds=90):
            raise ValueError("Quiet execution missed its 90-second acceptance window")
        self.tick()
        self.tick()
        duplicate = self.task("inspect", "--action-id", queued["action_id"])
        if (
            duplicate["action"]["execution_attempt_seq"]
            != result["action"]["execution_attempt_seq"]
        ):
            raise ValueError("Duplicate delivery changed the execution attempt")
        return {
            "status": "passed",
            "quiet_started_at": start.isoformat(),
            "retained_request_count": len(traffic),
            "due": due.isoformat(),
            "result": result,
            "duplicate_attempt_unchanged": True,
            "engine": "dogwood-local",
            "source": "twin",
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=[
            "offline",
            "bootstrap",
            "invite",
            "iam",
            "quiet",
            "cancel",
            "export",
            "inventory",
            "cleanup",
        ],
    )
    parser.add_argument("--artifacts-dir", type=Path)
    parser.add_argument("--billing-clearance", type=Path)
    args = parser.parse_args()
    if args.operation == "offline":
        subprocess.run(["pnpm", "--filter", "infra", "test"], check=True)
        subprocess.run(
            [sys.executable, "-m", "pytest", "tests/unit/aws", "--no-cov"], check=True
        )
        print(
            "Offline contracts passed; live acceptance and teardown remain unverified."
        )
        return
    if not args.artifacts_dir:
        parser.error("Live operations require --artifacts-dir")
    if args.operation not in {"export", "inventory", "cleanup"}:
        clearance(args.billing_clearance)
    acceptance = Acceptance(args.artifacts_dir, missing_ok=args.operation == "cleanup")
    if args.operation not in {"export", "inventory", "cleanup"}:
        acceptance.within_window()
    if args.operation == "cleanup":
        from hirz.aws.cleanup import destroy

        result = destroy(acceptance)
    elif args.operation == "bootstrap":
        if acceptance.parameters["WorkerDesiredCount"] != "0":
            raise ValueError("Initialize only with WorkerDesiredCount=0")
        result = {
            op: acceptance.task(op, setup=True)
            for op in ("initialize", "migrate", "seed")
        }
    elif args.operation == "invite":
        result = acceptance.task("invite")
    elif args.operation == "iam":
        positive = acceptance.positive_control()
        workload_token = positive.pop("workload_token")
        result = {
            "positive": positive,
            "worker": acceptance.task("iam", workload_token=workload_token),
        }
    elif args.operation == "cancel":
        result = acceptance.task("cancel")
        acceptance.tick()
        remaining = acceptance.client("scheduler").list_schedules(
            GroupName=acceptance.outputs["ScheduleGroup"],
            NamePrefix=name(result["household"], result["action"]),
        )
        if remaining.get("Schedules"):
            raise ValueError("Cancelled action retained a schedule")
    elif args.operation == "quiet":
        result = acceptance.quiet()
        acceptance.export()
    elif args.operation == "export":
        result = acceptance.export()
    else:
        result = {
            "stack": acceptance.stack,
            "diagnostics": acceptance.diagnostics(),
        }
    write_export(
        args.artifacts_dir / (args.operation + ".json"),
        json.loads(json.dumps(result, default=str)),
    )
    print(
        json.dumps(
            {"operation": args.operation, "status": "passed", "item36": "not complete"}
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "type": type(exc).__name__,
                    "detail": str(exc)
                    if isinstance(exc, ValueError)
                    else "Check private diagnostics; upstream details withheld.",
                }
            )
        )
        raise SystemExit(1) from None
