"""Prediction thresholds, remaining obligations and reservation conservation."""

import asyncio
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from hirz.executor.budget import transfer
from hirz.executor.runtime import (
    IntervalEstimate,
    RuntimeInputs,
    Thresholds,
    deviates,
    predicted,
    slice_input,
)
from hirz.planner.heuristic import baseline
from hirz.planner.replay import replay
from hirz.planner.service import plan
from hirz.twin.physics import Appliance, Battery, changed
from tests.unit.test_coordinator import AT, HOME, workload


def runtime():
    p = workload()
    result = plan(p)
    assert result.plan and result.schedule
    return RuntimeInputs.from_schedule(p, result.schedule), result


@pytest.mark.parametrize(
    "field,base,threshold",
    [("temp_f", 70, 1), ("soc", 0.5, 0.02), ("power_kw", 1, 0.25)],
)
def test_deviation_threshold_is_strict(field, base, threshold):
    assert not deviates({field: base + threshold}, {field: base}, Thresholds())
    assert deviates({field: base + threshold + 0.00001}, {field: base}, Thresholds())
    assert not deviates({field: None}, {field: base}, Thresholds())
    assert deviates({"available": False}, {"available": True}, Thresholds())
    assert deviates({"mode": "cool"}, {"mode": "heat"}, Thresholds())


def test_runtime_requires_complete_evidence_and_preserves_partial_slots():
    r, result = runtime()
    r.validate_plan(result.plan)
    assert sum(e.electricity for e in r.estimates) == pytest.approx(
        Decimal(str(result.plan.summary.electricity_usd))
    )
    partial = slice_input(
        r.workload, AT + timedelta(minutes=5), AT + timedelta(minutes=20)
    )
    assert [s.hours * 60 for s in partial.slots] == [10, 5]
    assert len(partial.zones[0].lower) == 2
    with pytest.raises(ValueError, match="forecasts"):
        slice_input(r.workload, AT - timedelta(seconds=1), AT + timedelta(minutes=5))
    with pytest.raises(ValueError, match="Estimates"):
        RuntimeInputs.model_validate(r.model_dump() | {"estimates": []})
    with pytest.raises(ValueError, match="Prediction"):
        RuntimeInputs.model_validate(
            r.model_dump() | {"prediction": {"method": "greedy", "controls": []}}
        )
    with pytest.raises(ValueError, match="terminal battery"):
        RuntimeInputs.model_validate(
            r.model_dump()
            | {
                "workload": changed(
                    r.workload, battery=Battery(soc=0.5, dispatch_kw=0)
                ).model_dump()
            }
        )
    assert (
        predicted(r, AT)[r.workload.zones[0].entity]["temp_f"]
        == r.workload.zones[0].physical.temp_f
    )
    assert (
        "temp_f" in predicted(r, AT + timedelta(minutes=5))[r.workload.zones[0].entity]
    )
    assert predicted(r, AT + timedelta(days=1)) == predicted(
        r, r.workload.slots[-1].end
    )


def test_running_appliance_finishes_once_and_original_battery_target_survives():
    p = workload()
    appliance = Appliance(
        cycle_minutes=60,
        cycle_kwh=1,
        noise_dba=40,
        running=True,
        elapsed_seconds=1800,
        completions=2,
    )
    p = changed(
        p,
        appliance=appliance,
        battery=Battery(soc=0.4, dispatch_kw=0),
        battery_terminal_kwh=6.75,
    )
    result = plan(p)
    assert result.plan and result.replay and result.schedule
    assert result.replay.appliance_completions == 1
    assert not any(c.appliance_start for c in result.schedule.controls)
    assert result.replay.battery_end_kwh == pytest.approx(6.75, abs=1e-6)
    assert result.replay.electricity_usd > 0
    for method in ("timer", "immediate", "greedy"):
        outcome = replay(p, baseline(p, method))
        assert outcome.appliance_completions == 1


def test_fixed_controls_cannot_be_replaced_and_ev_delivery_is_remaining_only():
    p = workload(ev=True)
    assert p.ev
    p = changed(
        p,
        ev=changed(p.ev, soc=0.45),
        fixed_ev_kwh=(0.1, None, None, None, None, None, None, None),
    )
    result = plan(p)
    assert result.schedule and result.replay
    assert result.schedule.controls[0].ev_kwh == pytest.approx(0.1)
    assert result.replay.ev_delivered_kwh == pytest.approx(
        (p.ev_target - 0.45) * p.ev.capacity_kwh
    )
    changed_schedule = changed(
        result.schedule,
        controls=(
            changed(result.schedule.controls[0], ev_kwh=0),
            *result.schedule.controls[1:],
        ),
    )
    assert "Authorized EV commitment changed" in replay(p, changed_schedule).reasons


