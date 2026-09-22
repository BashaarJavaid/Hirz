"""Explicit plan consent and revisions, committed through governance Decisions."""

from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import sqlalchemy as sa

from hirz import db
from hirz.executor.contracts import validate
from hirz.executor.runtime import RuntimeInputs
from hirz.executor.storage import notice, scheduled, transition
from hirz.pipeline.hashing import action_hash, digest
from hirz.pipeline.models import (
    Action,
    Decision,
    EventType,
    Plan,
    Principal,
    Requester,
    Target,
)

if TYPE_CHECKING:
    from hirz.pipeline.service import Pipeline

guarded = {
    "governance." + s
    for s in (
        "refresh_plan",
        "record_plan",
        "approve_plan",
        "revise_plan",
        "cancel_plan",
        "record_observations",
    )
}


def governance(
    p: "Pipeline",
    name: str,
    params: dict[str, Any],
    principal: Principal,
    action_id: str | None = None,
) -> Action:
    action = Action.model_validate(
        dict(
            action_id=action_id or uuid4().hex,
            **{"class": "governance." + name},
            target=Target(adapter="household", entity=str(p.household_id)),
            params=params,
            requested_by=Requester(
                member_id=None, role="unknown", surface=principal.surface
            ),
            reason="Explicit local household mutation",
            content_hash="",
        )
    )
    return action.model_copy(update={"content_hash": action_hash(action)})


