"""Trusted Registry reads and audited graph ingestion; no caller-supplied readings."""

from typing import TYPE_CHECKING, Any
from uuid import uuid5

import sqlalchemy as sa

from hirz import db
from hirz.adapters.registry import Registry
from hirz.executor.plans import governance
from hirz.graph.models import ASSET_DOMAINS, Observation
from hirz.pipeline.hashing import digest
from hirz.pipeline.models import Action, Decision, EventType, Principal

if TYPE_CHECKING:
    from hirz.pipeline.service import Pipeline


async def readings(registry: Registry) -> tuple[Observation, ...]:
    result = []
    for asset_id, binding in registry.bindings.items():
        domain = ASSET_DOMAINS[registry.assets[asset_id].kind]
        adapter: Any = registry.resolve(domain, asset_id=asset_id)
        name = {
            "ev": "get_charge_state",
            "home_battery": "get_battery",
            "solar": "get_solar",
        }.get(registry.assets[asset_id].kind, "get_state")
        method = getattr(adapter, name, None)
        if method is None and binding.adapter == "twin":
            method = getattr(adapter, "asset_state", None)
            if method is not None:
                result.append(
                    registry.stamp(
                        domain,
                        binding.adapter,
                        method(binding.entity_id),
                        at=registry.clock(),
                    )
                )
                continue
        if callable(method):
            result.append(
                registry.stamp(
                    domain,
                    binding.adapter,
                    await method(binding.entity_id),
                    at=registry.clock(),
                )
            )
    for (domain, implementation), adapter in registry.instances.items():
        if domain == "presence":
            for reading in await getattr(adapter, "who_is_home")():
                result.append(
                    registry.stamp(domain, implementation, reading, at=registry.clock())
                )
        if "get_tariff_state" in adapter.capabilities:
            result.append(
                registry.stamp(
                    domain,
                    implementation,
                    await getattr(adapter, "get_tariff_state")(),
                    at=registry.clock(),
                )
            )
    # One current reading per stream, independent of upstream observation IDs.
    return tuple(
        o.model_copy(
            update={
                "id": uuid5(
                    registry.household.id,
                    f"executor:{o.domain}:{o.asset_id or o.member_id or registry.household.id}",
                )
            }
        )
        for o in result
    )


async def ingest(p: "Pipeline", registry: Registry, principal: Principal) -> Decision:
    if p._observation_batch is not None or registry.household.id != p.household_id:
        raise ValueError("Invalid observation ingestion scope")
    batch = await readings(registry)
    scheduler = principal.model_copy(update={"surface": "scheduler"})
    action = governance(
        p,
        "record_observations",
        {"batch_hash": digest([o.model_dump(mode="json") for o in batch])},
        scheduler,
    )
    p._observation_batch = batch
    p._observation_world = next(
        (
            getattr(a, "world")
            for a in registry.instances.values()
            if hasattr(a, "world")
        ),
        None,
    )
    try:
        result = await p.redeem(action, scheduler)
        if result.decision != "execute":
            raise ValueError("Observation ingestion was not authorized")
        return result
    finally:
        p._observation_batch = None
        p._observation_world = None


async def commit(p: "Pipeline", action: Action, decision: Decision) -> None:
    assert p._observation_batch is not None
    committed = []
    for observation in p._observation_batch:
        match = (
            db.observations.c.asset_id == observation.asset_id
            if observation.asset_id
            else (
                db.observations.c.member_id == observation.member_id
                if observation.member_id
                else sa.and_(
                    db.observations.c.asset_id.is_(None),
                    db.observations.c.member_id.is_(None),
                )
            )
        )
        existing = await p.connection.scalar(
            sa.select(db.observations.c.id).where(
                p.scope(db.observations),
                match,
                db.observations.c.attributes["domain"].astext == observation.domain,
            )
        )
        if existing:
            observation = observation.model_copy(update={"id": existing})
        old = await p.repo.get("observations", {"id": observation.id})
        await p.repo.put(
            "observations",
            observation,
            expected_version=old["valid_from"] if old else None,
        )
        committed.append(observation)
    seq = await p.audit.append(
        p.connection,
        p.household_id,
        p.clock(),
        EventType.OBSERVATIONS_RECORDED,
        {
            "action_id": action.action_id,
            "decision_seq": decision.audit_id,
            "requested_by": action.requested_by.model_dump(mode="json"),
            "readings": [o.model_dump(mode="json") for o in committed],
        },
    )

    if p._observation_world is not None:
        from hirz.executor.twin import checkpoint

        world = p._observation_world
        _, state = world.read()
        await checkpoint(p, world, state, seq)