@pytest.mark.parametrize("price", ["1", "-1"])
def test_transfer_preserves_elapsed_cost_dates_and_nonnegative_reservations(price):
    async def run():
        r, _ = runtime()
        at = AT + timedelta(minutes=5)
        intervals = tuple(
            IntervalEstimate(
                start=e.start,
                end=e.end,
                electricity=Decimal(price),
                wear=Decimal("0.1"),
            )
            for e in r.estimates
        )
        r = r.model_copy(update={"estimates": intervals})
        p = SimpleNamespace(
            clock=lambda: at,
            household_id=HOME,
            connection=object(),
            audit=SimpleNamespace(append=AsyncMock(return_value=1)),
        )
        old = {
            "plan_id": "previous",
            "reservation": {
                "allocations": [
                    {
                        "start": AT.isoformat(),
                        "end": (AT + timedelta(minutes=15)).isoformat(),
                        "amount": "3",
                        "date": "2026-10-12",
                        "grant": "original",
                    }
                ]
            },
        }
        allocation = await transfer(p, old, r, ())
        assert Decimal(allocation["allocations"][0]["amount"]) == 1
        assert allocation["allocations"][0]["date"] == "2026-10-12"
        assert Decimal(p.audit.append.call_args.args[-1]["delta"]) == -2
        assert all(Decimal(e["amount"]) >= 0 for e in allocation["estimates"])
        if price == "-1":
            assert all(Decimal(e["amount"]) == 0 for e in allocation["estimates"])
        # A subsequent refresh retains the elapsed allocation without releasing it again.
        p.audit.append.reset_mock()
        await transfer(p, {"plan_id": "new", "reservation": allocation}, r, ())
        p.audit.append.assert_not_awaited()

    asyncio.run(run())


async def world_inputs():
    from pathlib import Path

    from hirz.executor.observations import readings
    from hirz.twin.adapters import registry
    from hirz.twin.scenario import LoadedScenario
    from tests.unit.test_coordinator import snapshot

    world = LoadedScenario(Path("scenarios/demo-evening.yaml")).world
    world.clock.jump(AT)
    reg = registry(world, "presence:twin,energy:twin,calendar:twin")
    await reg.start()
    snap = snapshot()
    snap.data["observations"] = [o.model_dump(mode="json") for o in await readings(reg)]
    p = workload(ev=True)
    p = changed(
        p,
        battery=Battery(soc=0.55, dispatch_kw=0),
        appliance=Appliance(cycle_minutes=60, cycle_kwh=1, noise_dba=40, running=False),
    )
    r = RuntimeInputs.from_schedule(p, baseline(p))
    return world, reg, snap, r


def test_rebuild_uses_current_state_and_carries_terminal_obligations():
    from hirz.executor.replanning import outstanding

    async def run():
        world, reg, snap, r = await world_inputs()
        try:
            p, bindings, exhausted = outstanding(
                r, snap, r.workload.requester, (), world.read()[1], {}
            )
            assert p.ev.soc == world.read()[1].evs[world.entity("ev", "ev")].soc
            assert p.battery_terminal_kwh == r.battery_terminal_kwh
            assert bindings["hvac.living_room"]["adapter"] == "twin"
            assert not exhausted
            # Completed work is omitted; a running cycle is carried as a fixed load.
            state = world.read()[1]
            asset = world.entity("dishwasher", "devices")
            state = changed(
                state,
                appliances=state.appliances
                | {
                    asset: changed(
                        state.appliances[asset], running=True, elapsed_seconds=30
                    )
                },
            )
            assert outstanding(r, snap, r.workload.requester, (), state, {})[
                0
            ].appliance.running
            state = changed(
                state,
                appliances=state.appliances
                | {
                    asset: changed(
                        state.appliances[asset],
                        running=False,
                        completions=r.appliance_completions,
                    )
                },
            )
            assert (
                outstanding(r, snap, r.workload.requester, (), state, {})[0].appliance
                is None
            )
        finally:
            await reg.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "failure",
    [
        "missing_binding",
        "unavailable",
        "stale",
        "unplugged",
        "unknown_temperature",
        "unsupported_adapter",
        "unknown_cycle",
        "unsupported_ha",
    ],
)
def test_missing_required_domain_is_held_without_twin_substitution(failure):
    from hirz.executor.replanning import outstanding

    async def run():
        world, reg, snap, r = await world_inputs()
        try:
            zone = str(world.entity("hvac.living_room", "devices"))
            obs = next(
                o for o in snap.data["observations"] if str(o.get("asset_id")) == zone
            )
            binding = next(
                b for b in snap.data["asset_bindings"] if str(b["asset_id"]) == zone
            )
            state = world.read()[1]
            if failure == "missing_binding":
                snap.data["asset_bindings"].remove(binding)
            elif failure == "unavailable":
                obs["state"]["available"] = False
            elif failure == "stale":
                obs["observed_at"] = (AT - timedelta(seconds=301)).isoformat()
            elif failure == "unplugged":
                next(o for o in snap.data["observations"] if o.get("domain") == "ev")[
                    "state"
                ]["plugged_in"] = False
            elif failure == "unknown_temperature":
                obs["state"]["temp_f"] = None
            elif failure == "unsupported_adapter":
                binding["adapter"] = "missing"
            elif failure == "unknown_cycle":
                state = None
            else:
                binding["adapter"] = "ha"
            with pytest.raises(ValueError):
                outstanding(r, snap, r.workload.requester, (), state, {})
        finally:
            await reg.close()

    asyncio.run(run())


