"""Household tool dispatch over existing services, serialized with durable receipts."""

import base64
import struct
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

import sqlalchemy as sa

from hirz import db
from hirz.executor.contracts import SUPPORTED, validate
from hirz.executor.plans import PlanService, get, governance
from hirz.executor.refresh import RefreshService, fresh
from hirz.executor.runtime import RuntimeInputs
from hirz.explainer.core import (
    approved_figures,
    context,
    display_name,
    facts,
    local_time,
    safe_text,
)
from hirz.graph.context import ContextSnapshot, project
from hirz.graph.models import ConstraintSpec
from hirz.mcp.contracts import (
    TOOLS,
    ActionInput,
    ApprovalInput,
    AuditInput,
    AuditSummary,
    ContextInput,
    ExplainInput,
    Input,
    PermissionInput,
    PlanInput,
    ProposalInput,
    Result,
    RevisionInput,
    RiskInput,
    VerifyInput,
    response,
)
from hirz.mcp.persistence import command
from hirz.mcp.profiles import Profile, ProfileName
from hirz.pipeline.hashing import action_hash, digest
from hirz.pipeline.models import (
    Action,
    Decision,
    EventType,
    ExpectedEffect,
    Inverse,
    Plan,
    Principal,
    Requester,
    Revert,
    Target,
)
from hirz.pipeline.service import Pipeline, identity
from hirz.planner.coordinator import (
    Clarification,
    Intake,
    active,
    prepare,
    records,
    time_at,
)
from hirz.risk import CONSUMER_ACTIONS


def unique(
    rows: list[dict[str, Any]], reference: str | None, name: str = "name"
) -> dict[str, Any]:
    matches = (
        rows
        if reference is None
        else [
            r
            for r in rows
            if str(r["id"]) == reference
            or str(r.get(name, "")).casefold() == reference.casefold()
        ]
    )
    if len(matches) != 1:
        raise Clarification(
            "Please name one available household member, device or room exactly.",
            options=tuple(
                label
                for row in rows[:5]
                if (label := display_name(str(row.get(name, ""))))
            ),
        )
    return matches[0]


def horizon_end(at: datetime, timezone: str, horizon: str) -> datetime:
    if horizon == "next_24h":
        return at + timedelta(hours=24)
    local = at.astimezone(ZoneInfo(timezone))
    end = local.replace(hour=8, minute=0, second=0, microsecond=0)
    if end <= local:
        end += timedelta(days=1)
    return end.astimezone(UTC)


def audit_window(
    at: datetime, timezone: str, window: str | None
) -> tuple[datetime, datetime]:
    local = at.astimezone(ZoneInfo(timezone))
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if window == "last_night":
        return midnight - timedelta(hours=6), min(at, midnight + timedelta(hours=8))
    if window == "this_week":
        return midnight - timedelta(days=local.weekday()), at
    return midnight, at


