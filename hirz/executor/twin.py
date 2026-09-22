"""Twin command state and checkpoints share the audited execution transaction."""

from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from hirz import db
from hirz.audit import Verification
from hirz.executor.contracts import SUPPORTED, validate
from hirz.executor.storage import transition
from hirz.pipeline.hashing import digest
from hirz.pipeline.models import Action, Decision, EventType
from hirz.twin.clock import SimClock
from hirz.twin.physics import changed
from hirz.twin.world import State, TwinWorld

if TYPE_CHECKING:
    from hirz.pipeline.service import Pipeline


def configuration(world: TwinWorld) -> str:
    return digest(
        {
            "config": world.config.model_dump(mode="json"),
            "assets": [a.model_dump(mode="json") for a in world.assets.values()],
            "bindings": [b.model_dump(mode="json") for b in world.bindings.values()],
        }
    )


async def restore(p: "Pipeline", world: TwinWorld) -> None:
    async with p.connection.begin():
        row = (
            (
                await p.connection.execute(
                    sa.select(db.twin_checkpoints).where(p.scope(db.twin_checkpoints))
                )
            )
            .mappings()
            .one_or_none()
        )
    if row:
        async with p.connection.begin():
            evidence = dict(
                (
                    await p.connection.execute(
                        sa.select(db.audit_log).where(
                            p.scope(db.audit_log),
                            db.audit_log.c.seq == row["audit_seq"],
                        )
                    )
                )
                .mappings()
                .one()
            )
        Verification(p.household_id, p.audit.key.public_key()).feed(evidence)
        if evidence["event_type"] != EventType.TWIN_CHECKPOINT or evidence[
            "payload"
        ].get("checkpoint_hash") != digest(
            {"config_hash": row["config_hash"], "state": row["state"], "at": row["at"]}
        ):
            raise ValueError("Twin checkpoint does not match its signed evidence")
        if row["config_hash"] != configuration(world):
            raise ValueError("Twin configuration differs from its committed checkpoint")
        world._state = State.model_validate(row["state"])
        world._at = world._last_read = row["at"]
        world.clock = SimClock(row["at"], world.clock._speed, timer=world.clock._timer)


async def checkpoint(p: "Pipeline", world: TwinWorld, state: State, seq: int) -> None:
    payload = dict(
        config_hash=configuration(world),
        state=state.model_dump(mode="json"),
        at=world._last_read,
    )
    seq = await p.audit.append(
        p.connection,
        p.household_id,
        p.clock(),
        EventType.TWIN_CHECKPOINT,
        {"effect_seq": seq, "checkpoint_hash": digest(payload)},
    )
    values = dict(household_id=p.household_id, **payload, audit_seq=seq)
    await p.connection.execute(
        insert(db.twin_checkpoints)
        .values(**values)
        .on_conflict_do_update(
            index_elements=[db.twin_checkpoints.c.household_id], set_=values
        )
    )


def state(world: TwinWorld, action: Action) -> dict[str, Any]:
    _, current = world.read()
    ident = world.entity(action.target.entity, SUPPORTED[action.action_class][0])  # type: ignore[arg-type]
    if ident in current.zones:
        return current.zones[ident].model_dump()
    if ident in current.evs:
        return current.evs[ident].model_dump()
    if ident in current.batteries:
        return current.batteries[ident].model_dump()
    if ident in current.appliances:
        return {"on": current.appliances[ident].running}
    return current.devices[ident].state.model_dump()


def effect(world: TwinWorld, action: Action) -> State:
    validate(action)
    _, current = world.read()
    ident = world.entity(action.target.entity, SUPPORTED[action.action_class][0])  # type: ignore[arg-type]
    if action.action_class == "energy.hvac_adjust":
        return changed(
            current,
            zones=current.zones
            | {ident: changed(current.zones[ident], **action.params)},
        )
    if action.action_class == "energy.ev_charge":
        if not current.evs[ident].plugged_in:
            raise ValueError("EV unavailable; it is unplugged")
        return changed(
            current,
            evs=current.evs | {ident: changed(current.evs[ident], **action.params)},
        )
    if action.action_class == "energy.battery_dispatch":
        if abs(float(action.params["dispatch_kw"])) > current.batteries[ident].power_kw:  # type: ignore[arg-type]
            raise ValueError("Battery command exceeds installed power")
        return changed(
            current,
            batteries=current.batteries
            | {ident: changed(current.batteries[ident], **action.params)},
        )
    if action.action_class == "energy.appliance_start":
        return changed(
            current,
            appliances=current.appliances
            | {ident: current.appliances[ident].start_cycle()},
        )
    device = current.devices[ident]
    if device.state.available is not True:
        raise ValueError("Twin device unavailable")
    return changed(
        current,
        devices=current.devices
        | {ident: changed(device, state=changed(device.state, **action.params))},
    )


async def execute(
    p: "Pipeline", world: TwinWorld, action: Action, decision: Decision
) -> None:
    candidate = effect(world, action)
    attempt = await p.claim_execution(action, decision)
    async with p.repo.write(p.clock):
        seq = await transition(
            p,
            action.action_id,
            "dispatched",
            EventType.EXECUTED,
            execution_attempt_seq=attempt,
            source="twin",
        )
        await checkpoint(p, world, candidate, seq)
    # Publish only the state whose signed effect and checkpoint actually committed.
    world._state, world._at = candidate, world._last_read
    actual = state(world, action)
    matched = all(actual.get(k) == v for k, v in action.params.items())
    if action.action_class == "energy.appliance_start":
        matched = actual["on"] is True
    await p.execution_outcome(
        action, attempt, EventType.VERIFIED if matched else EventType.VERIFY_FAILED
    )