def test_commitment_boundaries_and_exhausted_operation_survive_new_ids():
    from hirz.executor.replanning import bind_result, operation, outstanding
    from hirz.pipeline.hashing import action_hash
    from hirz.pipeline.models import Action, ExpectedEffect, Inverse, Revert, Target

    async def run():
        world, reg, snap, r = await world_inputs()
        try:
            target = Target(adapter="twin", entity="ev")
            action = Action.model_validate(
                dict(
                    action_id="old",
                    **{"class": "energy.ev_charge"},
                    target=target,
                    params={"charging": True, "charge_limit": 0.5},
                    requested_by=r.workload.requester,
                    reason="fixture",
                    plan_id="old-plan",
                    scheduled_for=AT - timedelta(minutes=5),
                    content_hash="",
                    expected_effect=ExpectedEffect(
                        entity="ev",
                        attr="charging",
                        value=True,
                        by=AT + timedelta(minutes=10),
                    ),
                    revert=Revert(
                        after_s=1200,
                        inverse=Inverse.model_validate(
                            {
                                "class": "energy.ev_charge",
                                "target": target,
                                "params": {"charging": False},
                            }
                        ),
                    ),
                )
            )
            action = changed(action, content_hash=action_hash(action))
            stored = dict(
                action_id="old",
                proposal=action.model_dump(mode="json", by_alias=True),
                lifecycle={},
                execution_status="verified",
                execution_attempt_seq=1,
            )
            p, bindings, exhausted = outstanding(
                r, snap, r.workload.requester, (stored,), world.read()[1], {}
            )
            assert p.slots[0].end == AT + timedelta(minutes=15)
            assert p.fixed_ev_kwh[0] is not None
            stored["execution_status"] = "dispatched"
            with pytest.raises(ValueError, match="uncertain"):
                outstanding(
                    r, snap, r.workload.requester, (stored,), world.read()[1], {}
                )
            stored.update(execution_status="failed", execution_attempt_seq=None)
            assert (
                operation(action)
                in outstanding(
                    r, snap, r.workload.requester, (stored,), world.read()[1], {}
                )[2]
            )
            permitted = changed(r, retry_actions=("old",))
            assert not outstanding(
                permitted, snap, r.workload.requester, (stored,), world.read()[1], {}
            )[2]
            simple, result = runtime()
            mapped = bind_result(result, simple.workload, result.plan, bindings, ())
            assert mapped.actions[0].target.zone
            with pytest.raises(ValueError, match="exhausted"):
                bind_result(
                    result,
                    simple.workload,
                    result.plan,
                    bindings,
                    (operation(mapped.actions[0]),),
                )
        finally:
            await reg.close()

    asyncio.run(run())


def test_adapter_feed_changes_ignore_duplicate_and_timestamp_only_reads():
    from hirz.executor.refresh_worker import RefreshWorker
    from hirz.twin.environment import Weather
    from scripts.smoke_executor import PRINCIPAL

    async def run():
        world, reg, snap, r = await world_inputs()
        try:
            p = SimpleNamespace(clock=world.clock)
            worker = RefreshWorker(p, reg, world=world)
            worker.service.command = AsyncMock()
            stored = {"plan_id": "fixture", "runtime": r.model_dump(mode="json")}
            await worker.poll_inputs(stored, PRINCIPAL)
            first = worker.service.command.call_args.args[1]
            assert first["baseline"] is True
            stored["runtime"] = first["runtime"]
            worker.service.command.reset_mock()
            await worker.poll_inputs(stored, PRINCIPAL)
            worker.service.command.assert_not_awaited()
            weather = world.config.weather.model_dump()
            # Changing supplied weather changes values, rather than retrieval timestamps.
            for sample in weather["samples"]:
                sample["temp_f"] += 2
            world.config = changed(
                world.config, weather=Weather.model_validate(weather)
            )
            await worker.poll_inputs(stored, PRINCIPAL)
            update = worker.service.command.call_args.args[1]
            assert update["baseline"] is False
            RuntimeInputs.model_validate(update["runtime"])
            assert (
                update["runtime"]["workload"]["slots"][0]["outdoor_f"]
                != r.workload.slots[0].outdoor_f
            )
        finally:
            await reg.close()

    asyncio.run(run())


