"""Delete only recorded item 36 resources; Object Lock bypass is cleanup-only."""

import json
import time
from typing import Any

from botocore.exceptions import ClientError  # type: ignore[import-untyped]


def empty_policy_engine(client: Any, engine: str) -> None:
    """Remove runtime-created policies before CloudFormation deletes their engine."""
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        policies = []
        token: dict[str, str] = {}
        for _ in range(11):
            page = client.list_policies(policyEngineId=engine, maxResults=100, **token)
            policies.extend(page.get("policies", []))
            if not page.get("nextToken"):
                break
            token = {"nextToken": page["nextToken"]}
        else:
            raise ValueError("Policy cleanup inventory exceeded the engine quota")
        if not policies:
            return
        for policy in policies:
            if policy["policyEngineId"] != engine:
                raise ValueError("Policy cleanup crossed the recorded engine")
            if policy["status"] not in {"CREATING", "UPDATING", "DELETING"}:
                client.delete_policy(policyEngineId=engine, policyId=policy["policyId"])
        time.sleep(2)
    raise ValueError("Policy cleanup exceeded its deadline")


def empty_bucket(s3: Any, bucket: str, *, governance_bypass: bool = False) -> None:
    bypass = {"BypassGovernanceRetention": True} if governance_bypass else {}
    for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket):
        versions = [
            {"Key": obj["Key"], "VersionId": obj["VersionId"]}
            for obj in page.get("Versions", []) + page.get("DeleteMarkers", [])
        ]
        for offset in range(0, len(versions), 1000):
            result = s3.delete_objects(
                Bucket=bucket,
                Delete={"Objects": versions[offset : offset + 1000], "Quiet": True},
                **bypass,
            )
            if result.get("Errors"):
                raise ValueError("Owned S3 versions could not be removed")
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
        if page.get("Contents"):
            result = s3.delete_objects(
                Bucket=bucket,
                Delete={
                    "Objects": [{"Key": obj["Key"]} for obj in page["Contents"]],
                    "Quiet": True,
                },
                **bypass,
            )
            if result.get("Errors"):
                raise ValueError("Owned S3 objects could not be removed")
    for page in s3.get_paginator("list_multipart_uploads").paginate(Bucket=bucket):
        for upload in page.get("Uploads", []):
            s3.abort_multipart_upload(
                Bucket=bucket, Key=upload["Key"], UploadId=upload["UploadId"]
            )


