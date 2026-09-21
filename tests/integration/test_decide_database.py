"""Nine real CLI decisions with native Dogwood and isolated PostgreSQL fixtures."""

import asyncio
import io
import json
import re
import shlex
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
import sqlalchemy as sa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from test_database import connect, migrate
from test_database import scratch_database as scratch_database

from hirz import cli, db
from hirz.constitution.boundary import BoundaryResult, Dogwood
from hirz.constitution.schema import loads
from hirz.graph.models import ASSET_DOMAINS, Observation, Preference
from hirz.graph.repository import GraphRepository
from hirz.graph.seeds import Seed, demo_id, load_seeds, read_seed
from hirz.pipeline.audit import AuditWriter
from hirz.pipeline.models import Principal
from hirz.pipeline.service import Pipeline, PolicyBundle
from tests.unit.test_decide import arguments
from tests.unit.test_pipeline import HOME, SEED, action, ident, snapshot

pytestmark = pytest.mark.integration
DAY = datetime.fromisoformat("2026-10-13T17:35:00-05:00")


async def setup(
    connection,
    at=DAY,
    *,
    version=7,
    asleep=False,
    teen=False,
    slug="quinn-home",
    observations=True,
):
    await migrate(connection)
    original = (
        SEED if slug == "quinn-home" else read_seed(Path(f"constitutions/{slug}.yaml"))
    )
    graph, policy = deepcopy(original.graph), deepcopy(original.constitution)
    if teen:
        graph["members"].append(
            {"id": "teen", "display_name": "Synthetic teen", "role": "teen"}
        )
        graph["member_accounts"].append(
            {"provider": "demo", "sub": "teen", "member_id": "teen"}
        )
    if version == 8:
        policy["version"] = 8
        policy["autonomy"]["security"]["door_unlock"]["never_for"] = [
            "unexpected_visitor"
        ]
    seed = Seed(graph, policy)
    await load_seeds(connection, [seed], lambda: at - timedelta(seconds=2))
    key = ec.generate_private_key(ec.SECP256R1())
    if slug == "quinn-parents":
        return seed, key
    observed = at - timedelta(seconds=1)
    models = seed.models(observed)
    zones = [a for a in models["assets"] if a.kind == "hvac_zone"]
    zone = next((z.id for z in zones if z.name == "Living room"), zones[0].id)
    repo = GraphRepository(connection, seed.household_id)
    async with repo.write(lambda: observed):
        for kind, field in (("members", "member_id"), ("assets", "asset_id")):
            for subject in models[kind] if observations else []:
                await repo.put(
                    "observations",
                    Observation.model_validate(
                        {
                            "id": uuid4(),
                            "household_id": seed.household_id,
                            field: subject.id,
                            "observed_at": observed,
                            "source": "twin",
                            "domain": "presence"
                            if kind == "members"
                            else ASSET_DOMAINS[subject.kind],
                            "state": {"available": True}
                            | (
                                {
                                    "present": True,
                                    "sleeping": asleep
                                    and subject.id == demo_id(slug, "members", "mom"),
                                    "zone_id": str(zone),
                                }
                                if kind == "members"
                                else {"last_press_at": observed.isoformat()}
                                if subject.kind == "doorbell"
                                else {}
                            ),
                        }
                    ),
                )
        if slug == "quinn-home":
            await repo.put(
                "preferences",
                Preference(
                    id=uuid4(),
                    household_id=HOME,
                    member_id=ident("members", "malik"),
                    scope="member",
                    key="temperature_target_f",
                    value=72,
                    source="declared",
                    confidence=1,
                ),
            )
    return seed, key


def invoke(url, key, args):
    values = {
        "AUDIT_SIGNING_KEY": key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
    }
    out, err = io.StringIO(), io.StringIO()
    with (
        patch("sys.argv", args),
        patch("hirz.pipeline.cli.read_env", return_value=values),
        patch("hirz.pipeline.cli.db.connect_database", lambda _: connect(url)),
        redirect_stdout(out),
        redirect_stderr(err),
    ):
        code = cli.main()
    return code, out.getvalue(), err.getvalue()


async def state(connection):
    """Fingerprint every application table and the materialized context view."""
    contents = []
    for name in [*sorted(db.metadata.tables), "household_context"]:
        contents.append(
            await connection.scalar(
                sa.text(
                    f"SELECT COALESCE(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text), '[]')::text FROM \"{name}\" t"
                )
            )
        )
    await connection.rollback()
    return sha256(json.dumps(contents).encode()).hexdigest()


CASES = [
    ("daytime_hvac", "energy.hvac_adjust", "EXECUTE"),
    ("sleeping_hvac", "energy.hvac_adjust", "ASK_CONSTITUTION"),
    ("teen_unlock", "security.door_unlock", "DENY_CONSTITUTION"),
    ("unexpected_v7", "security.door_unlock", "ASK_CONSTITUTION"),
    ("unexpected_v8", "security.door_unlock", "DENY_CONSTITUTION"),
    ("expected_arrival", "security.door_unlock", "ASK_CONSTITUTION"),
    ("stranger_in_window", "security.door_unlock", "ASK_CONSTITUTION"),
    ("suspicious_request", "finance.verify_request", "VERIFY"),
    ("budget_exceeded", "energy.optimize_cost", "DENY_BUDGET"),
]