class HouseholdTools:
    def __init__(
        self,
        pipeline: Pipeline,
        principal: Principal,
        *,
        policy_hash: str | None = None,
        profiles: dict[ProfileName, Profile] | None = None,
    ):
        self.p, self.principal = pipeline, principal
        self.policy_hash = policy_hash
        self.profiles = profiles or {}

    async def call(self, name: str, arguments: dict[str, Any]) -> Result:
        schema = TOOLS[name][0]
        args = schema.model_validate(arguments)
        p = self.p
        async with p.repo.write(p.clock):
            if self.policy_hash is not None:
                row = (
                    await p.connection.execute(
                        sa.select(
                            db.constitution_versions.c.hash,
                            db.households.c.constitution_version,
                        )
                        .join(
                            db.households,
                            sa.and_(
                                db.households.c.id
                                == db.constitution_versions.c.household_id,
                                db.households.c.constitution_version
                                == db.constitution_versions.c.version,
                            ),
                        )
                        .where(db.households.c.id == p.household_id)
                    )
                ).one_or_none()
                if (
                    row is None
                    or row.hash != self.policy_hash
                    or row.constitution_version != p.bundle.policy().version
                ):
                    raise ValueError(
                        "Household policy changed; restart the local server."
                    )
            member = await p.requester(self.principal)
            if member.member_id is None or member.role in {"unknown", "child"}:
                raise ValueError("This linked account cannot access household tools.")
            principal_hash = digest(identity(self.principal))
            request_id = getattr(args, "request_id", None)
            fingerprint = digest(
                {"tool": name, "arguments": args.model_dump(mode="json")}
            )
            if request_id:
                prior = (
                    (
                        await p.connection.execute(
                            sa.select(db.tool_requests).where(
                                p.scope(db.tool_requests),
                                db.tool_requests.c.principal_hash == principal_hash,
                                db.tool_requests.c.request_id == request_id,
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if prior:
                    if prior["fingerprint"] != fingerprint:
                        raise ValueError(
                            "REQUEST_CONFLICT: Use a new request key for a changed request."
                        )
                    return Result.model_validate(prior["result"])
            snapshot = await p.snapshot(p.clock())
            try:
                answer = await self.dispatch(name, args, snapshot)
            except Clarification as exc:
                return response(
                    "Please clarify this household request.",
                    details=(str(exc),),
                    status="clarification",
                    code="CLARIFY",
                    options=exc.options or ("Give the missing details",),
                )
            if request_id:
                receipt = dict(
                    principal_hash=principal_hash,
                    request_id=request_id,
                    fingerprint=fingerprint,
                    result=answer.model_dump(mode="json"),
                )
                if isinstance(args, PermissionInput):
                    seq = await p.audit.append(
                        p.connection,
                        p.household_id,
                        p.clock(),
                        EventType.DRY_RUN,
                        {
                            "request_hash": fingerprint,
                            "decision": answer.data.decision.model_dump(mode="json")
                            if answer.data.decision
                            else None,
                            **(
                                {
                                    "decisions": [
                                        d.model_dump(mode="json")
                                        for d in answer.data.decisions
                                    ]
                                }
                                if answer.data.decisions
                                else {}
                            ),
                        },
                    )
                    await p.connection.execute(
                        db.tool_requests.insert().values(
                            household_id=p.household_id, decision_seq=seq, **receipt
                        )
                    )
                else:
                    await command(p, "record_tool_request", receipt, self.principal)
            return answer

    async def current(self) -> dict[str, Any] | None:
        p = self.p
        result = (
            (
                await p.connection.execute(
                    sa.select(db.plans)
                    .where(
                        p.scope(db.plans),
                        db.plans.c.document["status"].astext.notin_(
                            ["superseded", "completed", "abandoned"]
                        ),
                    )
                    .order_by(db.plans.c.audit_seq.desc())
                    .limit(1)
                )
            )
            .mappings()
            .one_or_none()
        )
        return dict(result) if result else None

    async def dispatch(
        self, name: str, args: Input, snapshot: ContextSnapshot
    ) -> Result:
        p, principal = self.p, self.principal
        if isinstance(args, (RiskInput, VerifyInput)):
            from hirz.mcp.trust import assess, verify

            return (
                await assess(p, principal, args, snapshot)
                if isinstance(args, RiskInput)
                else await verify(p, principal, args, snapshot)
            )
        if isinstance(args, ContextInput):
            member = (
                unique(snapshot.data["members"], args.member, "display_name")
                if args.member
                else None
            )
            data = project(
                snapshot.data, args.scope, UUID(str(member["id"])) if member else None
            )
            for observation in data.get("observations", []):
                observation["staleness_seconds"] = (
                    p.clock() - datetime.fromisoformat(str(observation["observed_at"]))
                ).total_seconds()
            return response(
                "Here is the household information available to your linked account.",
                context=snapshot.model_copy(update={"scope": args.scope, "data": data}),
            )
        if isinstance(args, ProposalInput):
            decision = await command(p, "propose_rule", {"text": args.text}, principal)
            return response(
                "Your proposed rule is recorded. It has not been activated.",
                details=(
                    "Phone delivery and activation are unavailable in this preview.",
                ),
                status="recorded",
                reference=decision.action_id,
            )
        if isinstance(args, PlanInput):
            return await self.plan(args, snapshot)
        if isinstance(args, RevisionInput):
            return await self.revise(args, snapshot)
        if isinstance(args, ApprovalInput):
            return await self.approve(args)
        if isinstance(args, ExplainInput):
            stored = (
                await get(p, args.plan_id) if args.plan_id else await self.current()
            )
            if stored is None:
                return response(
                    "There is no plan to explain yet.", status="unavailable"
                )
            plan = Plan.model_validate(stored["document"])
            if args.focus not in {"summary", "conflicts", *plan.actions, *plan.goals}:
                raise Clarification(
                    "Choose the summary, conflicts, or an action or goal in this plan."
                )
            if plan.status == "refreshing" or not await fresh(p, stored):
                return response(
                    "The plan is still updating. Ask again when its replacement is ready.",
                    status="preparing",
                )
            # Stored narration is already figure-checked; never call a provider here.
            if args.focus == "summary":
                return Result.model_validate(
                    {"speakable": plan.speakable, "data": {"plan": plan}}
                )
            if args.focus in plan.goals:
                goals = {
                    "minimize_degree_hours": "This goal reduces departures from the requested temperatures.",
                    "minimize_grid_import": "This goal reduces grid electricity. It does not measure emissions.",
                    "minimize_cost_and_wear": "This goal reduces forecast electricity cost and battery wear within the household constraints.",
                    "comfort": "This goal keeps temperatures within the household's comfort limits.",
                    "ev_deadline": "This goal meets the requested car charge by its deadline.",
                }
                return response(
                    goals.get(
                        args.focus, "This goal is recorded in the household plan."
                    ),
                    plan=plan,
                    reference=args.focus,
                )
            if args.focus in plan.actions:
                proposal = await p.connection.scalar(
                    sa.select(db.actions.c.proposal).where(
                        p.scope(db.actions), db.actions.c.action_id == args.focus
                    )
                )
                if proposal is None:
                    raise ValueError("Stored action is unavailable")
                return response(
                    "The stored energy plan schedules this setting change.",
                    details=(
                        "The plan's recorded goals and constraints explain its overall schedule.",
                    ),
                    plan=plan,
                    action=Action.model_validate(proposal),
                )
            details = (
                plan.explain.rejected
                if args.focus == "conflicts"
                else plan.explain.facts
            )
            spoken = []
            figures = approved_figures(facts(plan, context(snapshot)))
            for line in details:
                try:
                    safe_text(line, figures)
                except ValueError:
                    continue
                if len(line.split()) <= 25:
                    spoken.append(line)
            return response(
                "Here are the recorded reasons for this plan.",
                details=tuple(spoken[:2]),
                plan=plan,
            )
        if isinstance(args, ActionInput):
            if args.action == "apply_profile":
                return await self.profile(args, snapshot)
            action, lowered = self.action(args, snapshot)
            if isinstance(args, PermissionInput):
                at = (
                    time_at(
                        args.at,
                        p.clock(),
                        p.clock() + timedelta(days=2),
                        str(snapshot.data["households"][0]["timezone"]),
                    )
                    if args.at
                    else p.clock()
                )
                ev = await p.assess_operation(action, lowered, None, (), at)
                # A preview never crosses the execution boundary or creates an approval.
                return response(
                    "This is a permission preview using current rules and known information.",
                    details=(
                        "Future observations remain unknown. This grants no authority.",
                    ),
                    decision=ev.decision,
                )
            if action.action_class.startswith("governance."):
                decision = await p.mutate_locked(action, lowered)
            elif action.action_class.startswith("security."):
                await p.proposal(action, lowered, None)
                ev = await p.assess_operation(action, lowered, None, (), p.clock())
                ev = await p.ask(ev, action, lowered, None, p.clock())
                decision = (
                    ev.decision
                    if ev.decision.audit_id
                    else await p.record(ev, p.clock())
                )
                return response(
                    "The household rules block this door request."
                    if decision.decision == "deny"
                    else "Door unlocking requires phone approval, which is unavailable in this preview.",
                    status="denied"
                    if decision.decision == "deny"
                    else "phone_required",
                    decision=decision,
                    source="twin" if action.target.adapter == "twin" else None,
                )
            else:
                validate(action)
                decision = await p.mutate_locked(action, lowered, enqueue=True)
            return response(
                "Your request is queued for a device check."
                if decision.status == "executing"
                else "Your request was evaluated under the household rules.",
                details=("Later approved automation may change this setting.",)
                if decision.status == "executing"
                else (),
                status="queued"
                if decision.status == "executing"
                else "denied"
                if decision.decision == "deny"
                else "ok",
                decision=decision,
                source="twin" if action.target.adapter == "twin" else None,
            )
        if isinstance(args, AuditInput):
            return await self.audit(args, snapshot)
        return response(
            "Contact checks are unavailable until the preview's trust rules are configured.",
            status="unavailable",
            code="TRUST_NOT_CONFIGURED",
        )

    async def profile(self, args: ActionInput, snapshot: ContextSnapshot) -> Result:
        if args.profile is None:
            raise Clarification(
                "Which household profile should I request?",
                options=tuple(name.replace("_", " ") for name in self.profiles),
            )
        profile = self.profiles.get(args.profile)
        if profile is None:
            return response(
                "That profile has no configured settings in this household.",
                status="unavailable",
                code="PROFILE_UNAVAILABLE",
            )
        children = []
        for setting in profile.settings:
            child, principal = self.action(
                ActionInput.model_validate(
                    setting.model_dump(exclude_none=True)
                    | {
                        "request_id": args.request_id,
                        "claimed_requester": args.claimed_requester,
                    }
                ),
                snapshot,
            )
            children.append(validate(child))
        targets = [(a.target.adapter, a.target.entity) for a in children]
        if len(set(targets)) != len(targets):
            raise Clarification(
                "This profile has conflicting settings for the same device."
            )
        aggregate = Action.model_validate(
            dict(
                action_id=uuid4().hex,
                **{"class": "environment.comfort_profile"},
                target=Target(adapter="household", entity=str(self.p.household_id)),
                params={
                    "profile": args.profile,
                    "actions": [
                        a.model_dump(mode="json", by_alias=True) for a in children
                    ],
                },
                requested_by=Requester(
                    member_id=None, role="unknown", surface=principal.surface
                ),
                reason="Explicit configured household profile request",
                content_hash="",
            )
        )
        aggregate = aggregate.model_copy(
            update={"content_hash": action_hash(aggregate)}
        )
        if isinstance(args, PermissionInput):
            at = (
                time_at(
                    args.at,
                    self.p.clock(),
                    self.p.clock() + timedelta(days=2),
                    str(snapshot.data["households"][0]["timezone"]),
                )
                if args.at
                else self.p.clock()
            )
            decisions = tuple(
                [
                    (await self.p.assess_operation(a, principal, None, (), at)).decision
                    for a in (aggregate, *children)
                ]
            )
            return response(
                "This previews the profile and each device under current rules; it grants no authority.",
                decision=decisions[0],
                decisions=decisions[1:],
            )
        decision = await self.p.mutate_locked(aggregate, principal)
        if decision.decision != "execute":
            return response(
                "The profile needs approval or is blocked by household rules.",
                decision=decision,
                status="denied" if decision.decision == "deny" else "ok",
            )
        return await self.expand_profile(aggregate, principal, decision)

    async def expand_profile(
        self, aggregate: Action, principal: Principal, decision: Decision
    ) -> Result:
        decisions = []
        payload = aggregate.params["actions"]
        if not isinstance(payload, list):
            raise ValueError("Profile actions are invalid")
        children = tuple(Action.model_validate(value) for value in payload)
        for action in children:
            if action.action_class not in {"environment.lights", "energy.hvac_adjust"}:
                raise ValueError("Profile contains an unsupported action")
            assert action.expected_effect
            action = action.model_copy(
                update={
                    "scheduled_for": self.p.clock(),
                    "expected_effect": action.expected_effect.model_copy(
                        update={"by": self.p.clock() + timedelta(seconds=30)}
                    ),
                }
            )
            action = action.model_copy(update={"content_hash": action_hash(action)})
            validate(action)
            decisions.append(
                await self.p.mutate_locked(action, principal, enqueue=True)
            )
        return response(
            "Each configured profile setting was checked under the household rules.",
            details=(
                "Some settings may need approval or be blocked. Later automation may change queued settings.",
            ),
            decision=decision,
            decisions=tuple(decisions),
            status="queued"
            if any(d.status == "executing" for d in decisions)
            else "ok",
            source="twin"
            if all(a.target.adapter == "twin" for a in children)
            else None,
        )

    def action(
        self, args: ActionInput, snapshot: ContextSnapshot
    ) -> tuple[Action, Principal]:
        p, principal = self.p, self.principal
        if args.claimed_requester:
            matches = [
                r
                for r in snapshot.data["members"]
                if str(r["display_name"]).casefold()
                == args.claimed_requester.casefold()
                or str(r["id"]) == args.claimed_requester
            ]
            role = str(matches[0]["role"]) if len(matches) == 1 else "unknown"
            principal = Principal.model_validate(
                principal.model_dump() | {"claimed_role": role}
            )
        kind = {
            "charge_car": "ev",
            "stop_charging": "ev",
            "set_temperature": "hvac_zone",
            "turn_on_light": "light",
            "turn_off_light": "light",
            "request_door_unlock": "lock",
            "hold_battery": "home_battery",
        }.get(args.action)
        if kind is None:
            return governance(p, "pause_automation", {}, principal), principal
        candidates = [r for r in snapshot.data["assets"] if r["kind"] == kind]
        reference = args.room
        if reference:
            suffix = {"light": " light", "lock": " lock"}.get(kind)
            matching = [
                r
                for r in candidates
                if str(r["name"]).casefold()
                in {reference.casefold(), reference.casefold() + (suffix or "")}
            ]
            if len(matching) == 1:
                reference = str(matching[0]["id"])
        asset = unique(candidates, reference)
        bindings = [
            r for r in snapshot.data["asset_bindings"] if r["asset_id"] == asset["id"]
        ]
        if len(bindings) != 1:
            raise Clarification(
                "That device needs a unique household binding before it can be used."
            )
        binding = bindings[0]
        target = Target(
            adapter=str(binding["adapter"]),
            entity=str(binding["entity_id"]),
            zone=str(asset["id"]) if kind == "hvac_zone" else None,
        )
        reason = "Explicit one-setting household request"
        if args.beneficiary:
            member = unique(snapshot.data["members"], args.beneficiary, "display_name")
            reason += "; intended beneficiary " + str(member["id"])
        params: dict[str, Any]
        if args.action == "set_temperature":
            if args.temperature_f is None:
                raise Clarification(
                    "What temperature in degrees Fahrenheit should I request?"
                )
            params = {"target_f": args.temperature_f}
        elif args.action == "charge_car":
            if args.percent is None or args.minutes is None:
                raise Clarification(
                    "What charge limit and maximum number of charging minutes should I request?"
                )
            params = {"charging": True, "charge_limit": args.percent / 100}
        elif args.action == "stop_charging":
            params = {"charging": False}
        elif args.action == "hold_battery":
            params = {"dispatch_kw": 0}
        elif args.action == "request_door_unlock":
            if args.minutes is None:
                raise Clarification(
                    "For how many minutes are you requesting the door unlock?"
                )
            params = {"open_minutes": args.minutes}
        else:
            params = {"on": args.action == "turn_on_light"}
        name = CONSUMER_ACTIONS[args.action]
        attr = SUPPORTED.get(name, ("", "locked"))[1]
        result = Action(
            action_id=uuid4().hex,
            **{"class": name},
            target=target,
            params=params,
            requested_by=Requester(
                member_id=None, role="unknown", surface=principal.surface
            ),
            reason=reason,
            content_hash="",
            scheduled_for=p.clock(),
            expected_effect=ExpectedEffect(
                entity=target.entity,
                attr=attr,
                value=params.get(attr, False),
                by=p.clock() + timedelta(seconds=30),
            ),
            revert=Revert(
                after_s=args.minutes * 60,
                inverse=Inverse(
                    **{"class": name}, target=target, params={"charging": False}
                ),
            )
            if args.action == "charge_car" and args.minutes
            else None,
        )
        return result.model_copy(
            update={"content_hash": action_hash(result)}
        ), principal

    async def plan(self, args: PlanInput, snapshot: ContextSnapshot) -> Result:
        p = self.p
        stored = await self.current()
        if stored:
            plan = Plan.model_validate(stored["document"])
            # Reads preserve the accepted horizon. A requested different horizon needs cancellation.
            requested_end = horizon_end(
                plan.horizon.start,
                str(snapshot.data["households"][0]["timezone"]),
                args.horizon,
            )
            if "horizon" in args.model_fields_set and requested_end != plan.horizon.end:
                return response(
                    "Cancel the existing plan before requesting a different planning horizon.",
                    status="clarification",
                    code="CANCEL_FIRST",
                )
            if args.objective is not None:
                if not stored["runtime"]:
                    return response(
                        "Planning inputs are unavailable for changing the priority.",
                        status="unavailable",
                    )
                runtime = RuntimeInputs.model_validate(stored["runtime"])
                if runtime.workload.objective != args.objective:
                    runtime = runtime.model_copy(
                        update={
                            "workload": runtime.workload.model_copy(
                                update={"objective": args.objective}
                            )
                        }
                    )
                    await RefreshService(p).command(
                        self.principal,
                        dict(
                            operation="inputs",
                            plan_id=plan.plan_id,
                            runtime=runtime.model_dump(mode="json"),
                            explicit=True,
                            reason="Explicit planning priority change",
                        ),
                        locked=True,
                    )
                    return response(
                        "Your planning priority is recorded. Review the updated plan before approving it.",
                        details=(
                            "Greenest reduces grid electricity; it does not measure emissions.",
                        )
                        if args.objective == "greenest"
                        else (),
                        status="preparing",
                        reference=plan.plan_id,
                    )
            await RefreshService(p).command(
                self.principal,
                {"plan_id": plan.plan_id, "operation": "detect"},
                locked=True,
            )
            stored = await get(p, plan.plan_id)
            plan = Plan.model_validate(stored["document"])
            if plan.status == "refreshing" or not await fresh(p, stored):
                return response(
                    "The plan is still updating. Ask again shortly.",
                    status="preparing",
                    reference=plan.plan_id,
                )
            return Result.model_validate(
                {"speakable": plan.speakable, "data": {"plan": plan}}
            )
        pending = (
            (
                await p.connection.execute(
                    sa.select(db.plan_requests)
                    .where(p.scope(db.plan_requests))
                    .order_by(db.plan_requests.c.created_at.desc())
                    .limit(1)
                )
            )
            .mappings()
            .one_or_none()
        )
        if pending and pending["status"] == "pending":
            if args.objective is not None and pending["objective"] != args.objective:
                await command(
                    p,
                    "request_plan",
                    dict(
                        operation="revise", id=pending["id"], objective=args.objective
                    ),
                    self.principal,
                )
            return response(
                "Your plan is being prepared. Ask again shortly.",
                status="preparing",
                reference=pending["id"],
            )
        if not args.request_id:
            return response(
                "No plan is ready. Would you like me to prepare one?",
                status="failed" if pending else "clarification",
                code="PREPARATION_FAILED" if pending else "REQUEST_KEY_REQUIRED",
            )
        ident = uuid4().hex
        await command(
            p,
            "request_plan",
            {
                "operation": "start",
                "id": ident,
                "objective": args.objective,
                "horizon_end": horizon_end(
                    p.clock(),
                    str(snapshot.data["households"][0]["timezone"]),
                    args.horizon,
                ).isoformat(),
            },
            self.principal,
        )
        return response(
            "Your plan request is recorded. Ask again after it has been prepared.",
            status="preparing",
            reference=ident,
        )

    async def revise(self, args: RevisionInput, snapshot: ContextSnapshot) -> Result:
        p = self.p
        stored = await self.current()
        end = (
            Plan.model_validate(stored["document"]).horizon.end
            if stored
            else p.clock() + timedelta(hours=24)
        )
        timezone = str(snapshot.data["households"][0]["timezone"])
        kind = (
            "ev"
            if args.change
            in {"car_target", "car_limit", "charge_after", "car_ready_by"}
            else "appliance"
            if args.change.startswith("appliance_")
            else "hvac_zone"
        )
        assets = [r for r in snapshot.data["assets"] if r["kind"] == kind]
        aliases = {"car", "ev"} if kind == "ev" else set()
        owners = [
            r
            for r in snapshot.data["members"]
            if str(r["id"]) == args.applies_to
            or str(r["display_name"]).casefold() == args.applies_to.casefold()
        ]
        target = (
            unique(
                [
                    r
                    for r in assets
                    if str(r.get("owner_member_id")) == str(owners[0]["id"])
                ],
                None,
            )
            if len(owners) == 1
            else unique(
                assets,
                None if args.applies_to.casefold() in aliases else args.applies_to,
            )
        )
        replaces = UUID(args.constraint_id) if args.constraint_id else None
        if args.change == "release_hold" and replaces is None:
            selected = [
                r
                for r in records(snapshot)
                if str(r.asset_id) == str(target["id"])
                and r.spec.kind == "manual_hold"
                and active(r, p.clock(), p.clock() + timedelta(microseconds=1))
            ]
            if len(selected) != 1:
                raise Clarification("There is no unique active hold to release.")
            replaces = selected[0].id
        if replaces:
            selected = [
                r
                for r in records(snapshot)
                if r.id == replaces and str(r.asset_id) == str(target["id"])
            ]
            if len(selected) != 1:
                raise Clarification(
                    "That constraint is unavailable for this household target."
                )
        spec = None
        if args.operation != "remove":
            change = {
                "car_target": "ev_target",
                "car_limit": "ev_ceiling",
                "charge_after": "ev_not_before",
                "car_ready_by": "ev_deadline",
                "appliance_after": "appliance_not_before",
                "appliance_ready_by": "appliance_deadline",
                "temperature": "temperature",
                "temperature_range": "temperature_band",
            }[args.change]
            start = (
                time_at(args.window_start, p.clock(), end, timezone)
                if args.window_start
                else p.clock()
            )
            finish = (
                time_at(args.window_end, start, end, timezone)
                if args.window_end
                else end
            )
            spec = ConstraintSpec.model_validate(
                dict(
                    kind=change,
                    asset_id=UUID(str(target["id"])),
                    starts_at=start,
                    ends_at=finish,
                    value=args.percent / 100
                    if args.percent is not None
                    else args.temperature_f
                    if args.temperature_f is not None
                    else args.lower_f,
                    upper=args.upper_f,
                    at=time_at(args.at, start, finish, timezone) if args.at else None,
                )
            )
        intake = Intake(
            text=args.text,
            horizon_end=end,
            replaces=replaces,
            spec=spec,
            claimed_author=args.claimed_author,
            kind=args.kind,
        )
        action = governance(
            p,
            "withdraw_constraint"
            if args.operation == "remove"
            else "record_constraint",
            intake.model_dump(mode="json"),
            self.principal,
        )
        await prepare(
            p,
            action.model_copy(
                update={"requested_by": await p.requester(self.principal)}
            ),
            p.clock(),
            self.principal,
        )
        decision = await p.mutate_locked(action, self.principal)
        if decision.decision != "execute":
            return response(
                "The household rules did not accept this constraint.",
                status="denied",
                decision=decision,
            )
        descriptions = {
            "car_target": f"The car target is {args.percent:g} percent."
            if args.percent is not None
            else "",
            "car_limit": f"The car limit is {args.percent:g} percent."
            if args.percent is not None
            else "",
            "temperature": f"The temperature request is {args.temperature_f:g} degrees."
            if args.temperature_f is not None
            else "",
            "temperature_range": f"The temperature range is {args.lower_f:g} to {args.upper_f:g} degrees."
            if args.lower_f is not None and args.upper_f is not None
            else "",
        }
        if spec and spec.at:
            label = {
                "charge_after": "The car's earliest charging time",
                "car_ready_by": "The car's requested ready time",
                "appliance_after": "The appliance's earliest start time",
                "appliance_ready_by": "The appliance's requested ready time",
            }[args.change]
            descriptions[args.change] = (
                f"{label} is {local_time(spec.at, context(snapshot))}."
            )
        headline = (
            "The constraint was removed."
            if args.operation == "remove"
            else descriptions.get(
                args.change, "Your temporary planning constraint is recorded."
            )
        )
        return response(
            headline,
            details=("The affected plan is updating.",) if stored else (),
            status="recorded",
            decision=decision,
            constraint_id=str(uuid5(p.household_id, action.action_id))
            if spec
            else None,
        )

    async def approve(self, args: ApprovalInput) -> Result:
        p = self.p
        if args.plan_id:
            stored = await get(p, args.plan_id)
            plan = Plan.model_validate(stored["document"])
            if (
                plan.version != args.version
                or plan.status in {"superseded", "abandoned", "completed"}
                or (
                    args.approved
                    and (plan.status == "refreshing" or not await fresh(p, stored))
                )
            ):
                return response(
                    "The plan is still updating or has changed. Review the current version before approving.",
                    status="denied",
                    code="PLAN_CHANGED",
                )
            if args.action_id is None:
                decision = (
                    await PlanService(p).approve_locked(
                        args.plan_id, self.principal, version=args.version
                    )
                    if args.approved
                    else await p.mutate_locked(
                        governance(
                            p, "cancel_plan", {"plan_id": args.plan_id}, self.principal
                        ),
                        self.principal,
                    )
                )
                return response(
                    "Your response to that plan was recorded.", decision=decision
                )
        assert args.action_id and args.approval_id
        pending = await p.approval(args.approval_id)
        row = (
            (
                await p.connection.execute(
                    sa.select(db.actions).where(
                        p.scope(db.actions), db.actions.c.action_id == args.action_id
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if (
            pending is None
            or row is None
            or pending["action_id"] != args.action_id
            or row["proposal"].get("plan_id") != args.plan_id
        ):
            raise ValueError("That approval is unavailable for this request.")
        action = Action.model_validate(row["proposal"])
        if action.action_class.startswith("security."):
            return response(
                "Phone approval is required and unavailable in this preview. The door request remains unresolved.",
                status="phone_required",
            )
        decision = await p.vote_locked(
            args.approval_id, self.principal, approved=args.approved
        )
        if args.plan_id:
            await RefreshService(p).command(
                Principal.model_validate(row["principal"]),
                dict(
                    plan_id=args.plan_id,
                    operation="resume",
                    action_id=args.action_id,
                    approval_id=args.approval_id,
                ),
                locked=True,
            )
        elif args.approved and decision.event_type.value == "APPROVED":
            decision = await p.mutate_locked(
                action,
                Principal.model_validate(row["principal"]),
                approval_id=args.approval_id,
                enqueue=action.action_class != "environment.comfort_profile",
            )
            if (
                action.action_class == "environment.comfort_profile"
                and decision.decision == "execute"
            ):
                return await self.expand_profile(
                    action, Principal.model_validate(row["principal"]), decision
                )
        return response("Your response to that action was recorded.", decision=decision)

    async def audit(self, args: AuditInput, snapshot: ContextSnapshot) -> Result:
        p = self.p
        start, end = audit_window(
            p.clock(), str(snapshot.data["households"][0]["timezone"]), args.window
        )
        binding = digest(
            {
                "household": str(p.household_id),
                "window": args.window,
                "action": args.action_id,
            }
        )
        cursor = None
        if args.cursor:
            try:
                raw = base64.urlsafe_b64decode(args.cursor.encode())
                if raw[:16] != bytes.fromhex(binding[:32]):
                    raise ValueError
                cursor, first, last = struct.unpack("!Qdd", raw[16:])
                start, end = (
                    datetime.fromtimestamp(first, UTC),
                    datetime.fromtimestamp(last, UTC),
                )
            except (ValueError, KeyError, TypeError, struct.error, OverflowError):
                raise ValueError(
                    "That history cursor is invalid for this request."
                ) from None
        query = sa.select(db.audit_log).where(p.scope(db.audit_log))
        query = (
            query.where(db.audit_log.c.payload["action_id"].astext == args.action_id)
            if args.action_id
            else query.where(
                db.audit_log.c.created_at >= start, db.audit_log.c.created_at <= end
            )
        )
        if cursor is not None:
            query = query.where(db.audit_log.c.seq < cursor)
        rows = (
            (
                await p.connection.execute(
                    query.order_by(db.audit_log.c.seq.desc()).limit(args.limit + 1)
                )
            )
            .mappings()
            .all()
        )
        # No raw audit payload: checks, claims, channel hashes and proposal text are private.
        summaries = {
            "EXECUTED": "A device command completed.",
            "VERIFIED": "A device setting was checked.",
            "CONSTITUTION_PROPOSED": "A household rule was proposed.",
            "CONSTRAINT_RECORDED": "A planning constraint was recorded.",
            "AUTONOMY_PAUSED": "Household automation was paused.",
            "PLAN_CREATED": "A plan was prepared.",
            "PLAN_APPROVED": "A plan received consent.",
            "DRY_RUN": "A permission preview was requested.",
        }
        items = tuple(
            AuditSummary(
                at=r["created_at"].isoformat(),
                summary=summaries.get(
                    r["event_type"], "A household request was evaluated."
                ),
                action_id=r["payload"].get("action_id"),
            )
            for r in rows[: args.limit]
        )
        token = (
            base64.urlsafe_b64encode(
                bytes.fromhex(binding[:32])
                + struct.pack(
                    "!Qdd",
                    rows[args.limit - 1]["seq"],
                    start.timestamp(),
                    end.timestamp(),
                )
            ).decode()
            if len(rows) > args.limit
            else None
        )
        return response(
            "Here are the most recent household activity summaries.",
            audit=items,
            cursor=token,
        )
