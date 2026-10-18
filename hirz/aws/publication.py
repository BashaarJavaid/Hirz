"""Audited write-ahead publication. An uncertain engine stays blocked."""

import json
from typing import Any

import sqlalchemy as sa
from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from sqlalchemy.dialects.postgresql import insert

from hirz import db
from hirz.audit import Verification
from hirz.aws.policy import Findings, Publisher, inventory, quota
from hirz.companion import policy
from hirz.companion.governance import constitution
from hirz.constitution.compiler import compile_policy
from hirz.constitution.schema import loads
from hirz.pipeline.hashing import digest
from hirz.pipeline.models import Decision, EventType, Principal
from hirz.pipeline.service import Pipeline


def binding(job: dict[str, Any]) -> str:
    return digest(
        {
            key: job[key]
            for key in (
                "id",
                "engine_id",
                "candidate_hash",
                "base_hash",
                "base_version",
                "principal",
                "decision_seq",
                "session_digest",
            )
        }
    )


async def queue(
    p: Pipeline,
    principal: Principal,
    draft: dict[str, Any],
    decision: Decision,
    session_digest: str,
) -> None:
    assert p.policy_route is not None
    if principal.credential_id is None:
        raise ValueError("Publication requires the initiating passkey credential")
    await p.connection.execute(
        insert(db.policy_engines)
        .values(
            id=p.policy_route.engine_id,
            generation=0,
            ready=False,
            inventory={},
            changed_at=p.clock(),
        )
        .on_conflict_do_nothing()
    )
    job = dict(
        id=draft["id"],
        household_id=p.household_id,
        engine_id=p.policy_route.engine_id,
        status="queued",
        candidate_hash=draft["candidate_hash"],
        base_hash=draft["base_hash"],
        base_version=draft["base_version"],
        principal=principal.model_dump(mode="json"),
        decision_seq=decision.audit_id,
        session_digest=session_digest,
        desired={},
        findings=[],
        created_at=p.clock(),
    )
    await p.connection.execute(db.policy_publications.insert().values(**job))
    await p.audit.append(
        p.connection,
        p.household_id,
        p.clock(),
        EventType.POLICY_PUBLICATION,
        {
            "publication_id": job["id"],
            "candidate_hash": job["candidate_hash"],
            "status": "queued",
            "decision_seq": decision.audit_id,
            "binding_hash": binding(job),
        },
    )


async def transition(
    p: Pipeline, job: dict[str, Any], status: str, **values: Any
) -> Decision:
    principal = Principal.model_validate(job["principal"]).model_copy(
        update={
            "surface": "scheduler",
            "credential_id": None,
            "passkey_verified": False,
            "verified_action_hash": None,
        }
    )
    decision = await constitution(p, principal, "publish", job["id"])
    await p.connection.execute(
        db.policy_publications.update()
        .where(
            db.policy_publications.c.id == job["id"], p.scope(db.policy_publications)
        )
        .values(status=status, **values)
    )
    await p.audit.append(
        p.connection,
        p.household_id,
        p.clock(),
        EventType.POLICY_PUBLICATION,
        {
            "publication_id": job["id"],
            "candidate_hash": job["candidate_hash"],
            "initiating_decision": job["decision_seq"],
            "status": status,
            "decision_seq": decision.audit_id,
            **values,
        },
    )
    return decision


async def checked(p: Pipeline, job: dict[str, Any]) -> tuple[Any, ...]:
    queued = (
        (
            await p.connection.execute(
                sa.select(db.audit_log).where(
                    p.scope(db.audit_log),
                    db.audit_log.c.event_type == EventType.POLICY_PUBLICATION,
                    db.audit_log.c.payload["publication_id"].astext == job["id"],
                    db.audit_log.c.payload["status"].astext == "queued",
                )
            )
        )
        .mappings()
        .one()
    )
    signed = Verification(p.household_id, p.audit.key.public_key()).feed(dict(queued))
    if signed.payload["binding_hash"] != binding(job):
        raise ValueError("Queued activation differs from its signed initiating binding")
    principal = Principal.model_validate(job["principal"])
    if not principal.credential_id or not principal.passkey_verified:
        raise ValueError("Missing queued passkey binding")
    inputs = await policy.activation_inputs(
        p, principal, job["id"], job["candidate_hash"], job["session_digest"]
    )
    if (
        inputs[1]["hash"] != job["base_hash"]
        or inputs[1]["version"] != job["base_version"]
    ):
        raise ValueError("Queued base changed")
    return inputs


def desired_inventory(
    p: Pipeline, candidate: str, committed: dict[str, str]
) -> dict[str, str]:
    assert p.policy_route is not None
    compiled = compile_policy(
        loads(candidate), p.policy_route.gateway_arn, engine="agentcore-policy"
    )
    candidate_inventory = inventory([compiled])
    prefix = "_".join(next(iter(candidate_inventory)).split("_", 2)[:2]) + "_"
    desired = {
        n: s for n, s in committed.items() if not n.startswith(prefix)
    } | candidate_inventory
    quota(desired, committed)
    return desired