def destroy(acceptance: Any) -> dict[str, Any]:
    cfn = acceptance.client("cloudformation")
    output = acceptance.outputs
    records: dict[str, Any] = {"evidence_export": "pending", "status": "incomplete"}
    try:
        records["diagnostics"] = acceptance.diagnostics()
    except Exception as exc:
        records["diagnostics"] = {"status": "failed", "type": type(exc).__name__}
        print(
            "Diagnostic export failed; teardown continues. Retain prior local exports.",
            flush=True,
        )
    try:
        records["evidence_export"] = acceptance.export()
    except Exception as exc:
        records["evidence_export"] = {"status": "failed", "type": type(exc).__name__}
        print(
            "Evidence export failed; teardown continues. Acceptance cannot pass.",
            flush=True,
        )

    def resources(stack: str) -> list[dict[str, Any]]:
        try:
            return [
                row
                for page in cfn.get_paginator("list_stack_resources").paginate(
                    StackName=stack
                )
                for row in page["StackResourceSummaries"]
            ]
        except ClientError as exc:
            if (
                exc.response["Error"]["Code"] == "ValidationError"
                and "does not exist" in exc.response["Error"]["Message"]
            ):
                return []
            raise

    app, toolkit = resources("HirzItem36"), resources("HirzItem36Toolkit")
    for path in sorted(acceptance.folder.glob("before-destroy*.json")):
        prior = json.loads(path.read_text())
        app = app or prior["application_resources"]
        toolkit = toolkit or prior["toolkit_resources"]

    def physical(rows: list[dict[str, Any]], kind: str) -> str | None:
        return next(
            (
                row.get("PhysicalResourceId")
                for row in rows
                if row["ResourceType"] == kind and row.get("PhysicalResourceId")
            ),
            None,
        )

    for key, kind in {
        "Cluster": "AWS::ECS::Cluster",
        "WorkerService": "AWS::ECS::Service",
        "ScheduleGroup": "AWS::Scheduler::ScheduleGroup",
        "AnchorBucket": "AWS::S3::Bucket",
        "CommandKey": "AWS::KMS::Key",
        "PolicyEngine": "AWS::BedrockAgentCore::PolicyEngine",
    }.items():
        if value := physical(app, kind):
            output.setdefault(key, value)

    def absent(exc: ClientError) -> bool:
        return exc.response["Error"]["Code"] in {
            "ResourceNotFoundException",
            "NoSuchBucket",
            "ClusterNotFoundException",
            "ServiceNotFoundException",
            "ServiceNotActiveException",
            "RepositoryNotFoundException",
            "NotFoundException",
        }

    records["application_resources"], records["toolkit_resources"] = app, toolkit
    from hirz.audit import write_export

    write_export(
        acceptance.folder / ("before-destroy-" + str(time.time_ns()) + ".json"),
        json.loads(json.dumps(records, default=str)),
    )
    ecs = acceptance.client("ecs")
    if output.get("Cluster") and output.get("WorkerService"):
        try:
            ecs.update_service(
                cluster=output["Cluster"],
                service=output["WorkerService"],
                desiredCount=0,
            )
        except ClientError as exc:
            if not absent(exc):
                raise
    try:
        if output.get("Cluster"):
            for page in ecs.get_paginator("list_tasks").paginate(
                cluster=output["Cluster"]
            ):
                for task in page["taskArns"]:
                    ecs.stop_task(
                        cluster=output["Cluster"],
                        task=task,
                        reason="End item 36 acceptance window",
                    )
    except ClientError as exc:
        if not absent(exc):
            raise
    functions = acceptance.client("lambda")
    try:
        functions.delete_function(FunctionName="hirz-item36-positive-control")
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
    schedules = acceptance.client("scheduler")
    try:
        if output.get("ScheduleGroup"):
            for page in schedules.get_paginator("list_schedules").paginate(
                GroupName=output["ScheduleGroup"]
            ):
                for item in page["Schedules"]:
                    schedules.delete_schedule(
                        GroupName=output["ScheduleGroup"], Name=item["Name"]
                    )
    except ClientError as exc:
        if not absent(exc):
            raise
    s3 = acceptance.client("s3")
    try:
        if output.get("AnchorBucket"):
            empty_bucket(s3, output["AnchorBucket"], governance_bypass=True)
    except ClientError as exc:
        if not absent(exc):
            raise

    def delete_stack(name: str) -> None:
        try:
            cfn.delete_stack(StackName=name)
        except ClientError as exc:
            if (
                exc.response["Error"]["Code"] == "ValidationError"
                and "does not exist" in exc.response["Error"]["Message"]
            ):
                return
            raise
        limit = time.monotonic() + 1800
        while time.monotonic() < limit:
            try:
                status = cfn.describe_stacks(StackName=name)["Stacks"][0]["StackStatus"]
            except ClientError as exc:
                if (
                    exc.response["Error"]["Code"] == "ValidationError"
                    and "does not exist" in exc.response["Error"]["Message"]
                ):
                    return
                raise
            if status == "DELETE_FAILED":
                raise ValueError(
                    "Stack deletion failed; inspect retained resource inventory immediately"
                )
            print(name + ": " + status, flush=True)
            time.sleep(30)
        raise ValueError("Stack deletion exceeded the cleanup deadline")

    if output.get("PolicyEngine"):
        try:
            empty_policy_engine(
                acceptance.client("bedrock-agentcore-control"), output["PolicyEngine"]
            )
        except ClientError as exc:
            if not absent(exc):
                raise
    delete_stack("HirzItem36")
    ecr = acceptance.client("ecr")
    for row in toolkit:
        if row["ResourceType"] == "AWS::S3::Bucket":
            bucket = row["PhysicalResourceId"]
            if not bucket.startswith("cdk-hirzitem36-"):
                raise ValueError("Refusing a bucket outside the dedicated toolkit")
            try:
                empty_bucket(s3, bucket)
            except ClientError as exc:
                if not absent(exc):
                    raise
        if row["ResourceType"] == "AWS::ECR::Repository":
            repo = row["PhysicalResourceId"]
            if not repo.startswith("cdk-hirzitem36-"):
                raise ValueError("Refusing a repository outside the dedicated toolkit")
            try:
                for page in ecr.get_paginator("list_images").paginate(
                    repositoryName=repo
                ):
                    images = page["imageIds"]
                    for offset in range(0, len(images), 100):
                        response = ecr.batch_delete_image(
                            repositoryName=repo, imageIds=images[offset : offset + 100]
                        )
                        if response.get("failures"):
                            raise ValueError("Owned ECR images could not be removed")
            except ClientError as exc:
                if not absent(exc):
                    raise
    delete_stack("HirzItem36Toolkit")
    for row in toolkit:
        try:
            if row["ResourceType"] == "AWS::S3::Bucket":
                s3.delete_bucket(Bucket=row["PhysicalResourceId"])
            elif row["ResourceType"] == "AWS::ECR::Repository":
                ecr.delete_repository(
                    repositoryName=row["PhysicalResourceId"], force=False
                )
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in {
                "NoSuchBucket",
                "RepositoryNotFoundException",
            }:
                raise
    # CloudFormation scheduled the seven-day KMS deletion; never cancel it.
    if output.get("CommandKey"):
        try:
            state = acceptance.client("kms").describe_key(KeyId=output["CommandKey"])[
                "KeyMetadata"
            ]
            if state["KeyState"] != "PendingDeletion":
                raise ValueError("Command key is not pending deletion")
            records["kms"] = {
                "state": state["KeyState"],
                "deletion_date": str(state["DeletionDate"]),
            }
        except ClientError as exc:
            if not absent(exc):
                raise
            records["kms"] = {"state": "absent"}
    for row in app:
        if row["ResourceType"] == "AWS::SecretsManager::Secret":
            try:
                acceptance.client("secretsmanager").delete_secret(
                    SecretId=row["PhysicalResourceId"], ForceDeleteWithoutRecovery=True
                )
            except ClientError as exc:
                if exc.response["Error"]["Code"] != "ResourceNotFoundException":
                    raise
    records["status"] = "destroyed"
    records["item36"] = "requires live evidence review and post-deletion inventory"
    return records