def test_fingerprints_ignore_tariff_and_window_crossings_but_detect_changes(
    monkeypatch,
):
    import hirz.executor.refresh as module
    from tests.unit.test_coordinator import POLICY, add, requirement

    monkeypatch.setattr(module, "applied_controls", AsyncMock(return_value=()))

    async def run():
        world, reg, snap, r = await world_inputs()
        try:
            hold = requirement("prefer living room at 72 F", snap=snap)
            snap = add(snap, hold)
            p = SimpleNamespace(
                clock=lambda: snap.as_of,
                snapshot=AsyncMock(side_effect=lambda _: snap),
                bundle=SimpleNamespace(policy=lambda: POLICY),
                repo=SimpleNamespace(_at=AT, _revision=1),
                _refresh_fingerprint=None,
            )
            stored = {"runtime": r.model_dump(mode="json")}
            first = await module.fingerprint(p, stored)
            cached = p._refresh_fingerprint
            repeated = await module.fingerprint(p, stored)
            assert repeated == first and p._refresh_fingerprint is cached
            assert module.applied_controls.await_count == 2
            repeated["samples"].clear()
            assert await module.fingerprint(p, stored) == first
            p.repo._revision += 1
            assert await module.fingerprint(p, stored) == first
            assert p._refresh_fingerprint is not cached
            p.repo._at = None
            assert await module.fingerprint(p, stored) == first
            p.repo._at = AT
            # Poll timestamps alone do not invalidate physical predictions.
            for o in snap.data["observations"]:
                if o.get("member_id"):
                    o["observed_at"] = (AT + timedelta(seconds=1)).isoformat()
            assert await module.fingerprint(p, stored) == first
            presence = next(o for o in snap.data["observations"] if o.get("member_id"))
            presence["state"]["present"] = not presence["state"]["present"]
            second = await module.fingerprint(p, stored)
            assert second["samples"] != first["samples"]
            snap = changed(snap, as_of=hold.spec.ends_at)
            expired = await module.fingerprint(p, stored)
            assert expired == second
            energy = next(
                o for o in snap.data["observations"] if o["state"].get("price_band")
            )
            energy["state"]["price_band"] = "another known tariff period"
            assert await module.fingerprint(p, stored) == expired
            p.bundle.policy = lambda: changed(POLICY, version=POLICY.version + 1)
            # Policy content and runtime thresholds are separate durable inputs.
            assert (await module.fingerprint(p, stored))["policy"] != expired["policy"]
            stored["runtime"]["thresholds"] = {"asset": {"temp_f": 2}}
            assert (await module.fingerprint(p, stored))["inputs"] != expired["inputs"]
        finally:
            await reg.close()

    asyncio.run(run())


def test_job_queue_coalesces_and_holds_in_one_mutation(monkeypatch):
    import hirz.executor.plans as plans
    import hirz.executor.refresh as module

    async def run():
        p = SimpleNamespace(
            connection=SimpleNamespace(execute=AsyncMock()), scope=lambda _: True
        )
        stored = {"plan_id": "old", "document": {"status": "approved"}}
        current = None
        monkeypatch.setattr(module, "job", AsyncMock(side_effect=lambda *_: current))
        saved = AsyncMock()
        held = AsyncMock()
        monkeypatch.setattr(module, "save", saved)
        monkeypatch.setattr(plans, "stop_unstarted", held)
        await module.queue(p, stored, "price", fingerprint={"price": 1})
        values = saved.call_args.args[2]
        assert values["requested_generation"] == 1 and values["state"] == "queued"
        assert not values["explicit"]
        held.assert_awaited_once()
        current = values
        saved.reset_mock()
        await module.queue(p, stored, "price", fingerprint={"price": 1})
        saved.assert_not_awaited()
        await module.queue(p, stored, "change", explicit=True)
        assert saved.call_args.args[2]["explicit"]
        assert saved.call_args.args[2]["requested_generation"] == 2
        stored["document"]["status"] = "abandoned"
        saved.reset_mock()
        await module.queue(p, stored, "weather")
        saved.assert_not_awaited()

    asyncio.run(run())


