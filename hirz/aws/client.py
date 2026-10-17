"""Bounded AWS calls, including settling an SDK thread on cancellation."""

import asyncio
from typing import Any

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]


def client(service: str) -> Any:
    return boto3.client(
        service,
        region_name="us-east-1",
        config=Config(connect_timeout=3, read_timeout=5, retries={"max_attempts": 1}),
    )


async def call(sdk: Any, method: str, **kwargs: Any) -> Any:
    task = asyncio.create_task(asyncio.to_thread(getattr(sdk, method), **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.gather(task, return_exceptions=True)
        raise
