"""AWS request composition over disposable PostgreSQL and real passkey ceremonies."""

import asyncio
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import sqlalchemy as sa
from test_database import connect, migrate
from test_database import scratch_database as scratch_database
from webauthn.helpers import base64url_to_bytes

from hirz import db
from hirz.api.app import create_app
from hirz.audit import verify_database
from hirz.aws.fixture import load
from hirz.aws.probe import PRINCIPAL
from hirz.aws.worker import tick
from hirz.companion.api import Companion
from hirz.companion.auth import initial_invitation
from hirz.constitution.schema import dump
from hirz.graph.models import now
from hirz.local import read_env, signing_key
from hirz.pipeline.audit import AuditWriter
from hirz.twin.authenticator import CONFIG, Authenticator
from hirz.twin.execution import bootstrap
from scripts.smoke_executor import action

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("interrupt_after_dispatch", [False, True])
def test_aws_tick_activation_cancellation_duplicate_and_restart(
    scratch_database, monkeypatch, interrupt_after_dispatch
):
    async def run():
        start = now() - timedelta(minutes=2)
        monkeypatch.setenv("HIRZ_FIXTURE_START", start.isoformat())
        monkeypatch.setenv("HIRZ_LLM", "off")
        for field in ("HIRZ_SCHEDULE_GROUP", "HIRZ_SCHEDULE_ROLE", "HIRZ_TICK_ARN"):
            monkeypatch.setenv(field, "test")
        monkeypatch.setattr("hirz.aws.worker.client", lambda _: Mock())
        scheduled = {}

        async def sdk_call(sdk, method, **args):
            from botocore.exceptions import ClientError

            key = args.get("Name")
            if method == "list_schedules":
                return {"Schedules": [{"Name": k} for k in scheduled]}
            if method in {"create_schedule", "update_schedule"}:
                scheduled[key] = args
                return {}
            if method == "delete_schedule":
                del scheduled[key]
                return {}
            if key not in scheduled:
                raise ClientError(
                    {"Error": {"Code": "ResourceNotFoundException"}}, method
                )
            return scheduled[key]

        calls = AsyncMock(side_effect=sdk_call)
        monkeypatch.setattr("hirz.aws.schedules.call", calls)
        monkeypatch.setattr("hirz.aws.client.call", calls)
        monkeypatch.setattr("hirz.aws.probe.client", lambda _: Mock())
        loaded = load()
        audit = AuditWriter(signing_key(read_env(Path(".env"))))
        async with connect(scratch_database) as c:
            await migrate(c)
            p = await bootstrap(loaded, c, audit=audit)
            p.clock = now
            service = Companion(c.engine, audit, CONFIG)
            app = create_app(companion=service)
            key = Authenticator()
            invitation = await initial_invitation(p, loaded.ref("members", "malik"))
            async with (
                service.boundary.persistent(),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url=CONFIG.origin,
                    headers={"Origin": CONFIG.origin},
                ) as client,
            ):

                async def post(path, data):
                    response = await client.post("/api/" + path, json=data)
                    assert response.status_code == 200, response.text
                    return response.json()

                async def ceremony(binding):
                    options = await post("auth/begin", binding)
                    return await post(
                        "auth/finish",
                        {
                            "id": options["id"],
                            "credential": key.response(
                                base64url_to_bytes(options["publicKey"]["challenge"]),
                                register=binding["operation"] == "enroll",
                            ),
                        },
                    )

                await client.get("/api/auth/session")
                login = await ceremony({"operation": "enroll", "token": invitation})
                client.headers["x-hirz-csrf"] = login["csrf"]
                draft = await post(
                    "constitution/draft", {"yaml": dump(p.bundle.policy())}
                )
                await post("constitution/review", {"id": draft["id"]})
                await ceremony(
                    {
                        "operation": "activate",
                        "draft_id": draft["id"],
                        "candidate_hash": draft["candidate_hash"],
                    }
                )
                async with service.pipeline(p.household_id) as q:
                    from hirz.executor.local import compose
                    from hirz.executor.observations import ingest
                    from hirz.twin.clock import SimClock

                    loaded.world.clock = SimClock(now(), 1)
                    r = await compose(
                        q,
                        world=loaded.world,
                        config=",".join(f"{d}:twin" for d in loaded.spec.adapters),
                    )
                    await r.start()
                    try:
                        await ingest(q, r, PRINCIPAL)
                        light = action(loaded.world)
                        decision = await q.enqueue(light, PRINCIPAL)
                        assert decision.status == "executing", decision
                    finally:
                        await r.close()
                if interrupt_after_dispatch:
                    # Interrupt after the signed twin checkpoint commits, before read-back.
                    from hirz.pipeline.service import Pipeline

                    reached = asyncio.Event()

                    async def interrupted_outcome(*args, **kwargs):
                        reached.set()
                        await asyncio.Event().wait()

                    with monkeypatch.context() as interrupted:
                        interrupted.setattr(
                            Pipeline, "execution_outcome", interrupted_outcome
                        )
                        pending = asyncio.create_task(tick(service))
                        try:
                            async with asyncio.timeout(10):
                                await reached.wait()
                        finally:
                            pending.cancel()
                            with pytest.raises(asyncio.CancelledError):
                                await pending
                    async with c.begin():
                        assert (
                            await c.scalar(
                                sa.select(db.actions.c.execution_status).where(
                                    db.actions.c.action_id == light.action_id
                                )
                            )
                            == "dispatched"
                        )
                # Existing recovery holds an uncertain dispatch; it never silently verifies or redispatches.
                await tick(service)
                await tick(service)
                async with c.begin():
                    stored = (
                        (
                            await c.execute(
                                sa.select(db.actions).where(
                                    db.actions.c.action_id == light.action_id
                                )
                            )
                        )
                        .mappings()
                        .one()
                    )
                    assert stored["execution_status"] == (
                        "failed" if interrupt_after_dispatch else "verified"
                    )
                    events = (
                        (
                            await c.execute(
                                sa.select(db.audit_log.c.event_type).where(
                                    db.audit_log.c.payload["action_id"].astext
                                    == light.action_id
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                    assert events.count("EXECUTION_ATTEMPTED") == 1
                    assert events.count("VERIFIED") == (
                        0 if interrupt_after_dispatch else 1
                    )
                    if interrupt_after_dispatch:
                        assert events.count("VERIFY_FAILED") == 1
                from hirz.aws.probe import run as probe

                monkeypatch.setattr("hirz.aws.probe.database", lambda _: c.engine)
                monkeypatch.setattr("hirz.aws.probe.secret", lambda _: "fixture")
                monkeypatch.setattr("hirz.aws.probe.signing_key", lambda _: audit.key)
                cancelled = await probe("cancel", None, None)
                assert cancelled["status"] == "cancelled"
                summary, _ = await verify_database(
                    c, p.household_id, audit.key.public_key()
                )
                assert summary["status"] == "valid"
                assert calls.await_count >= 2

    asyncio.run(run())


def test_non_superuser_owns_schema_and_materialized_view(scratch_database):
    import secrets
    from uuid import uuid4

    from hirz.graph.seeds import load_seeds, read_seed

    role, password = "hirz_aws_role_" + uuid4().hex, secrets.token_hex(20)
    setup_role = "hirz_aws_setup_" + uuid4().hex

    async def run():
        async with connect(scratch_database) as admin:
            await admin.execute(
                sa.text(
                    f"CREATE ROLE {setup_role} LOGIN NOSUPERUSER CREATEDB CREATEROLE PASSWORD '{password}'"
                )
            )
            await admin.execute(
                sa.text(
                    f'ALTER DATABASE "{scratch_database.database}" OWNER TO {setup_role}'
                )
            )
            await admin.execute(sa.text(f"ALTER SCHEMA public OWNER TO {setup_role}"))
            await admin.commit()
            try:
                async with connect(
                    scratch_database.set(username=setup_role, password=password)
                ) as setup:
                    await setup.execute(
                        sa.text(
                            f"CREATE ROLE {role} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD '{password}'"
                        )
                    )
                    assert not await setup.scalar(
                        sa.text(f"SELECT pg_has_role(current_user, '{role}', 'SET')")
                    )
                    await setup.execute(
                        sa.text(
                            f"GRANT {role} TO CURRENT_USER WITH INHERIT TRUE, SET TRUE"
                        )
                    )
                    await setup.execute(
                        sa.text(
                            f'ALTER DATABASE "{scratch_database.database}" OWNER TO {role}'
                        )
                    )
                    await setup.execute(sa.text(f"ALTER SCHEMA public OWNER TO {role}"))
                    await setup.commit()
                async with connect(
                    scratch_database.set(username=role, password=password)
                ) as application:
                    await migrate(application)
                    await application.run_sync(db.require_current)
                    flags = (
                        await application.execute(
                            sa.text(
                                "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication FROM pg_roles WHERE rolname=current_user"
                            )
                        )
                    ).one()
                    assert flags == (False, False, False, False)
                    owner = await application.scalar(
                        sa.text(
                            "SELECT matviewowner FROM pg_matviews WHERE matviewname='household_context'"
                        )
                    )
                    assert owner == role
                    await application.rollback()
                    await load_seeds(
                        application, [read_seed(Path("constitutions/quinn-home.yaml"))]
                    )
                    async with application.begin():
                        await application.execute(
                            sa.text("REFRESH MATERIALIZED VIEW household_context")
                        )
            finally:
                await admin.execute(
                    sa.text(
                        f'ALTER DATABASE "{scratch_database.database}" OWNER TO hirz'
                    )
                )
                await admin.execute(sa.text("ALTER SCHEMA public OWNER TO hirz"))
                for disposable_role in (role, setup_role):
                    if await admin.scalar(
                        sa.text("SELECT 1 FROM pg_roles WHERE rolname=:name"),
                        {"name": disposable_role},
                    ):
                        await admin.execute(
                            sa.text(f"DROP OWNED BY {disposable_role} CASCADE")
                        )
                        await admin.execute(sa.text(f"DROP ROLE {disposable_role}"))
                await admin.commit()

    asyncio.run(run())
