"""Cancellation retains drafting ownership until the bounded provider call settles."""

import asyncio
import threading
from pathlib import Path

import pytest
import sqlalchemy as sa
import yaml
from test_database import connect
from test_database import scratch_database as scratch_database
from test_pipeline_database import setup

from hirz import db
from hirz.audit import verify_database
from hirz.companion import drafting
from hirz.mcp.household import HouseholdTools
from hirz.twin.scenario import Patch
from tests.unit.test_pipeline import PRINCIPAL

pytestmark = pytest.mark.integration


def test_cancellation_keeps_lock_and_queued_proposal(scratch_database, monkeypatch):
    monkeypatch.setenv("HIRZ_LLM", "bedrock")
    monkeypatch.setenv("HIRZ_DRAFT_MODEL_ID", "synthetic-no-network")
    patch = Patch.model_validate(
        yaml.safe_load(
            Path("scenarios/fixtures/patch-never-unexpected-visitor.yaml").read_text()
        )
    )

    async def run():
        started, finish = asyncio.Event(), threading.Event()
        loop = asyncio.get_running_loop()
        calls = []

        def converse(self, sentence, base):
            calls.append(sentence)
            loop.call_soon_threadsafe(started.set)
            assert finish.wait(5)
            return patch

        monkeypatch.setattr(drafting.BedrockDrafting, "converse", converse)
        async with connect(scratch_database) as c, connect(scratch_database) as other:
            p = await setup(c, native=True)
            result = await HouseholdTools(p, PRINCIPAL).call(
                "propose_household_rule",
                {
                    "text": "Never unlock for unexpected visitors.",
                    "request_id": "cancelled-draft",
                },
            )
            assert result.data.status == "recorded"
            lock = sa.text(
                "SELECT pg_try_advisory_lock(hashtext('hirz-drafting'), hashtext(:home))"
            )
            unlock = sa.text(
                "SELECT pg_advisory_unlock(hashtext('hirz-drafting'), hashtext(:home))"
            )
            params = {"home": str(p.household_id)}
            task = asyncio.create_task(drafting.advance(p))
            try:
                await asyncio.wait_for(started.wait(), 3)
                assert not c.in_transaction()
                task.cancel()
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(asyncio.shield(task), 0.1)
                async with other.begin():
                    assert not await other.scalar(lock, params)
            finally:
                finish.set()
                await asyncio.gather(task, return_exceptions=True)
            assert task.cancelled() and len(calls) == 1
            async with other.begin():
                assert await other.scalar(lock, params)
                assert await other.scalar(unlock, params)
                assert (
                    await other.scalar(sa.select(db.rule_proposals.c.status))
                    == "queued"
                )
                assert (
                    await other.scalar(
                        sa.select(sa.func.count()).select_from(db.companion_drafts)
                    )
                    == 0
                )
            # A later attempt can safely draft, but cannot activate the proposed rules.
            await drafting.advance(p)
            async with c.begin():
                assert await c.scalar(sa.select(db.rule_proposals.c.status)) == "ready"
                assert (
                    await c.scalar(sa.select(db.constitution_versions.c.status))
                    == "unvalidated"
                )
            await verify_database(c, p.household_id, p.audit.key.public_key())

    asyncio.run(run())
