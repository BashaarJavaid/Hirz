"""Opt-in benchmark diagnostics; never log arguments, SQL text or parameters."""

import gc
import json
import time
from contextvars import ContextVar
from hashlib import sha256
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from hirz.mcp.contracts import TOOLS, Result
from hirz.mcp.runtime import HouseholdRuntime


def install(engine: AsyncEngine, runtime: HouseholdRuntime) -> None:
    """Instrument only the disposable benchmark process, for its lifetime."""
    current: ContextVar[dict[str, Any] | None] = ContextVar("diagnostic", default=None)
    collections: dict[int, tuple[float, dict[str, Any] | None]] = {}

    def before(*args: Any) -> None:
        args[4]._diagnostic_started = time.perf_counter()

    def after(*args: Any) -> None:
        sample = current.get()
        if sample is not None:
            sample["queries"].append(
                {
                    "fingerprint": sha256(args[2].encode()).hexdigest(),
                    "ms": (time.perf_counter() - args[4]._diagnostic_started) * 1000,
                }
            )

    def collection(phase: str, info: dict[str, Any]) -> None:
        generation = info["generation"]
        if phase == "start":
            collections[generation] = time.perf_counter(), current.get()
        elif generation in collections:
            started, sample = collections.pop(generation)
            if sample is not None:
                sample["gc"].append(
                    {
                        "generation": generation,
                        "ms": (time.perf_counter() - started) * 1000,
                    }
                )

    event.listen(engine.sync_engine, "before_cursor_execute", before)
    event.listen(engine.sync_engine, "after_cursor_execute", after)
    gc.callbacks.append(collection)
    original = runtime.call

    async def call(name: str, arguments: dict[str, Any]) -> Result:
        sample: dict[str, Any] = {"queries": [], "gc": []}
        token = current.set(sample)
        started = time.perf_counter()
        cpu_started = time.thread_time()
        try:
            return await original(name, arguments)
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            cpu_elapsed = (time.thread_time() - cpu_started) * 1000
            current.reset(token)
            queries = sample["queries"]
            print(
                "DIAGNOSTIC_NOT_GATE "
                + json.dumps(
                    {
                        "tool": name if name in TOOLS else "unknown",
                        "method_ms": elapsed,
                        "thread_cpu_ms": cpu_elapsed,
                        "query_count": len(queries),
                        "query_ms": sum(q["ms"] for q in queries),
                        "slowest_queries": sorted(
                            queries, key=lambda q: q["ms"], reverse=True
                        )[:3],
                        "gc": sample["gc"],
                    }
                ),
                flush=True,
            )

    runtime.call = call  # type: ignore[method-assign]
