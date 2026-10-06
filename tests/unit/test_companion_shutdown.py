"""Shutdown diagnostics expose locations, including async contexts, without data."""

import asyncio
import json
from contextlib import asynccontextmanager

from scripts.companion_demo import shutdown_stacks


def test_shutdown_stacks_follow_context_without_payloads():
    async def run():
        started = asyncio.Event()

        @asynccontextmanager
        async def context():
            secret = "private-frame-value"
            started.set()
            await asyncio.Event().wait()
            yield secret

        async def work():
            async with context():
                pass

        task = asyncio.create_task(work(), name="private-task-name")
        try:
            await started.wait()
            stacks = shutdown_stacks()
            assert any(
                sum(frame.startswith("test_companion_shutdown.py:") for frame in stack)
                == 2
                for stack in stacks
            )
            assert "private-" not in json.dumps(stacks)
            assert all(
                frame.rsplit(":", 1)[1].isdigit() for stack in stacks for frame in stack
            )
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())
