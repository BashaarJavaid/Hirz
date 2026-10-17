"""Schedules are a projection of durable actions; the minute tick repairs them."""

import hashlib
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from sqlalchemy.ext.asyncio import AsyncConnection

from hirz import db
from hirz.aws.client import call


def name(household: object, action: str) -> str:
    return "action-" + hashlib.sha256(f"{household}:{action}".encode()).hexdigest()[:56]


async def reconcile(
    connection: AsyncConnection,
    sdk: Any,
    *,
    group: str,
    target: str,
    role: str,
    at: datetime,
) -> None:
    # Snapshot only. Each invocation rechecks authority in the existing Pipeline.
    async with connection.begin():
        rows = (
            await connection.execute(
                sa.select(
                    db.actions.c.household_id,
                    db.actions.c.action_id,
                    db.actions.c.due_at,
                ).where(
                    db.actions.c.lifecycle.is_not(None),
                    db.actions.c.execution_status.in_(
                        ["scheduled", "executing", "dispatched"]
                    ),
                    db.actions.c.due_at > at,
                )
            )
        ).all()
    wanted = {
        name(household, action): due.astimezone(UTC).replace(microsecond=0)
        for household, action, due in rows
    }
    existing: set[str] = set()
    token: dict[str, str] = {}
    while True:
        page = await call(
            sdk, "list_schedules", GroupName=group, NamePrefix="action-", **token
        )
        existing.update(item["Name"] for item in page.get("Schedules", []))
        if not page.get("NextToken"):
            break
        token = {"NextToken": page["NextToken"]}
    for schedule in sorted(existing - wanted.keys()):
        try:
            await call(sdk, "delete_schedule", GroupName=group, Name=schedule)
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ResourceNotFoundException":
                raise
    for schedule, due in wanted.items():
        config = dict(
            GroupName=group,
            Name=schedule,
            ScheduleExpression=f"at({due.strftime('%Y-%m-%dT%H:%M:%S')})",
            ScheduleExpressionTimezone="UTC",
            FlexibleTimeWindow={"Mode": "OFF"},
            ActionAfterCompletion="DELETE",
            State="ENABLED",
            Target={
                "Arn": target,
                "RoleArn": role,
                "Input": "{}",
                "RetryPolicy": {
                    "MaximumEventAgeInSeconds": 120,
                    "MaximumRetryAttempts": 2,
                },
            },
        )
        current = None
        if schedule in existing:
            try:
                current = await call(
                    sdk, "get_schedule", GroupName=group, Name=schedule
                )
            except ClientError as exc:
                if exc.response["Error"]["Code"] != "ResourceNotFoundException":
                    raise
        if current and all(
            current.get(k) == v for k, v in config.items() if k != "GroupName"
        ):
            continue
        try:
            await call(
                sdk, "update_schedule" if current else "create_schedule", **config
            )
        except ClientError as exc:
            # A firing/deletion race is repaired by the next minute tick.
            if exc.response["Error"]["Code"] not in {
                "ResourceNotFoundException",
                "ConflictException",
            }:
                raise