def test_change_detection_blocks_legacy_and_authority_without_age_churn(monkeypatch):
    import hirz.executor.refresh as module

    async def run():
        p = SimpleNamespace(clock=lambda: AT, snapshot=AsyncMock())
        p.snapshot.return_value = SimpleNamespace(data={"observations": []})
        stored = {"runtime": {}, "accepted_at": AT, "document": {"status": "approved"}}
        current = {"state": "idle", "fingerprint": {"v": 1}}
        monkeypatch.setattr(module, "job", AsyncMock(side_effect=lambda *_: current))
        monkeypatch.setattr(module, "fingerprint", AsyncMock(return_value={"v": 1}))
        monkeypatch.setattr(module, "queue", AsyncMock())
        monkeypatch.setattr(module, "save", AsyncMock())
        await module.detect(p, stored)
        module.queue.assert_not_awaited()
        stored["runtime"] = {"present": True}
        assert await module.fresh(p, stored)
        for age in (timedelta(minutes=5), timedelta(hours=12)):
            stored["accepted_at"] = AT - age
            assert await module.fresh(p, stored)
            await module.detect(p, stored)
            module.queue.assert_not_awaited()
            module.save.assert_not_awaited()
        for state in ("queued", "running", "blocked"):
            current["state"] = state
            assert not await module.fresh(p, stored)
        stored["runtime"] = None
        current["state"] = "blocked"
        module.queue.reset_mock()
        await module.detect(p, stored)
        module.queue.assert_not_awaited()
        current["fingerprint"] = {"v": 0}
        await module.detect(p, stored)
        assert "Complete runtime" in module.queue.call_args.args[2]
        stored["runtime"] = {"present": True}
        current["state"] = "idle"
        assert not await module.fresh(p, stored)
        await module.detect(p, stored)
        assert "changed" in module.queue.call_args.args[2]
        current = None
        stored["accepted_at"] = AT
        await module.detect(p, stored)
        module.save.assert_awaited()
        stored["document"]["status"] = "completed"
        module.queue.reset_mock()
        await module.detect(p, stored)
        module.queue.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize(
    "mode,step,features",
    [
        ("heat", 0.5, 1),
        ("cool", None, 1),
        ("off", 1, 1),
        ("heat", 0, 1),
        ("heat", 1, 0),
    ],
)
def test_ha_facts_use_observed_mode_limits_and_optional_increment(mode, step, features):
    from unittest.mock import Mock

    from hirz.adapters.devices.ha import HomeAssistant
    from hirz.executor.refresh_worker import RefreshWorker

    async def run():
        adapter = Mock(spec=HomeAssistant)
        adapter.temperature_unit = AsyncMock(return_value="°C")
        adapter.raw_state = AsyncMock(
            return_value={
                "state": mode,
                "attributes": {
                    "min_temp": 15,
                    "max_temp": 30,
                    "target_temp_step": step,
                    "supported_features": features,
                },
            }
        )
        registry = SimpleNamespace(
            instances={("devices", "ha"): adapter},
            bindings={1: SimpleNamespace(adapter="ha", entity_id="climate.living")},
        )
        worker = RefreshWorker(SimpleNamespace(), registry)
        if mode == "off" or step == 0 or not features:
            with pytest.raises(ValueError):
                await worker.ha_facts()
        else:
            facts = (await worker.ha_facts())["climate.living"]
            assert facts == dict(
                mode=mode, low=59, high=86, step=0.9 if step else None, origin=32
            )
        adapter.raw_state.reset_mock()
        assert await worker.ha_facts({"another"}) == {}
        adapter.raw_state.assert_not_awaited()

    asyncio.run(run())


def test_blocked_read_labels_history_and_never_rewrites_saved_plan(monkeypatch):
    from contextlib import asynccontextmanager

    import hirz.executor.plans as plans
    import hirz.executor.refresh as module
    from scripts.smoke_executor import PRINCIPAL
    from tests.unit.test_pipeline import snapshot as graph_snapshot

    @asynccontextmanager
    async def transaction():
        yield

    async def run():
        r, result = runtime()
        stored = {
            "plan_id": result.plan.plan_id,
            "document": result.plan.model_dump(mode="json"),
        }
        snapshot = result.plan.model_dump(mode="json")
        current = {
            "plan_id": result.plan.plan_id,
            "state": "blocked",
            "blocking_reason": "The supplied forecast ends too soon.",
        }
        p = SimpleNamespace(
            connection=SimpleNamespace(begin=transaction),
            requester=AsyncMock(return_value=r.workload.requester),
            snapshot=AsyncMock(return_value=graph_snapshot()),
            clock=lambda: AT,
        )
        monkeypatch.setattr(plans, "get", AsyncMock(return_value=stored))
        monkeypatch.setattr(module, "job", AsyncMock(return_value=current))
        service = module.RefreshService(p)
        service.command = AsyncMock()
        held = await service.read(result.plan.plan_id, PRINCIPAL)
        assert held.summary.estimated_savings_usd is None
        assert held.summary.peak_kwh_avoided is None
        assert not held.comparison_validity.valid
        assert all(
            not a.validity.valid and a.cost_delta_usd is None for a in held.alternatives
        )
        assert "historical" in str(held.speakable).lower()
        assert "forecast" in held.speakable["details"][1]
        assert stored["document"] == snapshot
        current["state"] = "idle"
        assert await service.read(result.plan.plan_id, PRINCIPAL) == result.plan
        p.requester.return_value = SimpleNamespace(member_id=None)
        with pytest.raises(ValueError, match="linked"):
            await service.read(result.plan.plan_id, PRINCIPAL)

    asyncio.run(run())


def test_runtime_rejects_dropped_domains_and_invalid_costs():
    r, _ = runtime()
    with pytest.raises(ValueError, match="required domains"):
        changed(r, workload=changed(r.workload, zones=())).preserves(r)
    r.preserves(r)
    for electricity, wear in (("NaN", "0"), ("1", "-1"), ("1", "Infinity")):
        with pytest.raises(ValueError):
            IntervalEstimate(
                start=AT,
                end=AT + timedelta(minutes=15),
                electricity=Decimal(electricity),
                wear=Decimal(wear),
            )


