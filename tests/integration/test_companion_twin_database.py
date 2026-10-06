"""Owner controls and simulated replies remain isolated from household approvals."""

import asyncio

import pytest
import sqlalchemy as sa
from test_companion_auth_database import enroll
from test_database import connect
from test_database import scratch_database as scratch_database
from test_pipeline_database import setup

from hirz import db
from hirz.companion import auth, twin
from tests.unit.test_companion_auth import Authenticator
from tests.unit.test_pipeline import ident

pytestmark = pytest.mark.integration


def test_isolated_scenario_controls_and_simulated_checkin(scratch_database):
    async def run():
        async with connect(scratch_database) as c:
            p = await setup(c, native=True)
            login = await enroll(
                p,
                await auth.initial_invitation(p, ident("members", "malik")),
                Authenticator(),
            )
            async with c.begin():
                principal = (await auth.session(c, login["session"], p.clock()))[
                    "principal"
                ]
            async with p.repo.write(p.clock):
                run_id = await twin.command(
                    p,
                    principal,
                    twin.Command(operation="start", scenario="parents-scam-check"),
                )
                await twin.command(
                    p, principal, twin.Command(operation="step", id=run_id, minutes=5)
                )
            await twin.advance(p)
            async with c.begin():
                view = await twin.view(p)
                current = view["runs"][0]
                assert not current["refreshing"], current
                snapshot = current["snapshot"]
                assert snapshot["status"] == "stopped", snapshot
                assert snapshot["source"] == "twin"
                checkin = snapshot["checkins"][0]
                assert checkin["status"] == "pending"
                before = await c.scalar(
                    sa.select(sa.func.count()).select_from(db.approval_votes)
                )
            async with p.repo.write(p.clock):
                await twin.command(
                    p,
                    principal,
                    twin.Command(
                        operation="inject",
                        id=run_id,
                        event={
                            "at": checkin["reply_at"],
                            "event": "contact.checkin_reply",
                            "contact": checkin["contact"],
                            "requested_at": checkin["requested_at"],
                            "deadline": checkin["deadline"],
                            "reply": "not_genuine",
                        },
                    ),
                )
            await twin.advance(p)
            async with c.begin():
                snapshot = (await twin.view(p))["runs"][0]["snapshot"]
                assert snapshot["checkins"][0]["status"] == "not_genuine"
                assert (
                    await c.scalar(
                        sa.select(sa.func.count()).select_from(db.approval_votes)
                    )
                    == before
                )
                assert (
                    await c.scalar(
                        sa.select(sa.func.count())
                        .select_from(db.audit_log)
                        .where(db.audit_log.c.event_type == "APPROVED")
                    )
                    == 0
                )

    asyncio.run(run())
