import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from hirz.aws.tick import router

SECRET = "ab" * 32


def test_auth_before_body_and_no_payload():
    async def run():
        process = AsyncMock()
        app = FastAPI()
        app.include_router(router(SECRET, process))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="https://worker"
        ) as client:
            assert (
                await client.post("/internal/tick", content=b"{}")
            ).status_code == 401
            for headers in (
                {"Authorization": "Bearer wrong"},
                [("Authorization", "Bearer " + SECRET)] * 2,
            ):
                assert (
                    await client.post("/internal/tick", headers=headers)
                ).status_code == 401
            headers = {"Authorization": "Bearer " + SECRET}
            assert (
                await client.post("/internal/tick", headers=headers, content=b"{}")
            ).status_code == 400
            process.assert_not_awaited()
            for _ in range(2):
                assert (
                    await client.post("/internal/tick", headers=headers)
                ).status_code == 204
            assert process.await_count == 2
            process.side_effect = ValueError("private input")
            failed = await client.post("/internal/tick", headers=headers)
            assert failed.status_code == 503 and not failed.content

    asyncio.run(run())


def test_deadline_settles_child_before_retry():
    async def run():
        cancelled = asyncio.Event()
        recovered = False

        async def child():
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                cancelled.set()

        async def process():
            if recovered:
                return
            task = asyncio.create_task(child())
            try:
                await task
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

        app = FastAPI()
        app.include_router(router(SECRET, process, deadline=0.01))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="https://worker",
            headers={"Authorization": "Bearer " + SECRET},
        ) as client:
            assert (await client.post("/internal/tick")).status_code == 503
            assert cancelled.is_set()
            recovered = True
            assert (await client.post("/internal/tick")).status_code == 204

    asyncio.run(run())


def test_invalid_secret():
    for value in ("", "UNINITIALIZED", "ab" * 31, "g" * 64):
        with pytest.raises(ValueError):
            router(value, AsyncMock())