@pytest.mark.parametrize("status", ["dispatched", "failed", "verified"])
def test_uncertain_dispatch_and_bounded_commitments_keep_original_grant_date(status):
    from hirz.pipeline.models import Action, ExpectedEffect, Inverse, Revert, Target

    async def run():
        r, result = runtime()
        target = Target(adapter="twin", entity="ev")
        a = Action.model_validate(
            dict(
                action_id="commitment",
                **{"class": "energy.ev_charge"},
                target=target,
                params={"charging": True},
                reason="fixture",
                requested_by=r.workload.requester,
                scheduled_for=AT,
                expected_effect=ExpectedEffect(
                    entity="ev",
                    attr="charging",
                    value=True,
                    by=AT + timedelta(minutes=1),
                ),
                revert=Revert(
                    after_s=900,
                    inverse=Inverse.model_validate(
                        {
                            "class": "energy.ev_charge",
                            "target": target,
                            "params": {"charging": False},
                        }
                    ),
                ),
                content_hash="",
            )
        )
        action = dict(
            proposal=a.model_dump(mode="json", by_alias=True),
            action_id=a.action_id,
            lifecycle={},
            execution_attempt_seq=1,
            execution_status=status,
        )
        p = SimpleNamespace(
            clock=lambda: AT + timedelta(minutes=1),
            household_id=HOME,
            connection=object(),
            audit=SimpleNamespace(append=AsyncMock(return_value=1)),
        )
        allocations = [
            dict(
                start=e.start.isoformat(),
                end=e.end.isoformat(),
                amount="1",
                grant="before-midnight",
                date="2026-10-12",
            )
            for e in r.estimates
        ]
        transferred = await transfer(
            p,
            {"plan_id": "old", "reservation": {"allocations": allocations}},
            r,
            (action,),
        )
        retained = transferred["allocations"]
        assert all(e["date"] == "2026-10-12" for e in retained)
        if status != "verified":
            assert retained == allocations
            p.audit.append.assert_not_awaited()
        else:
            assert len(retained) == 1
            assert retained[0]["end"] == (AT + timedelta(minutes=15)).isoformat()
            assert p.audit.append.call_args.args[-1]["local_date"] == "2026-10-12"
        assert all(Decimal(e["amount"]) >= 0 for e in transferred["estimates"])

    asyncio.run(run())


def test_recorded_ha_changes_need_matching_dispatch_and_unchanged_mode(tmp_path):
    from hirz.executor.refresh import owned_control
    from tests.unit.test_ha import Recorded, adapter

    async def run():
        recorded = Recorded()
        ha = adapter(tmp_path, recorded)
        await ha.start()
        try:
            first = await ha.get_state("climate.demo")
            recorded.states["climate.demo"]["attributes"]["temperature"] = 72
            observed = await ha.get_state("climate.demo")
            assert (
                observed.observed_at == first.observed_at
            )  # upstream timestamp preserved
            binding = {"attributes": {"adapter": "ha", "entity_id": "climate.demo"}}
            rows = [
                {
                    "created_at": observed.observed_at,
                    "proposal": {
                        "class": "energy.hvac_adjust",
                        "target": {"adapter": "ha", "entity": "climate.demo"},
                        "params": {"target_f": 72},
                    },
                }
            ]
            p = SimpleNamespace(
                scope=lambda _: True, connection=SimpleNamespace(execute=AsyncMock())
            )

            def query(_):
                if "asset_bindings" in str(_):
                    return SimpleNamespace(
                        mappings=lambda: SimpleNamespace(one_or_none=lambda: binding)
                    )
                return SimpleNamespace(
                    mappings=lambda: SimpleNamespace(all=lambda: rows)
                )

            p.connection.execute.side_effect = query
            assert await owned_control(
                p, observed, since=first.observed_at, previous_mode="heat"
            )
            recorded.states["climate.demo"]["state"] = "cool"
            assert not await owned_control(
                p,
                await ha.get_state("climate.demo"),
                since=first.observed_at,
                previous_mode="heat",
            )
            recorded.states["climate.demo"]["state"] = "heat"
            recorded.states["climate.demo"]["attributes"]["temperature"] = 73
            assert not await owned_control(
                p, await ha.get_state("climate.demo"), previous_mode="heat"
            )
            rows[0]["created_at"] = first.observed_at - timedelta(seconds=1)
            assert not await owned_control(
                p, observed, since=first.observed_at, previous_mode="heat"
            )
            rows[0]["proposal"]["target"]["entity"] = "climate.other"
            assert not await owned_control(p, observed)
            binding = None
            assert not await owned_control(p, observed)
            from uuid import uuid4

            from hirz.executor.refresh import compensate_owned_controls

            later = observed.model_copy(
                update={
                    "id": uuid4(),
                    "asset_id": uuid4(),
                    "observed_at": observed.observed_at + timedelta(seconds=2),
                }
            )
            observations = (observed, later)
            bindings = [
                {"asset_id": str(o.asset_id), "adapter": "ha", "entity_id": entity}
                for o, entity in zip(
                    observations, ("climate.demo", "climate.other"), strict=True
                )
            ]
            rows = [
                {
                    "created_at": observed.observed_at + timedelta(seconds=1),
                    "proposal": {
                        "class": "energy.hvac_adjust",
                        "target": {"adapter": "ha", "entity": b["entity_id"]},
                        "params": {"target_f": 72},
                    },
                }
                for b in bindings
            ]
            p.snapshot = AsyncMock(
                return_value=SimpleNamespace(
                    data={
                        "observations": [
                            o.model_dump(mode="json") for o in observations
                        ],
                        "asset_bindings": bindings,
                    }
                )
            )
            p.clock = lambda: later.observed_at
            previous = {
                "samples": {
                    str(o.asset_id): {"mode": "heat", "target_f": 68}
                    for o in observations
                }
            }
            current = {
                "samples": {
                    str(o.asset_id): {"mode": "heat", "target_f": 72}
                    for o in observations
                }
            }
            p.connection.execute.reset_mock()
            await compensate_owned_controls(p, previous, current)
            assert previous["samples"][str(observed.asset_id)]["target_f"] == 68
            assert previous["samples"][str(later.asset_id)]["target_f"] == 72
            p.connection.execute.assert_awaited_once()
        finally:
            await ha.close()

    asyncio.run(run())


