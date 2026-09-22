"""Strict scripted input, isolated references and signed-row selection contracts."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from hirz.pipeline.models import EventType
from hirz.twin.execution import Host, audit_checks
from hirz.twin.scenario import LoadedScenario
from hirz.twin.script import Binding, Range, ScriptCall, selector


@pytest.mark.parametrize(
    "tool,args",
    [
        ("get_household_plan", {"invented": 1}),
        ("approve_action", {"approved": "true"}),
        ("execute_household_action", {"asset": "lamp", "on": {"value": True}}),
        ("revise_household_plan", {"text": ""}),
        ("security.unlock", {}),
    ],
)
def test_strict_flat_scripts(tool, args):
    with pytest.raises(ValueError):
        ScriptCall(tool=tool, arguments=args)


@pytest.mark.parametrize("data", [{}, {"min": 2, "max": 1}, {"min": float("nan")}])
def test_ranges_reject_ambiguous_expectations(data):
    with pytest.raises(ValueError):
        Range.model_validate(data)


def test_ranges_and_selectors():
    assert Range(min=0.5, max=0.5).matches(0.5 - 1e-7)
    assert not Range(min=0.5).matches(None)
    assert not Range(max=0.5).matches(0.6)
    assert selector("EXECUTE:finance.*") == ("EXECUTE", "finance.*")
    for value in ("NOT_AN_EVENT", "EXECUTE:invented.action"):
        with pytest.raises(ValueError):
            selector(value)
    with pytest.raises(ValueError):
        Binding(adapter="other", entity="lamp")


def test_ordered_assertions_consume_distinct_rows_and_resolve_actions():
    actions = {"a": SimpleNamespace(action_class="environment.lights")}
    rows = [
        SimpleNamespace(
            seq=1, event_type=EventType.VERIFIED, payload={"action_id": "a"}
        )
    ]
    result = audit_checks(
        ("VERIFIED:environment.lights", "VERIFIED"), rows, actions, ordered=True
    )
    assert [r["status"] for r in result] == ["passed", "failed"]
    assert (
        audit_checks(("VERIFIED:energy.*",), rows, actions, ordered=False)[0]["status"]
        == "passed"
    )
    assert (
        audit_checks(("VERIFIED:environment.*",), rows, actions, ordered=False)[0][
            "status"
        ]
        == "failed"
    )


def test_named_references_are_run_local_and_never_inferred():
    loaded = LoadedScenario(Path("scenarios/demo-evening.yaml"))
    first, second = Host(loaded, AsyncMock()), Host(loaded, AsyncMock())
    first.saved["prior"] = "a"
    call = ScriptCall(
        tool="revise_household_plan",
        arguments={"text": "Set the car to 50%", "replaces": "$prior"},
    )
    with pytest.raises(ValueError, match="Unknown result"):
        asyncio.run(second.call(call, "malik"))
    with pytest.raises(ValueError, match="No plan"):
        asyncio.run(second.current(second.principal("malik")))


def test_committed_execution_scope():
    loaded = LoadedScenario(Path("scenarios/demo-evening.yaml"))
    assert loaded.spec.execution
    assert loaded.execution_policy.version == 7
    assert loaded.spec.execution.ev_needed_by == "+1d 06:30"
    assert len(loaded.spec.execution.responses) == 2
    assert all(b.adapter == "twin" for b in loaded.spec.bindings.values())
    assert not LoadedScenario(Path("scenarios/demo-evening-hourly.yaml")).spec.execution
    assert not LoadedScenario(Path("scenarios/parents-scam-check.yaml")).spec.execution


@pytest.mark.parametrize(
    "step,assertions,bad,startup",
    [
        (False, True, False, False),
        (False, False, False, False),
        (True, True, False, False),
        (False, True, True, False),
        (False, True, False, True),
    ],
)
def test_service_runner_order_pacing_artifacts_and_step(
    tmp_path, monkeypatch, step, assertions, bad, startup
):
    """Mock service seams; verify orchestration, never claim device/audit integration."""
    import json
    from contextlib import asynccontextmanager

    import yaml

    from hirz.twin import execution
    from hirz.twin.adapters import registry as twin_registry

    raw = yaml.safe_load(Path("scenarios/demo-evening.yaml").read_text())
    raw["household"] = str(Path("constitutions/quinn-home.yaml").resolve())
    raw["clock"]["end"] = "2026-10-13T17:32:00-05:00"
    raw["execution"] = {"member": "malik", "rooms": {}}
    raw["timeline"] = [
        {
            "at": "17:31",
            "event": "voice",
            "member": "malik",
            "text": "Read context",
            "script": [{"tool": "get_household_context", "arguments": {}}],
        }
    ]
    raw["assert"] = {
        "checks": [
            {
                "at": "17:31",
                "kind": "observation",
                "subject": "malik",
                "domain": "presence",
                "equals": {"present": not bad},
            }
        ],
        "deferred": [],
    }
    path = tmp_path / "short.yaml"
    path.write_text(yaml.safe_dump(raw))
    loaded = LoadedScenario(path)
    events = []

    @asynccontextmanager
    async def begin():
        yield

    class Result:
        def scalars(self):
            return self

        def mappings(self):
            return self

        def all(self):
            return []

        def __iter__(self):
            return iter(())

    c = SimpleNamespace(
        begin=begin,
        engine=SimpleNamespace(url=SimpleNamespace(database="mock_disposable")),
        execute=AsyncMock(return_value=Result()),
        in_transaction=lambda: False,
    )
    p = SimpleNamespace(
        connection=c,
        household_id=loaded.world.household.id,
        scope=lambda table: True,
        clock=loaded.world.clock,
        boundary=None,
    )

    @asynccontextmanager
    async def disposable(values):
        try:
            yield c
        except BaseException:
            events.append("retain")
            raise
        else:
            events.append("drop")

    monkeypatch.setattr(execution, "disposable", disposable)
    monkeypatch.setattr(execution, "read_env", lambda path: {})
    monkeypatch.setattr(execution, "bootstrap", AsyncMock(return_value=p))
    monkeypatch.setattr(
        execution,
        "compose",
        AsyncMock(return_value=twin_registry(loaded.world, "presence:twin")),
    )
    if startup:
        execution.compose.side_effect = ValueError("Unavailable configured adapter")

    async def ingest(*args):
        events.append("ingest")

    monkeypatch.setattr(execution, "ingest", ingest)

    refresh_times = []

    class Worker:
        def __init__(self, *args, **kwargs):
            self.world = kwargs["world"]
            self.advanced = False

        async def sweep(self, *, endings_only=False):
            from datetime import timedelta

            events.append("endings" if endings_only else "openings")
            if endings_only and not self.advanced:
                self.world.clock.jump(self.world.clock() + timedelta(microseconds=1))
                self.advanced = True
            return ()

        async def batch(self):
            events.append("refresh")
            refresh_times.append(self.world.clock())

    monkeypatch.setattr(execution, "Executor", Worker)
    monkeypatch.setattr(execution, "RefreshWorker", Worker)

    async def call(self, *args):
        events.append("call")
        return {"status": "executed"}

    monkeypatch.setattr(execution.Host, "call", call)
    monkeypatch.setattr(execution.Host, "responses", AsyncMock(return_value=0))

    async def retain(p, folder):
        execution.write_export(folder / "audit.json", {"test_seam": True})
        return {"status": "valid"}, []

    monkeypatch.setattr(execution, "retain_audit", retain)
    delays = []

    async def sleep(seconds):
        delays.append(seconds)

    folder = tmp_path / "private"
    report = asyncio.run(
        execution.run_execution(
            loaded,
            headless=False,
            assertions=assertions,
            speed=None,
            to="17:31" if step else None,
            sleep=sleep,
            progress=lambda text: None,
            artifacts_dir=folder,
            ha_config=None,
        )
    )
    assert report["status"] == (
        "failed"
        if startup or bad and assertions
        else "stopped"
        if step
        else "execution_checks_passed"
        if assertions
        else "completed_unchecked"
    ), report
    assert events[0] == ("retain" if startup else "endings")
    assert events[-1] == ("retain" if startup or bad and assertions else "drop")
    assert ("call" in events) == (not step and not startup)
    if not step and not startup:
        assert (
            events.index("endings") < events.index("refresh") < events.index("openings")
        )
    if not startup:
        assert (refresh_times[0] - loaded.spec.clock.start).total_seconds() == 0.000001
    assert (folder.stat().st_mode & 0o777) == 0o700
    assert ((folder / "report.json").stat().st_mode & 0o777) == 0o600
    assert json.loads((folder / "report.json").read_text()) == report
    if not step:
        replay = LoadedScenario(path)
        p.clock = replay.world.clock
        execution.compose.return_value = twin_registry(replay.world, "presence:twin")
        again = asyncio.run(
            execution.run_execution(
                replay,
                headless=True,
                assertions=assertions,
                speed=None,
                to=None,
                sleep=sleep,
                progress=None,
                artifacts_dir=tmp_path / "headless",
                ha_config=None,
            )
        )
        assert {k: v for k, v in again.items() if k != "artifacts_dir"} == {
            k: v for k, v in report.items() if k != "artifacts_dir"
        }
    with pytest.raises(FileExistsError):
        asyncio.run(
            execution.run_execution(
                loaded,
                headless=True,
                assertions=True,
                speed=None,
                to=None,
                sleep=sleep,
                progress=None,
                artifacts_dir=folder,
                ha_config=None,
            )
        )


def test_scenario_energy_is_published_rates_with_supplied_weather():
    from hirz.twin.scenario_energy import ScenarioEnergy

    loaded = LoadedScenario(Path("scenarios/demo-evening.yaml"))

    async def run():
        adapter = ScenarioEnergy(loaded.world)
        await adapter.start()
        try:
            prices = await adapter.get_prices(
                loaded.spec.clock.start, loaded.spec.clock.end, "day_ahead"
            )
            assert prices.complete and prices.source == "real"
            assert prices.source_label == "real (published ComEd rate)"
            assert prices.source_urls and prices.tariff_version
            assert (
                await adapter.get_weather(
                    loaded.spec.clock.start, loaded.spec.clock.end
                )
            ).source == "twin"
            assert (await adapter.get_tariff_state()).source == "real"
        finally:
            await adapter.close()

    asyncio.run(run())


def test_script_calls_use_services_and_keep_identifiers_local():
    from contextlib import asynccontextmanager
    from uuid import uuid4

    from hirz.graph.repository import row_values

    loaded = LoadedScenario(Path("scenarios/demo-evening.yaml"))

    @asynccontextmanager
    async def begin():
        yield

    snapshot = SimpleNamespace(model_dump=lambda **kwargs: {"scope": "all"})
    p = SimpleNamespace(
        connection=SimpleNamespace(begin=begin),
        clock=loaded.world.clock,
        snapshot=AsyncMock(return_value=snapshot),
    )
    host = Host(loaded, p)
    plan = SimpleNamespace(
        plan_id="plan-one", model_dump=lambda **kwargs: {"plan_id": "plan-one"}
    )
    host.plans.read_current = AsyncMock(return_value=plan)
    decision = SimpleNamespace(
        decision="execute",
        status="executing",
        model_dump=lambda **kwargs: {"decision": "execute"},
    )
    host.plans.approve = AsyncMock(return_value=decision)
    host.plans.cancel = AsyncMock(return_value=decision)
    cid = uuid4()
    host.coordinator.intake = AsyncMock(
        return_value=SimpleNamespace(
            decision=decision,
            constraint_id=cid,
            model_dump=lambda **kwargs: {"constraint_id": str(cid)},
        )
    )
    host.plan_id = "plan-one"
    p.repo = SimpleNamespace(
        get=AsyncMock(
            return_value=row_values(
                "asset_bindings",
                loaded.world.bindings[loaded.ref("assets", "light.living_room")],
            )
        )
    )
    p.enqueue = AsyncMock(return_value=decision)

    async def run():
        assert (
            await host.call(
                ScriptCall(tool="get_household_plan", arguments={}, save_as="plan"),
                "malik",
            )
        )["status"] == "executed"
        assert host.saved["plan"] == "plan-one"
        await host.call(ScriptCall(tool="get_household_context", arguments={}), "malik")
        await host.call(
            ScriptCall(
                tool="revise_household_plan",
                arguments={"text": "Set the car to 50%"},
                save_as="constraint",
            ),
            "malik",
        )
        await host.call(
            ScriptCall(
                tool="revise_household_plan",
                arguments={"text": "Change the car to 40%", "replaces": "$constraint"},
            ),
            "malik",
        )
        assert host.coordinator.intake.call_args.kwargs["replaces"] == cid
        await host.call(
            ScriptCall(tool="approve_action", arguments={"plan": "$plan"}), "malik"
        )
        await host.call(
            ScriptCall(tool="approve_action", arguments={"approved": False}), "malik"
        )
        with pytest.raises(ValueError, match="superseded"):
            await host.call(
                ScriptCall(tool="approve_action", arguments={"plan": "old"}), "malik"
            )
        await host.call(
            ScriptCall(
                tool="execute_household_action",
                arguments={"asset": "light.living_room", "on": True, "duration_s": 2},
                save_as="lamp",
            ),
            "malik",
        )
        action = p.enqueue.call_args.args[0]
        assert action.revert.inverse.params == {"on": False}
        assert action.target.adapter == "twin"
        assert p.enqueue.call_args.args[1].surface == "alexa"
        with pytest.raises(ValueError, match="unique"):
            await host.call(
                ScriptCall(tool="get_household_plan", arguments={}, save_as="plan"),
                "malik",
            )
        host.coordinator.intake.return_value = SimpleNamespace(
            decision=None, constraint_id=None, clarification="Please clarify"
        )
        with pytest.raises(ValueError, match="intake failed"):
            await host.call(
                ScriptCall(
                    tool="revise_household_plan", arguments={"text": "ambiguous"}
                ),
                "malik",
            )
        decision.decision = "deny"
        with pytest.raises(ValueError, match="consent refused"):
            await host.call(ScriptCall(tool="approve_action", arguments={}), "malik")

    asyncio.run(run())


def test_initial_computation_is_separate_from_scripted_calls(monkeypatch):
    from uuid import uuid4

    from hirz.planner.service import plan
    from hirz.twin import execution
    from tests.unit.test_planner import tiny

    loaded = LoadedScenario(Path("scenarios/demo-evening.yaml"))
    host = Host(loaded, SimpleNamespace())
    inputs = tiny()
    result = plan(inputs)
    monkeypatch.setattr(execution, "workload_input", lambda *args, **kwargs: inputs)
    host.coordinator.intake = AsyncMock(
        return_value=SimpleNamespace(constraint_id=uuid4())
    )
    host.coordinator.plan = AsyncMock(
        return_value=SimpleNamespace(
            result=result, inputs=inputs, model_dump_json=lambda: "failed"
        )
    )
    host.plans.record = AsyncMock(return_value=SimpleNamespace(decision="execute"))
    asyncio.run(host.create_plan())
    assert host.plan_id == result.plan.plan_id
    assert host.initial_summary == result.plan.summary.model_dump(mode="json")
    assert "initial_target" in host.saved
    host.plans.record.return_value.decision = "deny"
    with pytest.raises(ValueError, match="publication refused"):
        asyncio.run(host.create_plan())


def test_declared_device_responses_are_visible_once_and_scoped():
    from contextlib import asynccontextmanager

    from hirz.pipeline.models import Action, Requester, Target

    loaded = LoadedScenario(Path("scenarios/demo-evening.yaml"))
    loaded.world.clock.jump(loaded.time("23:10"))
    action = Action.model_validate(
        dict(
            action_id="guest",
            plan_id="plan",
            **{"class": "energy.hvac_adjust"},
            target=Target(adapter="twin", entity="hvac.guest_room"),
            params={"target_f": 72},
            requested_by=Requester(member_id=None, role="unknown", surface="scheduler"),
            reason="Scheduled adjustment",
            content_hash="",
        )
    )
    rows = [
        {"approval_id": "guest-approval", "proposal": action.model_dump(mode="json")},
        {
            "approval_id": "unmatched",
            "proposal": action.model_copy(
                update={"target": Target(adapter="twin", entity="hvac.living_room")}
            ).model_dump(mode="json"),
        },
    ]

    @asynccontextmanager
    async def begin():
        yield

    p = SimpleNamespace(
        clock=loaded.world.clock,
        scope=lambda table: True,
        connection=SimpleNamespace(
            begin=begin,
            execute=AsyncMock(
                return_value=SimpleNamespace(
                    mappings=lambda: SimpleNamespace(all=lambda: rows)
                )
            ),
        ),
    )
    host = Host(loaded, p)
    host.plans.respond_to_action = AsyncMock(
        return_value=SimpleNamespace(model_dump=lambda **kw: {"decision": "execute"})
    )

    async def run():
        assert await host.responses() == 1
        assert await host.responses() == 0

    asyncio.run(run())
    assert host.plans.respond_to_action.await_count == 1
    args = host.plans.respond_to_action.call_args
    assert args.args[:2] == ("plan", "guest-approval")
    assert args.args[2].sub == "malik" and args.args[2].surface == "alexa"
    assert args.kwargs == {"approved": True}
    assert host.turns[0]["text"] == "Yes."


def test_retained_audit_checks_independent_trust_and_corruption(tmp_path, monkeypatch):
    import json

    from cryptography.hazmat.primitives.asymmetric import ec

    from hirz.audit import AuditError
    from hirz.twin import execution

    key = ec.generate_private_key(ec.SECP256R1())
    loaded = LoadedScenario(Path("scenarios/demo-evening.yaml"))
    p = SimpleNamespace(
        connection=object(),
        household_id=loaded.world.household.id,
        audit=SimpleNamespace(key=key),
    )
    monkeypatch.setattr(
        execution, "verify_database", AsyncMock(return_value=({"status": "empty"}, []))
    )
    good = tmp_path / "good"
    good.mkdir()
    result, rows = asyncio.run(execution.retain_audit(p, good))
    assert result["status"] == "empty" and rows == []
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in good.iterdir())
    write = execution.write_export

    def corrupt(path, document):
        write(path, document)
        data = json.loads(path.read_text())
        data["key_fingerprint"] = "0" * 64
        path.write_text(json.dumps(data))

    monkeypatch.setattr(execution, "write_export", corrupt)
    bad = tmp_path / "bad"
    bad.mkdir()
    with pytest.raises(AuditError):
        asyncio.run(execution.retain_audit(p, bad))


def test_overnight_checks_do_not_promote_missing_execution_to_success():
    from contextlib import asynccontextmanager

    from hirz.twin.execution import overnight_checks

    loaded = LoadedScenario(Path("scenarios/demo-evening.yaml"))

    @asynccontextmanager
    async def begin():
        yield

    p = SimpleNamespace(
        clock=loaded.world.clock,
        scope=lambda table: True,
        snapshot=AsyncMock(
            return_value=SimpleNamespace(
                data={
                    "constraints": [
                        {
                            "provenance": {
                                "source": "member:" + str(loaded.ref("members", "dad")),
                                "surface": "alexa",
                                "encoded": {
                                    "kind": "appliance_not_before",
                                    "at": loaded.time("23:00").isoformat(),
                                },
                            }
                        }
                    ]
                }
            )
        ),
        connection=SimpleNamespace(
            begin=begin,
            execute=AsyncMock(return_value=SimpleNamespace(mappings=lambda: [])),
        ),
    )
    host = Host(loaded, p)

    async def observe():
        await loaded.registry.start()
        try:
            return await loaded.observations()
        finally:
            await loaded.registry.close()

    observations = asyncio.run(observe())
    checks = asyncio.run(
        overnight_checks(
            host,
            [
                {
                    "at": loaded.world.clock().isoformat(),
                    "observations": [r.model_dump(mode="json") for r in observations],
                }
            ],
        )
    )
    statuses = {c["expectation"]: c["status"] for c in checks}
    for name in (
        "verified_device_classes",
        "separate_nighttime_votes",
        "completed_current_plan",
        "ev_delivery_and_ceiling",
        "appliance_completed",
        "battery_terminal_preserved",
    ):
        assert statuses[name] == "failed"
    assert statuses["comfort_at_replay_boundaries"] == "passed"
    assert statuses["dad_attribution"] == "passed"