@pytest.mark.parametrize("case,name,expected", CASES, ids=[c[0] for c in CASES])
def test_worked_examples(case, name, expected, scratch_database, tmp_path):
    async def run():
        at = (
            DAY.replace(hour=23, minute=40)
            if case == "sleeping_hvac"
            else DAY.replace(hour=19, minute=4)
            if case in {"expected_arrival", "stranger_in_window"}
            else DAY
        )
        async with connect(scratch_database) as connection:
            seed, key = await setup(
                connection,
                at,
                version=8 if case == "unexpected_v8" else 7,
                asleep=case == "sleeping_hvac",
                teen=case == "teen_unlock",
            )
            if case == "budget_exceeded":
                boundary = Dogwood()
                bundle = await PolicyBundle.validate(HOME, loads(seed.yaml), boundary)
                pipeline = Pipeline(
                    connection, bundle, boundary, AuditWriter(key), lambda: at
                )
                grant = await pipeline.redeem(
                    action(name),
                    Principal(provider="demo", sub="malik", surface="app"),
                    cost=Decimal("9.60"),
                )
                assert grant.event_type == "EXECUTE" and grant.audit_id is not None
            before = await state(connection)
            a = action(name)
            facts = {
                "scam_pattern": {
                    "household_id": str(HOME),
                    "observed_at": at.isoformat(),
                    "source": "twin",
                    "scam_pattern": case == "suspicious_request",
                }
            }
            path = tmp_path / "evidence.json"
            path.write_text(json.dumps(facts))
            options = dict(
                action=name,
                adapter=a.target.adapter,
                entity=a.target.entity,
                params=json.dumps(a.params),
                at=at.isoformat(),
                evidence=str(path),
            )
            if a.target.zone:
                options["zone"] = a.target.zone
            if case == "teen_unlock":
                options["as"] = "teen"
            if case == "budget_exceeded":
                options["cost"] = "0.80"
            args = arguments(**options) + ["--requester-confirmed"]
            code, output, errors = await asyncio.to_thread(
                invoke, scratch_database, key, args
            )
            assert code == 0, errors
            decision = json.loads(output)
            assert decision["event_type"] == expected, decision
            assert decision["approval"] is None and decision["audit_id"] is None
            assert decision["constitution"]["version"] == seed.version
            assert "unactivated" in errors and "simulated" in errors
            assert decision["boundary"]["engine"] == "dogwood-local"
            if case == "daytime_hvac":
                assert decision["risk"]["band"] == "low"
                assert decision["boundary"]["result"] == "allow"
            if case == "budget_exceeded":
                assert decision["budget"]["used"] == "9.60"
                assert decision["budget"]["reserved"] == "0"
            assert await state(connection) == before
            print(
                f"{case}: {decision['event_type']}; audit=null; approval=null; database=unchanged"
            )

    asyncio.run(run())


def test_stored_policy_and_prerequisite_failures(scratch_database):
    async def run():
        async with connect(scratch_database) as connection:
            await migrate(connection)
            key = ec.generate_private_key(ec.SECP256R1())
            code, out, err = await asyncio.to_thread(
                invoke, scratch_database, key, arguments()
            )
            assert code == 1 and not out and "missing" in err
            seed, key = await setup(connection)
            for text, stored_hash in [
                (seed.yaml, "0" * 64),
                (seed.yaml.replace("version: 7", "version: 8"), None),
                (
                    seed.yaml.replace(
                        "household: quinn-home", "household: quinn-parents"
                    ),
                    None,
                ),
                ("PRIVATE: [", None),
                (seed.yaml + "version: 7\n", None),
                (
                    seed.yaml.replace("- app_push", "- alexa"),
                    None,
                ),
            ]:
                # Synthetic damaged storage, never a runtime policy-update path.
                async with connection.begin():
                    await connection.execute(
                        db.constitution_versions.update()
                        .where(db.constitution_versions.c.household_id == HOME)
                        .values(
                            yaml=text,
                            hash=stored_hash or sha256(text.encode()).hexdigest(),
                        )
                    )
                before = await state(connection)
                code, out, err = await asyncio.to_thread(
                    invoke, scratch_database, key, arguments()
                )
                assert code == 1 and not out, err
                assert "PRIVATE" not in err
                assert await state(connection) == before
            async with connection.begin():
                await connection.execute(
                    db.constitution_versions.update()
                    .where(db.constitution_versions.c.household_id == HOME)
                    .values(yaml=seed.yaml, hash=seed.hash)
                )
            before = await state(connection)
            with patch.dict("os.environ", {"HIRZ_DOGWOOD": "/PRIVATE/missing-dogwood"}):
                code, out, err = await asyncio.to_thread(
                    invoke, scratch_database, key, arguments()
                )
            assert code == 1 and not out and "PRIVATE" not in err
            assert await state(connection) == before

    asyncio.run(run())