def test_partial_ev_prediction_keeps_the_full_slot_charge_ceiling():
    from hirz.planner.models import Control, Schedule
    from hirz.twin.physics import EV

    p = workload()
    ev = EV(soc=0.34, plugged_in=True, charging=False, charge_limit=0.8)
    p = changed(p, ev=ev)
    controls = tuple(
        Control(
            targets=(72,) * len(p.zones),
            modes=("heat",) * len(p.zones),
            ev_kwh=1 if i == 0 else 0,
            battery_kw=0,
            appliance_start=False,
        )
        for i in range(len(p.slots))
    )
    r = RuntimeInputs.from_schedule(p, Schedule(method="greedy", controls=controls))
    actual = changed(
        ev, charging=True, charge_limit=ev.soc + ev.efficiency / ev.capacity_kwh
    ).advance(1)
    expected = predicted(r, p.slots[0].start + timedelta(seconds=1))["ev"]
    assert expected["soc"] == pytest.approx(actual.soc)
    assert expected["power_kw"] == actual.power_kw > 0
    assert not deviates(
        {"soc": actual.soc, "power_kw": actual.power_kw}, expected, Thresholds()
    )


def test_prediction_uses_applied_controls_and_keeps_them_until_verified_change():
    from hirz.pipeline.models import Target
    from hirz.twin.physics import EV

    r, result = runtime()
    p = changed(
        r.workload,
        ev=EV(soc=0.34, plugged_in=True, charging=False, charge_limit=0.8),
        battery=Battery(soc=0.5, dispatch_kw=0),
        appliance=Appliance(cycle_minutes=10, cycle_kwh=1, noise_dba=40, running=False),
    )
    r = r.model_copy(update={"workload": p})
    template = result.actions[0]

    def command(entity, kind, params):
        return template.model_copy(
            update={
                "target": Target(adapter="twin", entity=entity),
                "action_class": kind,
                "params": params,
                # Scheduled time never supplies the applied time.
                "scheduled_for": AT,
            }
        )

    start = AT + timedelta(minutes=5)
    opening = (
        (
            start,
            command("ev", "energy.ev_charge", {"charging": True, "charge_limit": 0.5}),
        ),
        (start, command("home_battery", "energy.battery_dispatch", {"dispatch_kw": 2})),
        (start, command("dishwasher", "energy.appliance_start", {})),
        (
            start,
            command(
                "hvac.living_room",
                "energy.hvac_adjust",
                {"mode": "heat", "target_f": 72},
            ),
        ),
    )
    before = predicted(r, start - timedelta(microseconds=1), applied=opening)
    assert (
        predicted(r, AT - timedelta(microseconds=1), applied=((AT, opening[0][1]),))[
            "ev"
        ]["power_kw"]
        == 0
    )
    assert before["ev"]["soc"] == 0.34 and before["ev"]["power_kw"] == 0
    assert before["home_battery"]["soc"] == 0.5
    assert before["hvac.living_room"]["mode"] == "off"
    assert not before["dishwasher"]["on"]
    simultaneous = predicted(r, start, applied=opening)
    assert simultaneous["ev"]["power_kw"] == 0
    assert not simultaneous["ev"]["charging"]
    later = predicted(r, start + timedelta(microseconds=1), applied=opening)
    assert later["ev"]["power_kw"] == p.ev.charger_kw
    assert later["ev"]["charging"]
    at = start + timedelta(minutes=5)
    actual = predicted(r, at, applied=opening)
    assert actual["ev"]["soc"] == pytest.approx(
        p.ev.model_copy(update=opening[0][1].params).advance(300).soc
    )
    assert actual["home_battery"]["soc"] == pytest.approx(
        p.battery.model_copy(update={"dispatch_kw": 2}).advance(300).soc
    )
    assert actual["hvac.living_room"]["temp_f"] > before["hvac.living_room"]["temp_f"]
    assert actual["dishwasher"]["on"]
    ending = (
        at,
        command("home_battery", "energy.battery_dispatch", {"dispatch_kw": 0}),
    )
    stopped = predicted(r, at + timedelta(minutes=20), applied=(*opening, ending))
    assert stopped["home_battery"]["soc"] == actual["home_battery"]["soc"]
    assert not stopped["dishwasher"]["on"] and stopped["dishwasher"]["power_kw"] == 0
    assert (
        predicted(r, at + timedelta(minutes=20), applied=opening)["home_battery"]["soc"]
        < stopped["home_battery"]["soc"]
    )