async def get(p: "Pipeline", plan_id: str) -> dict[str, Any]:
    row = (
        (
            await p.connection.execute(
                sa.select(db.plans)
                .where(p.scope(db.plans), db.plans.c.plan_id == plan_id)
                .with_for_update()
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ValueError("Plan is unavailable in this household")
    return dict(row)


def eligible(p: "Pipeline", member: Requester, principal: Principal) -> bool:
    roles = {member.role, principal.claimed_role or member.role}
    return member.member_id is not None and all(
        role in {"owner", "adult", "caregiver"}
        and p.bundle.policy().domain_allowed(role, "energy.optimize_cost")
        for role in roles
    )


async def execution_authority(
    p: "Pipeline", action: Action, principal: Principal
) -> None:
    from hirz.pipeline.service import identity

    assert action.plan_id
    stored = await get(p, action.plan_id)
    member = await p.requester(principal)
    linked = await p.connection.scalar(
        sa.select(db.plan_actions.c.action_id).where(
            p.scope(db.plan_actions),
            db.plan_actions.c.plan_id == action.plan_id,
            db.plan_actions.c.action_id == action.action_id,
        )
    )
    from hirz.executor.refresh import fresh

    if (
        not await fresh(p, stored)
        or not linked
        or stored["document"]["status"] not in {"approved", "active"}
        or stored["approver"] != identity(principal)
        or principal.surface != "scheduler"
        or str(stored["member_id"]) != member.member_id
        or not eligible(p, member, principal)
    ):
        raise ValueError("Plan execution lacks current approver authority")


async def budget_params(p: "Pipeline", plan: Plan) -> dict[str, Any]:
    snapshot = await p.snapshot(p.clock())
    evs = {str(a["id"]) for a in snapshot.data["assets"] if a["kind"] == "ev"}
    latest: dict[str, dict[str, Any]] = {}
    for observation in snapshot.data["observations"]:
        asset = str(observation.get("asset_id"))
        if asset in evs and observation["domain"] == "ev":
            if (
                asset not in latest
                or observation["observed_at"] > latest[asset]["observed_at"]
            ):
                latest[asset] = observation
    result = {
        "plan_id": plan.plan_id,
        "plan_hash": digest(plan.model_dump(mode="json")),
    }
    if (
        evs
        and evs == latest.keys()
        and all(o["state"].get("soc") is not None for o in latest.values())
    ):
        result["ev_soc_floor"] = min(o["state"]["soc"] for o in latest.values())
    return result


async def budget_scope(p: "Pipeline", action: Action) -> set[str] | None:
    if action.action_class != "energy.optimize_cost" or "plan_id" not in action.params:
        return None
    stored = await get(p, str(action.params["plan_id"]))
    plan = Plan.model_validate(stored["document"])
    if stored["runtime"] is None or action.params != await budget_params(p, plan):
        raise ValueError("Budget scope must match a stored complete planning workload")
    inputs = RuntimeInputs.model_validate(stored["runtime"]).workload
    snapshot = await p.snapshot(p.clock())
    entities = {z.entity for z in inputs.zones}
    if inputs.ev:
        entities.add("ev")
    if inputs.battery:
        entities.add("home_battery")
    if inputs.appliance:
        entities.add("dishwasher")
    required = {
        str(b["asset_id"])
        for b in snapshot.data["asset_bindings"]
        if b["entity_id"] in entities
    }
    # The seed's explicit EV-floor bound remains an obligation even for HVAC-only work.
    required.update(
        str(a["id"])
        for a in snapshot.data["assets"]
        if a["kind"] == "ev" and "ev_soc_floor" in action.params
    )
    if any(s.solar_kw for s in inputs.slots):
        required.update(
            str(a["id"]) for a in snapshot.data["assets"] if a["kind"] == "solar"
        )
    return required


def reservation(stored: dict[str, Any]) -> Decimal:
    if stored.get("reservation") and "estimates" in stored["reservation"]:
        return sum(
            (Decimal(e["amount"]) for e in stored["reservation"]["estimates"]),
            Decimal(0),
        )
    if stored["runtime"]:
        runtime = RuntimeInputs.model_validate(stored["runtime"])
        return sum((e.reserved for e in runtime.estimates), Decimal(0))
    summary = stored["document"]["summary"]
    return max(
        Decimal(0),
        Decimal(str(summary["electricity_usd"])) + Decimal(str(summary["wear_usd"])),
    )


async def prepare_mutation(p: "Pipeline", action: Action, principal: Principal) -> None:
    from hirz.pipeline.service import identity

    member = await p.requester(principal)
    name = action.action_class.removeprefix("governance.")
    if name == "refresh_plan":
        from hirz.executor.refresh import prepare

        await prepare(p, action, principal)
        return
    if name == "record_observations":
        if (
            p._observation_batch is None
            or principal.surface != "scheduler"
            or member.member_id is None
            or action.params
            != {
                "batch_hash": digest(
                    [o.model_dump(mode="json") for o in p._observation_batch]
                )
            }
        ):
            raise ValueError("Only configured registry readings may be ingested")
        return
    if name in {"record_plan", "revise_plan"}:
        autonomous = action.params.get("autonomous") is True
        if (
            not eligible(p, member, principal)
            or principal.surface == "scheduler"
            and not autonomous
        ):
            raise ValueError("Plan proposals require an eligible linked member")
        if set(action.params) - {"runtime"} != (
            {"plan", "actions", "autonomous"} if autonomous else {"plan", "actions"}
        ):
            raise ValueError("Invalid plan mutation")
        plan = Plan.model_validate(action.params["plan"])
        if action.params.get("runtime") is not None:
            RuntimeInputs.model_validate(action.params["runtime"]).validate_plan(plan)
        raw_actions = action.params["actions"]
        if not isinstance(raw_actions, list):
            raise ValueError("Plan actions must be a list")
        actions = tuple(validate(Action.model_validate(a)) for a in raw_actions)
        if (
            plan.household_id != p.household_id
            or plan.status != "proposed"
            or plan.actions != tuple(a.action_id for a in actions)
            or len(set(plan.actions)) != len(actions)
            or any(
                a.plan_id != plan.plan_id
                or a.scheduled_for is None
                or not plan.horizon.start <= a.scheduled_for <= plan.horizon.end
                for a in actions
            )
        ):
            raise ValueError("Invalid plan scope or action links")
        if await p.connection.scalar(
            sa.select(db.plans.c.plan_id).where(
                p.scope(db.plans), db.plans.c.plan_id == plan.plan_id
            )
        ):
            raise ValueError("Plan identifiers are immutable")
        if actions and await p.connection.scalar(
            sa.select(db.actions.c.action_id)
            .where(p.scope(db.actions), db.actions.c.action_id.in_(plan.actions))
            .limit(1)
        ):
            raise ValueError("Plan action identifiers must be fresh")
        if name == "revise_plan":
            if not plan.supersedes:
                raise ValueError("Revision must name its superseded plan")
            old = await get(p, plan.supersedes)
            predecessor = Plan.model_validate(old["document"])
            if (
                plan.horizon.end != predecessor.horizon.end
                or plan.horizon.start < predecessor.horizon.start
            ):
                raise ValueError("A refresh must preserve the approved horizon end")
            if autonomous and plan.goals != predecessor.goals:
                raise ValueError("Automatic refresh must preserve approved goals")
            if old["runtime"] and action.params.get("runtime") is not None:
                prior_inputs = RuntimeInputs.model_validate(old["runtime"])
                next_inputs = RuntimeInputs.model_validate(action.params["runtime"])
                next_inputs.preserves(prior_inputs)
            if autonomous and (
                principal.surface != "scheduler"
                or (old["approver"] or old["requester"]) != identity(principal)
                or old["member_id"] is not None
                and str(old["member_id"]) != member.member_id
            ):
                raise ValueError(
                    "Autonomous replacement requires the inherited approver"
                )
            if plan.version != old["document"]["version"] + 1 or old["document"][
                "status"
            ] in {"superseded", "completed", "abandoned"}:
                raise ValueError("Invalid revision version or prior status")
        elif autonomous or plan.supersedes is not None or plan.version != 1:
            raise ValueError("Initial plan must have version one")
        return
    if set(action.params) != (
        {"plan_id", "budget_action"} if name == "approve_plan" else {"plan_id"}
    ):
        raise ValueError("Invalid consent mutation")
    stored = await get(p, str(action.params["plan_id"]))
    plan = Plan.model_validate(stored["document"])
    if name == "cancel_plan":
        if member.member_id is None or (
            member.role != "owner" and str(stored["member_id"]) != member.member_id
        ):
            raise ValueError("Only the approver or owner may cancel a plan")
        if (
            principal.claimed_role is not None
            and principal.claimed_role != "owner"
            and str(stored["member_id"]) != member.member_id
        ):
            raise ValueError("Claimed authority cannot cancel this plan")
        return
    from hirz.executor.refresh import fresh

    if (
        not await fresh(p, stored)
        or not eligible(p, member, principal)
        or principal.surface == "scheduler"
        and stored["approver"] != identity(principal)
        or plan.status != "proposed"
    ):
        raise ValueError("Plan is not eligible for fresh consent")
    budget = (
        (
            await p.connection.execute(
                sa.select(db.actions).where(
                    p.scope(db.actions),
                    db.actions.c.action_id == action.params["budget_action"],
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    expected = reservation(stored)
    if (
        budget is None
        or budget["grant_seq"] is None
        or budget["principal"] != identity(principal)
        or budget["proposal"]["class"] != "energy.optimize_cost"
        or budget["proposal"]["params"] != await budget_params(p, plan)
        or Decimal(budget["cost"]) != expected
    ):
        raise ValueError("Plan consent requires its separate energy budget grant")


async def stop_unstarted(
    p: "Pipeline", plan_id: str, event: EventType, status: str
) -> None:
    ids = (
        (
            await p.connection.execute(
                sa.select(db.actions.c.action_id)
                .join(
                    db.plan_actions,
                    sa.and_(
                        db.actions.c.household_id == db.plan_actions.c.household_id,
                        db.actions.c.action_id == db.plan_actions.c.action_id,
                    ),
                )
                .where(
                    p.scope(db.actions),
                    db.plan_actions.c.plan_id == plan_id,
                    db.actions.c.execution_attempt_seq.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for action_id in ids:
        await transition(p, action_id, status, event, plan_id=plan_id)
        approvals = (
            (
                await p.connection.execute(
                    sa.select(db.approvals).where(
                        p.scope(db.approvals),
                        db.approvals.c.action_id == action_id,
                        db.approvals.c.status.in_(["pending", "approved"]),
                    )
                )
            )
            .mappings()
            .all()
        )
        for approval in approvals:
            await p.status(dict(approval), "expired")
            await p.audit.append(
                p.connection,
                p.household_id,
                p.clock(),
                EventType.EXPIRED,
                {"approval_id": approval["approval_id"], "reason": event.value},
            )


async def hold(p: "Pipeline", action: Action, member_id: str, reason: str) -> None:
    if action.plan_id:
        stored = await get(p, action.plan_id)
        if stored["document"]["status"] not in {"superseded", "abandoned", "completed"}:
            await stop_unstarted(p, action.plan_id, EventType.EXECUTION_HELD, "held")
            seq = await p.audit.append(
                p.connection,
                p.household_id,
                p.clock(),
                EventType.EXECUTION_HELD,
                {
                    "plan_id": action.plan_id,
                    "status": "refreshing",
                    "trigger_action": action.action_id,
                },
            )
            await p.connection.execute(
                db.plans.update()
                .where(p.scope(db.plans), db.plans.c.plan_id == action.plan_id)
                .values(
                    document=stored["document"] | {"status": "refreshing"},
                    audit_seq=seq,
                )
            )
    if action.plan_id:
        from hirz.executor.refresh import queue

        await queue(p, await get(p, action.plan_id), reason)
    await notice(
        p,
        member_id,
        action.action_id,
        (
            "A plan needs your attention. Review and revise it to continue. "
            if action.plan_id
            else "A request needs your attention. Review it before trying again. "
        )
        + reason,
    )


async def commit_mutation(
    p: "Pipeline", action: Action, decision: Decision, principal: Principal
) -> None:
    from hirz.pipeline.service import identity

    name = action.action_class.removeprefix("governance.")
    if name == "refresh_plan":
        from hirz.executor.refresh import commit as refresh_commit

        await refresh_commit(p, action, decision, principal)
        return
    if name == "record_observations":
        from hirz.executor.observations import commit

        await commit(p, action, decision)
        return
    member = await p.requester(principal)
    event = {
        "record_plan": EventType.PLAN_CREATED,
        "revise_plan": EventType.PLAN_REVISED,
        "approve_plan": EventType.PLAN_APPROVED,
        "cancel_plan": EventType.PLAN_CANCELLED,
    }[name]
    seq = await p.audit.append(
        p.connection,
        p.household_id,
        p.clock(),
        event,
        {
            "action_id": action.action_id,
            "decision_seq": decision.audit_id,
            "member_id": member.member_id,
            "surface": principal.surface,
            "mutation": action.params,
        },
    )
    if name in {"record_plan", "revise_plan"}:
        plan = Plan.model_validate(action.params["plan"])
        if plan.supersedes:
            old = await get(p, plan.supersedes)
            from hirz.executor.refresh import job

            refresh_job = await job(p, old)
            inherited = bool(
                action.params.get("autonomous")
                and old["approver"]
                and not (refresh_job and refresh_job["explicit"])
            )
            await stop_unstarted(
                p, plan.supersedes, EventType.PLAN_REVISED, "cancelled"
            )
            await p.connection.execute(
                db.plans.update()
                .where(p.scope(db.plans), db.plans.c.plan_id == plan.supersedes)
                .values(
                    document=old["document"] | {"status": "superseded"}, audit_seq=seq
                )
            )
        await p.connection.execute(
            db.plans.insert().values(
                household_id=p.household_id,
                plan_id=plan.plan_id,
                document=plan.model_dump(mode="json"),
                runtime=action.params.get("runtime"),
                requester=identity(
                    principal.model_copy(update={"surface": "scheduler"})
                ),
                lineage_id=(old["lineage_id"] or old["plan_id"])
                if plan.supersedes
                else plan.plan_id,
                accepted_at=p.clock(),
                approver=old["approver"] if plan.supersedes and inherited else None,
                member_id=UUID(str(member.member_id))
                if plan.supersedes and inherited
                else None,
                audit_seq=seq,
            )
        )
        from hirz.executor.refresh import fingerprint, save

        created = await get(p, plan.plan_id)
        await save(
            p,
            created,
            dict(
                plan_id=plan.plan_id,
                state="idle",
                reasons=[],
                explicit=False,
                blocking_reason=None,
                next_retry=None,
                fingerprint=await fingerprint(p, created),
            ),
            decision=decision.audit_id,
        )
        for raw in action.params["actions"]:  # type: ignore[union-attr]
            a = Action.model_validate(raw)
            await p.proposal(a, principal, None)
            await p.connection.execute(
                db.plan_actions.insert().values(
                    household_id=p.household_id,
                    plan_id=plan.plan_id,
                    action_id=a.action_id,
                )
            )
        return
    stored = await get(p, str(action.params["plan_id"]))
    plan = Plan.model_validate(stored["document"])
    if name == "cancel_plan":
        from hirz.executor.refresh import save

        await save(
            p,
            stored,
            {"state": "cancelled", "next_retry": None},
            decision=decision.audit_id,
        )
        await stop_unstarted(
            p, plan.plan_id, EventType.EXECUTION_CANCELLED, "cancelled"
        )
        await p.connection.execute(
            db.plans.update()
            .where(p.scope(db.plans), db.plans.c.plan_id == plan.plan_id)
            .values(
                document=stored["document"] | {"status": "abandoned"}, audit_seq=seq
            )
        )
        return
    scheduler = principal.model_copy(
        update={
            "surface": "scheduler",
            "requester_confirmed": False,
            "passkey_verified": False,
            "verified_action_hash": None,
        }
    )
    await p.connection.execute(
        db.plans.update()
        .where(p.scope(db.plans), db.plans.c.plan_id == plan.plan_id)
        .values(
            document=stored["document"] | {"status": "approved"},
            approver=identity(scheduler),
            member_id=UUID(str(member.member_id)),
            audit_seq=seq,
        )
    )
    from hirz.executor.budget import allocate

    await allocate(p, stored, action.params["budget_action"])
    for action_id in plan.actions:
        raw = await p.connection.scalar(
            sa.select(db.actions.c.proposal).where(
                p.scope(db.actions), db.actions.c.action_id == action_id
            )
        )
        a = Action.model_validate(raw).model_copy(
            update={"requested_by": member.model_copy(update={"surface": "scheduler"})}
        )
        await p.connection.execute(
            db.actions.update()
            .where(p.scope(db.actions), db.actions.c.action_id == action_id)
            .values(
                proposal=a.model_dump(mode="json", by_alias=True),
                principal=identity(scheduler),
            )
        )
        # Consent schedules work; it grants no device permission and clears no device ASK.
        queued = decision.model_copy(
            update={
                "action_id": action_id,
                "event_type": EventType.EXECUTE,
                "audit_id": None,
            }
        )
        await scheduled(p, a, queued, None)


class PlanService:
    def __init__(self, pipeline: "Pipeline"):
        self.pipeline = pipeline

    async def record(
        self,
        plan: Plan,
        actions: tuple[Action, ...],
        principal: Principal,
        *,
        runtime: RuntimeInputs | None = None,
    ) -> Decision:
        return await self.pipeline.redeem(
            governance(
                self.pipeline,
                "record_plan",
                {
                    **({"runtime": runtime.model_dump(mode="json")} if runtime else {}),
                    "plan": plan.model_dump(mode="json"),
                    "actions": [
                        a.model_dump(mode="json", by_alias=True) for a in actions
                    ],
                },
                principal,
            ),
            principal,
        )

    async def revise(
        self,
        plan: Plan,
        actions: tuple[Action, ...],
        principal: Principal,
        *,
        autonomous: bool = False,
        runtime: RuntimeInputs | None = None,
    ) -> Decision:
        from hirz.executor.budget import transfer
        from hirz.executor.refresh import job

        p = self.pipeline
        async with p.repo.write(p.clock):
            old = await get(p, plan.supersedes or "")
            current = await job(p, old)
            inherit = bool(
                autonomous and old["approver"] and not (current and current["explicit"])
            )
            decision = await p.mutate_locked(
                governance(
                    p,
                    "revise_plan",
                    {
                        **({"autonomous": True} if autonomous else {}),
                        **(
                            {"runtime": runtime.model_dump(mode="json")}
                            if runtime
                            else {}
                        ),
                        "plan": plan.model_dump(mode="json"),
                        "actions": [
                            a.model_dump(mode="json", by_alias=True) for a in actions
                        ],
                    },
                    principal,
                ),
                principal,
            )
            if decision.decision != "execute":
                return decision
            if runtime:
                history = tuple(
                    dict(r)
                    for r in (
                        await p.connection.execute(
                            sa.select(db.actions).where(
                                p.scope(db.actions), db.actions.c.lifecycle.is_not(None)
                            )
                        )
                    ).mappings()
                )
                allocation = await transfer(p, old, runtime, history)
                await p.connection.execute(
                    db.plans.update()
                    .where(p.scope(db.plans), db.plans.c.plan_id == plan.plan_id)
                    .values(reservation=allocation)
                )
            if inherit:
                approved = await self.approve_locked(plan.plan_id, principal)
                if approved.decision != "execute":
                    raise ValueError(
                        "Automatic replacement requires a current budget grant"
                    )
                return approved
            return decision

    async def approve(
        self, plan_id: str, principal: Principal, *, approval_id: str | None = None
    ) -> Decision:
        p = self.pipeline
        async with p.repo.write(p.clock):
            return await self.approve_locked(
                plan_id, principal, approval_id=approval_id
            )

    async def approve_locked(
        self, plan_id: str, principal: Principal, *, approval_id: str | None = None
    ) -> Decision:
        from hirz.executor.refresh import fresh

        p = self.pipeline
        stored = await get(p, plan_id)
        plan = Plan.model_validate(stored["document"])
        if (
            plan.status != "proposed"
            or not await fresh(p, stored)
            or not eligible(p, await p.requester(principal), principal)
        ):
            raise ValueError("Plan is not eligible for fresh consent")
        params = await budget_params(p, plan)
        action = governance(p, "approve_plan", {}, principal, "plan-budget:" + plan_id)
        action = action.model_copy(
            update={"action_class": "energy.optimize_cost", "params": params}
        )
        action = action.model_copy(update={"content_hash": action_hash(action)})
        cost = reservation(stored)
        grant = await p.mutate_locked(
            action, principal, cost=cost, approval_id=approval_id
        )
        if grant.decision != "execute":
            return grant
        approved = await p.mutate_locked(
            governance(
                p,
                "approve_plan",
                {"plan_id": plan_id, "budget_action": action.action_id},
                principal,
            ),
            principal,
        )
        if approved.decision != "execute":
            raise ValueError("Plan consent changed during authorization")
        return approved

    async def request_refresh(
        self,
        plan_id: str,
        principal: Principal,
        *,
        reason: str = "Explicit change request",
        explicit: bool = True,
        retry_action_id: str | None = None,
    ) -> Decision:
        from hirz.executor.refresh import RefreshService

        return await RefreshService(self.pipeline).request(
            plan_id,
            principal,
            reason=reason,
            explicit=explicit,
            retry_action_id=retry_action_id,
        )

    async def update_inputs(
        self,
        plan_id: str,
        runtime: RuntimeInputs,
        principal: Principal,
        *,
        explicit: bool = True,
    ) -> Decision:
        from hirz.executor.refresh import RefreshService

        return await RefreshService(self.pipeline).update(
            plan_id, runtime, principal, explicit=explicit
        )

    async def read_current(self, plan_id: str, principal: Principal) -> Plan:
        from hirz.executor.refresh import RefreshService

        return await RefreshService(self.pipeline).read(plan_id, principal)

    async def cancel(self, plan_id: str, principal: Principal) -> Decision:
        return await self.pipeline.redeem(
            governance(self.pipeline, "cancel_plan", {"plan_id": plan_id}, principal),
            principal,
        )