async def advance(p: Pipeline, publisher: Publisher) -> None:
    """Called with a dedicated connection; session lock spans durable commits."""
    assert p.policy_route is not None
    engine_id = p.policy_route.engine_id
    async with p.connection.begin():
        locked = await p.connection.scalar(
            sa.text(
                "SELECT pg_try_advisory_lock(hashtext('hirz-policy'), hashtext(:engine))"
            ),
            {"engine": engine_id},
        )
    if not locked:
        return
    try:
        await _advance(p, publisher)
    finally:
        if p.connection.in_transaction():
            await p.connection.rollback()
        async with p.connection.begin():
            await p.connection.execute(
                sa.text(
                    "SELECT pg_advisory_unlock(hashtext('hirz-policy'), hashtext(:engine))"
                ),
                {"engine": engine_id},
            )


async def _advance(p: Pipeline, publisher: Publisher) -> None:
    assert p.policy_route is not None
    async with p.repo.write(p.clock):
        engine = (
            (
                await p.connection.execute(
                    sa.select(db.policy_engines)
                    .where(db.policy_engines.c.id == p.policy_route.engine_id)
                    .with_for_update()
                )
            )
            .mappings()
            .one_or_none()
        )
        if engine is None:
            return
        job_row = (
            (
                await p.connection.execute(
                    sa.select(db.policy_publications)
                    .where(
                        p.scope(db.policy_publications),
                        db.policy_publications.c.engine_id == engine["id"],
                        db.policy_publications.c.status.in_(
                            ["queued", "publishing", "applying", "recovering"]
                        ),
                        db.policy_publications.c.id == engine["publication_id"]
                        if engine["publication_id"] is not None
                        else sa.true(),
                    )
                    .order_by(
                        db.policy_publications.c.created_at, db.policy_publications.c.id
                    )
                    .limit(1)
                )
            )
            .mappings()
            .one_or_none()
        )
        if job_row is None or engine["publication_id"] not in (None, job_row["id"]):
            return
        job = dict(job_row)
        if job["status"] == "applying":
            await transition(
                p,
                job,
                "recovering",
                findings=[
                    *job["findings"],
                    {"error": "Interrupted publication; restoring committed inventory"},
                ],
            )
            return
        if job["status"] == "queued":
            try:
                row, _, _, _ = await checked(p, job)
                desired = desired_inventory(p, row["candidate"], engine["inventory"])
            except ValueError as exc:
                await transition(p, job, "failed", findings=[{"error": str(exc)}])
                return
            await transition(p, job, "publishing", desired=desired)
            await p.connection.execute(
                db.policy_engines.update()
                .where(db.policy_engines.c.id == engine["id"])
                .values(
                    ready=False,
                    publication_id=job["id"],
                    generation=engine["generation"] + 1,
                    changed_at=p.clock(),
                )
            )
            return  # Commit the block before the first remote write.
    try:
        if job["status"] == "publishing":
            async with p.repo.write(p.clock):
                row, _, _, _ = await checked(p, job)
                if job["desired"] != desired_inventory(
                    p, row["candidate"], engine["inventory"]
                ):
                    raise ValueError("Queued compiled inventory changed")
                await transition(p, job, "applying")
        desired = (
            job["desired"] if job["status"] == "publishing" else engine["inventory"]
        )
        # Keep both schemas until restoration/removal finishes; optional fields grant no authority.
        contract_ready = await publisher.contract(engine["inventory"] | job["desired"])
        done = contract_ready and await publisher.step(
            desired, recovering=job["status"] == "recovering"
        )
        if not done:
            if job["status"] == "publishing":
                async with p.repo.write(p.clock):
                    await transition(p, job, "publishing")
            return
        async with p.repo.write(p.clock):
            if job["status"] == "publishing":
                row, base, bundle, pending = await checked(p, job)
                if job["desired"] != desired_inventory(
                    p, row["candidate"], engine["inventory"]
                ):
                    raise ValueError("Queued compiled inventory changed")
                decision = await transition(p, job, "committed")
                await policy.commit(
                    p,
                    Principal.model_validate(job["principal"]),
                    row,
                    base,
                    bundle,
                    pending,
                    decision,
                )
                installed = job["desired"]
            else:
                await transition(p, job, "failed")
                installed = engine["inventory"]
            await p.connection.execute(
                db.policy_engines.update()
                .where(db.policy_engines.c.id == engine["id"])
                .values(ready=True, publication_id=None, inventory=installed)
            )
    except Exception as exc:
        if p.connection.in_transaction():
            await p.connection.rollback()
        findings = (
            json.loads(json.dumps(exc.policy, default=str))
            if isinstance(exc, Findings)
            else json.loads(json.dumps(exc.response, default=str))
            if isinstance(exc, ClientError)
            else {"error": type(exc).__name__, "message": str(exc)}
        )
        async with p.repo.write(p.clock):
            await transition(
                p,
                job,
                "recovering" if job["status"] == "publishing" else "blocked",
                findings=[*job["findings"], findings],
            )