def test_ev_limit_adjacent_power_is_expected_without_hiding_soc_drift(monkeypatch):
    import hirz.executor.refresh as module
    from hirz.pipeline.models import Target
    from tests.unit.test_coordinator import POLICY

    async def run():
        world, reg, snap, r = await world_inputs()
        try:
            p = SimpleNamespace(
                clock=lambda: snap.as_of,
                snapshot=AsyncMock(side_effect=lambda _: snap),
                bundle=SimpleNamespace(policy=lambda: POLICY),
                repo=SimpleNamespace(_at=AT, _revision=1),
                _refresh_fingerprint=None,
            )
            _, result = runtime()
            action = result.actions[0].model_copy(
                update={
                    "target": Target(adapter="twin", entity="ev"),
                    "action_class": "energy.ev_charge",
                    "params": {"charging": True, "charge_limit": 0.5},
                }
            )
            monkeypatch.setattr(
                module,
                "applied_controls",
                AsyncMock(return_value=((snap.as_of, action),)),
            )
            monkeypatch.setattr(
                module,
                "predicted",
                lambda *args, **kwargs: {"ev": {"soc": 0.5, "power_kw": 0}},
            )
            o = next(o for o in snap.data["observations"] if o["domain"] == "ev")
            key = str(o["asset_id"])
            stored = {"runtime": r.model_dump(mode="json")}
            for power in (0, 7.4):
                o["state"].update(soc=0.4999, power_kw=power)
                assert (
                    "deviation"
                    not in (await module.fingerprint(p, stored))["samples"][key]
                )
            o["state"].update(soc=0.4998, power_kw=7.4)
            assert "deviation" in (await module.fingerprint(p, stored))["samples"][key]
            o["state"].update(soc=0.47, power_kw=0)
            assert "deviation" in (await module.fingerprint(p, stored))["samples"][key]
            o["state"].update(soc=0.4999, power_kw=7.4)
            assert (
                "deviation" not in (await module.fingerprint(p, stored))["samples"][key]
            )
            action.params["charging"] = 1
            assert "deviation" in (await module.fingerprint(p, stored))["samples"][key]
            action.params["charging"] = True
            assert (
                "deviation" not in (await module.fingerprint(p, stored))["samples"][key]
            )
            action.params["charge_limit"] = 0.6
            assert "deviation" in (await module.fingerprint(p, stored))["samples"][key]
        finally:
            await reg.close()

    asyncio.run(run())


def test_skipped_opening_keeps_status_but_pending_approval_still_expires(monkeypatch):
    import hirz.executor.plans as module
    from hirz.pipeline.models import EventType

    async def run():
        approval = {"approval_id": "vote", "action_id": "missed"}
        results = [
            SimpleNamespace(
                mappings=lambda: SimpleNamespace(
                    all=lambda: [{"action_id": "missed", "execution_status": "skipped"}]
                )
            ),
            SimpleNamespace(scalars=lambda: [approval["approval_id"]]),
            None,
        ]
        p = SimpleNamespace(
            connection=SimpleNamespace(execute=AsyncMock(side_effect=results)),
            scope=lambda _: True,
            clock=lambda: AT,
            household_id=HOME,
            audit=SimpleNamespace(append_many=AsyncMock()),
        )
        transition = AsyncMock()
        monkeypatch.setattr(module, "transition", transition)
        await module.stop_unstarted(p, "plan", EventType.PLAN_REVISED, "cancelled")
        transition.assert_not_awaited()
        assert p.audit.append_many.call_args.args[2] == (
            (AT, EventType.EXPIRED, {"approval_id": "vote", "reason": "PLAN_REVISED"}),
        )
        update = p.connection.execute.call_args.args[0].compile()
        assert update.params["status"] == "expired"

    asyncio.run(run())
