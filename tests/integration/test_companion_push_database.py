"""No network: durable push retries stop after three attempts or approval expiry."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
import sqlalchemy as sa
from test_companion_auth_database import enroll
from test_database import connect
from test_database import scratch_database as scratch_database
from test_executor_database import environment

from hirz import db
from hirz.companion import auth, push
from hirz.executor.observations import ingest
from scripts.smoke_executor import action
from tests.unit.test_companion_auth import Authenticator
from tests.unit.test_companion_push import config as push_config
from tests.unit.test_companion_push import subscription
from tests.unit.test_pipeline import PRINCIPAL, ident

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("fails,expires", [(True, False), (False, False), (True, True)])
def test_delivery_retries_and_generic_payload(scratch_database, fails, expires):
    async def run():
        async with connect(scratch_database) as c:
            p, world, registry, executor = await environment(c)
            try:
                login = await enroll(
                    p,
                    await auth.initial_invitation(p, ident("members", "malik")),
                    Authenticator(),
                )
                async with c.begin():
                    member = await auth.session(c, login["session"], p.clock())
                config = push_config()
                async with p.repo.write(p.clock):
                    await push.subscribe(
                        p,
                        member["principal"],
                        member["member_id"],
                        push.Subscription.model_validate(subscription()),
                        config,
                    )
                world.clock.jump(
                    world.clock().replace(hour=4, minute=10) + timedelta(days=1)
                )
                await ingest(p, registry, PRINCIPAL)
                decision = await p.enqueue(action(world), PRINCIPAL)
                assert decision.approval, decision.model_dump_json()
                deliver = AsyncMock(
                    side_effect=RuntimeError("controlled provider failure")
                    if fails
                    else None
                )
                with patch("pywebpush.webpush_async", deliver):
                    for attempt in range(5):
                        await push.advance(p, config)
                        world.clock.jump(
                            world.clock() + timedelta(hours=1)
                            if expires and attempt == 0
                            else world.clock() + timedelta(seconds=61)
                        )
                expected_attempts = 3 if fails and not expires else 1
                assert deliver.await_count == expected_attempts
                assert (
                    deliver.call_args.kwargs["data"]
                    == '{"title": "Hirz needs your attention", "url": "/approvals"}'
                )
                async with c.begin():
                    job = (
                        (await c.execute(sa.select(db.companion_delivery)))
                        .mappings()
                        .one()
                    )
                    assert job["status"] == ("failed" if fails else "sent")
                    assert job["attempts"] == expected_attempts
                    audit = str(
                        (await c.execute(sa.select(db.audit_log.c.payload)))
                        .scalars()
                        .all()
                    )
                    assert (
                        "web.push.apple.com" not in audit
                        and "offline-test-key" not in audit
                    )
            finally:
                await registry.close()

    asyncio.run(run())