@pytest.mark.parametrize("case", ["missing", "fill", "conflict", "foreign", "future"])
def test_missing_and_conflicting_evidence_fails_closed(
    case, scratch_database, tmp_path
):
    async def run():
        async with connect(scratch_database) as connection:
            _, key = await setup(connection, observations=case == "conflict")
            before = await state(connection)
            readings = snapshot().data["observations"]
            for row in readings:
                row["observed_at"] = DAY.isoformat()
            if case == "foreign":
                readings[0]["household_id"] = str(uuid4())
            if case == "future":
                readings[0]["observed_at"] = (DAY + timedelta(seconds=1)).isoformat()
            path = tmp_path / "facts.json"
            path.write_text(
                json.dumps({"observations": [] if case == "missing" else readings})
            )
            args = arguments(
                action="energy.hvac_adjust",
                adapter="twin",
                entity="hvac.living_room",
                zone=str(ident("assets", "hvac.living_room")),
                params='{"target_f":72}',
                at=DAY.isoformat(),
                evidence=str(path),
            )
            code, out, err = await asyncio.to_thread(
                invoke, scratch_database, key, args
            )
            assert code == 0, err
            decision = json.loads(out)
            assert decision["event_type"] == {
                "missing": "DENY_RISK",
                "fill": "EXECUTE",
            }.get(case, "DENY_CONSTITUTION")
            assert decision["audit_id"] is None and decision["approval"] is None
            assert await state(connection) == before
            print(f"overlay {case}: {decision['event_type']}; database=unchanged")

    asyncio.run(run())


def test_other_home_unknown_confirmation_governance_and_boundary(
    scratch_database, tmp_path
):
    async def run():
        async with connect(scratch_database) as connection:
            _, key = await setup(connection)
            before = await state(connection)
            path = tmp_path / "facts.json"
            path.write_text("{}")
            for changes, expected in [
                ({"as": "unlinked"}, "DENY_CONSTITUTION"),
                ({"action": "governance.pause_automation"}, "EXECUTE"),
                (
                    {"action": "governance.resume_automation", "surface": "app"},
                    "EXECUTE",
                ),
                (
                    {
                        "action": "security.door_unlock",
                        "adapter": "twin",
                        "entity": "lock.front_door",
                        "params": '{"open_minutes":10}',
                        "evidence": str(path),
                    },
                    "ASK_REQUESTER_CONFIRMATION",
                ),
                (
                    {
                        "action": "energy.hvac_adjust",
                        "adapter": "twin",
                        "entity": "hvac.living_room",
                        "zone": str(ident("assets", "hvac.living_room")),
                        "params": '{"target_f":72}',
                        "evidence": str(path),
                    },
                    "EXECUTE",
                ),
            ]:
                args = arguments(**({"at": DAY.isoformat()} | changes))
                code, out, err = await asyncio.to_thread(
                    invoke, scratch_database, key, args
                )
                assert code == 0, err
                assert json.loads(out)["event_type"] == expected
                if changes.get("action") == "energy.hvac_adjust":
                    for result in (BoundaryResult(False), None):
                        with patch.object(Dogwood, "authorize", return_value=result):
                            code, out, err = await asyncio.to_thread(
                                invoke, scratch_database, key, args
                            )
                        assert (
                            code == 0
                            and json.loads(out)["event_type"] == "DENY_BOUNDARY"
                        )
            assert await state(connection) == before
            seed, key = await setup(connection, slug="quinn-parents")
            before = await state(connection)
            code, out, err = await asyncio.to_thread(
                invoke,
                scratch_database,
                key,
                arguments(
                    household=str(seed.household_id),
                    entity=str(seed.household_id),
                    action="governance.pause_automation",
                    at=DAY.isoformat(),
                    **{"as": "mom"},
                ),
            )
            assert code == 0, err
            assert json.loads(out)["event_type"] == "EXECUTE"
            assert await state(connection) == before

    asyncio.run(run())


def test_documented_light_preview(scratch_database, tmp_path):
    """Run the actual documentation example, substituting only its file/DB/key."""
    section = (
        Path("docs/development.md").read_text().split("**Explicit preview file.**")[1]
    )
    example = re.search(r"```json\n(.*?)\n```", section, re.DOTALL).group(1)
    command = re.search(r"```sh\n(.*?)\n```", section, re.DOTALL).group(1)
    args = shlex.split(command.replace("\\\n", ""))[2:]
    path = tmp_path / "light-preview.json"
    path.write_text(example)
    args[args.index("--evidence") + 1] = str(path)

    async def run():
        async with connect(scratch_database) as connection:
            _, key = await setup(connection, observations=False)
            before = await state(connection)
            code, output, errors = await asyncio.to_thread(
                invoke, scratch_database, key, args
            )
            assert code == 0, errors
            decision = json.loads(output)
            assert decision["event_type"] == "EXECUTE"
            assert decision["audit_id"] is None and decision["approval"] is None
            assert decision["boundary"]["result"] == "allow"
            assert await state(connection) == before
            print(
                "documented light preview: EXECUTE; dogwood-local=allow; audit=null; approval=null; database=unchanged"
            )

    asyncio.run(run())
