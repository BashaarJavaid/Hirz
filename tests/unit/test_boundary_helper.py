"""A failed private pipe never becomes a CLI fallback or a reused response."""

import asyncio
import sys
from pathlib import Path

import pytest

from hirz.constitution.boundary import BoundaryError, Dogwood, Event
from hirz.constitution.compiler import compile_policy
from hirz.constitution.schema import load

COMPILED = compile_policy(load(Path("constitutions/quinn-home.yaml")))


def helper(tmp_path, body, *, timeout=0.5):
    executable = tmp_path / "dogwood"
    child = executable.with_name("dogwood-helper")
    child.write_text(f"#!{sys.executable}\nimport sys\n" + body + "\n")
    child.chmod(0o700)
    return Dogwood(str(executable), timeout=timeout)


@pytest.mark.parametrize(
    "body",
    [
        "sys.stdin.readline(); print('not json', flush=True)",
        "sys.stdin.readline(); print('[]', flush=True)",
        'sys.stdin.readline(); print(\'{"error":"rejected"}\', flush=True)',
        "sys.stdin.readline(); print('{\"verdicts\":[]}', flush=True)",
        "sys.stdin.readline(); raise SystemExit(3)",
        "sys.stdin.readline(); import time; time.sleep(10)",
    ],
)
def test_helper_failure_reaps_and_disables_session(tmp_path, body):
    async def run():
        engine = helper(tmp_path, body)
        async with engine.persistent():
            process = engine._process
            assert process is not None
            for _ in range(2):
                result = await engine.authorize(
                    COMPILED, Event(1, "environment.lights", {})
                )
                assert not result.allowed and result.diagnostic == "DENY_BOUNDARY"
                assert process.returncode is not None
            assert engine._process is None
        assert not engine._persistent

    asyncio.run(run())


def test_helper_cancellation_and_lifespan_cleanup(tmp_path):
    async def run():
        engine = helper(tmp_path, "sys.stdin.readline(); import time; time.sleep(10)")
        async with engine.persistent():
            process = engine._process
            task = asyncio.create_task(engine._exchange(COMPILED, "trace"))
            await asyncio.sleep(0.02)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert process is not None and process.returncode is not None
        async with engine.persistent():
            process = engine._process
            with pytest.raises(BoundaryError, match="already active"):
                async with engine.persistent():
                    pass
        assert process is not None and process.returncode is not None
        with pytest.raises(BoundaryError, match="unavailable"):
            async with Dogwood(str(tmp_path / "missing")).persistent():
                pass

    asyncio.run(run())


@pytest.mark.parametrize("ready", ["false", "1"])
def test_helper_preparation_requires_exact_acknowledgement(tmp_path, ready):
    async def run():
        engine = helper(
            tmp_path,
            f"sys.stdin.readline(); print('{{\"ready\":{ready}}}', flush=True)",
            timeout=5,
        )
        Path(engine.executable).write_text(
            f"#!{sys.executable}\n"
            'print(\'{"passed":true,"errors":[],"warnings":[]}\')\n'
        )
        Path(engine.executable).chmod(0o700)
        async with engine.persistent():
            process = engine._process
            with pytest.raises(BoundaryError, match="preparation failed"):
                await engine.validate(COMPILED)
            assert process is not None and process.returncode is not None

    asyncio.run(run())
