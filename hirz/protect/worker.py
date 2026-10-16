"""Durable single-attempt extraction, independent of household execution."""

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import sqlalchemy as sa

from hirz import db
from hirz.mcp.persistence import command
from hirz.pipeline.models import Principal, VerificationCase, VerificationExtraction
from hirz.pipeline.service import Pipeline
from hirz.protect.advice import publish
from hirz.protect.bedrock import ExtractionFailure, extract


async def transition(p: Pipeline, row: Any, case: VerificationCase) -> None:
    account = (
        (
            await p.connection.execute(
                sa.select(db.member_accounts).where(
                    p.scope(db.member_accounts),
                    db.member_accounts.c.member_id == row["member_id"],
                )
            )
        )
        .mappings()
        .first()
    )
    if account is None:
        raise ValueError("Extraction requires a linked initiating member")
    await command(
        p,
        "record_verification",
        {"operation": "extraction", "case": case.model_dump(mode="json")},
        Principal(
            provider=account["provider"], sub=account["sub"], surface="scheduler"
        ),
    )


def waiting(p: Pipeline) -> sa.ColumnElement[bool]:
    return sa.and_(
        p.scope(db.verification_cases),
        db.verification_cases.c.document["extraction"]["status"].astext.in_(
            ["pending", "running"]
        ),
    )


async def advance(p: Pipeline) -> bool:
    # Session lock owns only extraction, never the household mutation lock.
    key = "protect:" + str(p.household_id)
    async with p.connection.begin():
        locked = await p.connection.scalar(
            sa.text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"),
            {"key": key},
        )
    if not locked:
        return False
    try:
        async with p.repo.write(p.clock):
            row = (
                (
                    await p.connection.execute(
                        sa.select(db.verification_cases)
                        .where(waiting(p))
                        .order_by(
                            db.verification_cases.c.created_at,
                            db.verification_cases.c.id,
                        )
                        .limit(1)
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                return False
            case = VerificationCase.model_validate(row["document"])
            state = case.extraction
            assert state
            if (
                state.status == "running"
                or os.environ.get("HIRZ_LLM", "off") != "bedrock"
            ):
                state = state.model_copy(
                    update={
                        "status": "fallback",
                        "finished_at": p.clock(),
                        "failure_code": "interrupted"
                        if state.status == "running"
                        else "disabled",
                    }
                )
                await transition(p, row, publish(case, state))
                return True
            state = state.model_copy(
                update={"status": "running", "started_at": p.clock()}
            )
            await transition(p, row, publish(case, state))
        inference = asyncio.create_task(asyncio.to_thread(extract, case.claim.text))
        try:
            found = await asyncio.shield(inference)
            state = state.model_copy(
                update={
                    "status": "complete",
                    "model_signals": found,
                    "finished_at": p.clock(),
                }
            )
        except asyncio.CancelledError:
            # Keep extraction ownership until the non-cancellable SDK thread settles.
            await asyncio.gather(inference, return_exceptions=True)
            raise
        except ExtractionFailure as exc:
            state = VerificationExtraction.model_validate(
                state.model_dump()
                | {
                    "status": "fallback",
                    "failure_code": str(exc),
                    "finished_at": p.clock(),
                }
            )
        async with p.repo.write(p.clock):
            current = await p.connection.scalar(
                sa.select(db.verification_cases.c.document).where(
                    p.scope(db.verification_cases),
                    db.verification_cases.c.id == case.case_id,
                )
            )
            case = VerificationCase.model_validate(current)
            await transition(p, row, publish(case, state))
        return True
    finally:
        async with p.connection.begin():
            await p.connection.execute(
                sa.text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"),
                {"key": key},
            )


@asynccontextmanager
async def background(
    values: dict[str, str], database: str, parent: Pipeline
) -> AsyncIterator[asyncio.Task[None]]:
    from hirz.executor.local import policy

    async with db.connect_database(values, database=database) as connection:
        p = Pipeline(
            connection,
            parent.bundle,
            parent.boundary,
            parent.audit,
            parent.clock,
            require_active=parent.require_active,
        )

        async def run() -> None:
            while True:
                # An idle household costs one small query, never a policy load.
                async with p.connection.begin():
                    work = await p.connection.scalar(
                        sa.select(sa.exists().where(waiting(p)))
                    )
                if work:
                    p.bundle = await policy(p)
                    await advance(p)
                await asyncio.sleep(1)

        task = asyncio.create_task(run())
        try:
            yield task
            if task.done():
                await task
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
