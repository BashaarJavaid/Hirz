"""Internal deterministic pipeline. No authentication endpoint or device executor."""

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from hirz import db
from hirz.constitution.boundary import BoundaryResult, Dogwood, Event
from hirz.constitution.compiler import Compiled, boundary_input, compile_policy
from hirz.constitution.conditions import PolicyFacts
from hirz.constitution.evaluator import RuleOutcome, resolve
from hirz.constitution.schema import Constitution
from hirz.graph.context import ContextSnapshot, validate_snapshot
from hirz.graph.models import Household, now, utc
from hirz.graph.repository import GraphRepository, snapshot_sql
from hirz.pipeline.audit import AuditWriter, PipelineError
from hirz.pipeline.context import ContextError, Facts, extract
from hirz.pipeline.hashing import digest, ingest, wire
from hirz.pipeline.models import (
    Action,
    ApprovalEvidence,
    BoundaryEvidence,
    BudgetEvidence,
    ConstitutionEvidence,
    Decision,
    EventType,
    Principal,
    Requester,
    Role,
    SupplementalEvidence,
)
from hirz.pipeline.preview import PreviewEvidence, overlay
from hirz.risk import RiskBand
from hirz.risk.engine import RiskFacts, score

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PolicyBundle:
    household_id: UUID
    policy_json: str
    compiled: Compiled
    fingerprint: str

    @classmethod
    async def validate(
        cls, household_id: UUID, policy: Constitution, boundary: Dogwood
    ) -> "PolicyBundle":
        policy = Constitution.model_validate(policy.model_dump())
        compiled = compile_policy(policy)
        await boundary.validate(compiled)
        return cls(
            household_id,
            policy.model_dump_json(),
            compiled,
            digest(
                {
                    "policy": policy.model_dump(mode="json"),
                    "compiled": compiled.policy,
                    "schema": compiled.schema,
                    "manifest": compiled.manifest,
                }
            ),
        )

    def policy(self) -> Constitution:
        policy = Constitution.model_validate_json(self.policy_json)
        if self.fingerprint != digest(
            {
                "policy": policy.model_dump(mode="json"),
                "compiled": self.compiled.policy,
                "schema": self.compiled.schema,
                "manifest": self.compiled.manifest,
            }
        ):
            raise PipelineError("Policy bundle changed after validation")
        return policy


@dataclass
class Evaluation:
    decision: Decision
    action: Action
    outcomes: tuple[RuleOutcome, ...]
    facts: Facts | None
    gates: dict[str, Any]
    diagnostics: tuple[str, ...] = ()


def result(evaluation: Evaluation, event: EventType) -> Evaluation:
    kind = (
        "execute"
        if event == EventType.EXECUTE
        else "verify"
        if event == EventType.VERIFY
        else "ask"
        if event.value.startswith("ASK_")
        else "deny"
    )
    return replace(
        evaluation,
        decision=evaluation.decision.model_copy(
            update={"event_type": event, "decision": kind}
        ),
    )


def identity(principal: Principal) -> dict[str, Any]:
    return principal.model_dump(
        exclude={"passkey_verified", "requester_confirmed", "verified_action_hash"}
    )


def estimate(cost: Decimal | None) -> str | None:
    if cost is None:
        return None
    if not isinstance(cost, Decimal) or not cost.is_finite() or cost < 0:
        raise ValueError("Cost must be a nonnegative exact Decimal")
    return format(abs(cost) if cost == 0 else cost, "f")


class Pipeline:
    def __init__(
        self,
        connection: AsyncConnection,
        bundle: PolicyBundle,
        boundary: Dogwood,
        audit: AuditWriter,
        clock: Callable[[], datetime] = now,
    ):
        self.connection, self.bundle, self.boundary, self.audit, self.clock = (
            connection,
            bundle,
            boundary,
            audit,
            clock,
        )
        self.household_id = bundle.household_id
        self.repo = GraphRepository(connection, self.household_id)

    def scope(self, table: sa.Table) -> sa.ColumnElement[bool]:
        return table.c.household_id == self.household_id

    async def snapshot(self, at: datetime) -> ContextSnapshot:
        row = (
            (
                await self.connection.execute(
                    sa.text(snapshot_sql() + " WHERE h.id = :household_id"),
                    {"household_id": self.household_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise PipelineError("Household unavailable")
        return ContextSnapshot(
            household_id=self.household_id,
            scope="all",
            as_of=at,
            read_at=at,
            stale=False,
            staleness_seconds=0,
            policy_status="unvalidated",
            data=validate_snapshot(row["data"], self.household_id, at),
        )

    async def requester(self, principal: Principal) -> Requester:
        row = (
            await self.connection.execute(
                sa.select(db.members.c.id, db.members.c.role)
                .join(
                    db.member_accounts,
                    sa.and_(
                        db.members.c.household_id == db.member_accounts.c.household_id,
                        db.members.c.id == db.member_accounts.c.member_id,
                    ),
                )
                .where(
                    self.scope(db.members),
                    db.member_accounts.c.provider == principal.provider,
                    db.member_accounts.c.sub == principal.sub,
                )
            )
        ).one_or_none()
        return Requester(
            member_id=str(row.id) if row else None,
            role=cast(Role, row.role) if row else "unknown",
            surface=principal.surface,
        )

    async def usage(self, name: str, local_date: str) -> Decimal:
        rows = (
            await self.connection.execute(
                sa.select(db.audit_log.c.payload)
                .join(
                    db.actions,
                    sa.and_(
                        db.actions.c.household_id == db.audit_log.c.household_id,
                        db.actions.c.grant_seq == db.audit_log.c.seq,
                    ),
                )
                .where(self.scope(db.audit_log))
            )
        ).scalars()
        return sum(
            (
                Decimal(b["reserved"])
                for p in rows
                if (b := p.get("budget"))
                and b["class"] == name
                and b["local_date"] == local_date
            ),
            Decimal(0),
        )

    async def assess(
        self,
        action: Action,
        principal: Principal,
        cost: Decimal | None,
        evidence: tuple[SupplementalEvidence, ...],
        at: datetime,
        *,
        preview: PreviewEvidence | None = None,
    ) -> Evaluation:
        policy = self.bundle.policy()
        requester = await self.requester(principal)
        action = action.model_copy(update={"requested_by": requester})
        roles = tuple(
            dict.fromkeys((requester.role, principal.claimed_role or requester.role))
        )
        variants = tuple(
            action.model_copy(
                update={"requested_by": requester.model_copy(update={"role": r})}
            )
            for r in roles
        )
        initial = ConstitutionEvidence(
            version=policy.version,
            rule=action.action_class,
            mode="never",
            conditions_met=False,
        )
        ev = Evaluation(
            Decision(
                decision="deny",
                event_type=EventType.DENY_CONSTITUTION,
                action_id=action.action_id,
                constitution=initial,
            ),
            action,
            (),
            None,
            {},
        )
        snapshot = None
        if preview is not None:
            try:
                snapshot = overlay(await self.snapshot(at), preview)
                if preview.scam_pattern is not None:
                    evidence = (*evidence, preview.scam_pattern)
            except ValueError:
                return replace(ev, diagnostics=("context",))
        # Explicit NEVER does not require context or invoke risk scoring.
        if any(
            policy.role_mode(action.action_class, role) == "never" for role in roles
        ):
            return ev
        snapshot = snapshot or await self.snapshot(at)
        local_date = at.astimezone(
            ZoneInfo(str(snapshot.data["households"][0]["timezone"]))
        ).date()
        used = await self.usage(action.action_class, local_date.isoformat())
        try:
            facts = extract(snapshot, policy, action, evidence, used)
        except (ContextError, ValueError):
            return replace(ev, diagnostics=("context",))
        ev.facts = facts
        governance = action.action_class.startswith("governance.")
        if (
            governance
            and action.action_class.endswith("resume_automation")
            and principal.surface != "app"
        ):
            return ev
        early = tuple(
            resolve(policy, v, facts.policy, hard_only=True) for v in variants
        )
        if any(o.effective_mode == "never" for o in early):
            ev.diagnostics = tuple(
                sorted(
                    {
                        p
                        for o in early
                        for d in o.diagnostics
                        if d.code == "POLICY_ERROR"
                        for p in d.paths
                    }
                )
            )
            return ev
        risk = score(
            action,
            RiskFacts(observation_ages_seconds=()) if governance else facts.risk,
            policy.rule(action.action_class, requester.role),
        )
        values = dict(facts.policy.values) | {
            "risk": {
                "band": risk.band.value,
                "factors": [f.factor for f in risk.factors],
            },
            "requester": {"claimed_role": principal.claimed_role},
        }
        facts = replace(facts, policy=replace(facts.policy, values=values))
        outcomes = tuple(resolve(policy, v, facts.policy) for v in variants)
        worst = max(
            outcomes, key=lambda o: {"auto": 0, "ask": 1, "never": 2}[o.effective_mode]
        )
        ev = replace(
            ev,
            facts=facts,
            outcomes=outcomes,
            decision=ev.decision.model_copy(
                update={
                    "risk": risk,
                    "constitution": ConstitutionEvidence(
                        version=policy.version,
                        rule=action.action_class,
                        mode=worst.effective_mode,
                        conditions_met=all(o.conditions_met for o in outcomes),
                    ),
                }
            ),
            diagnostics=tuple(
                sorted(
                    {
                        p
                        for o in outcomes
                        for d in o.diagnostics
                        if d.code == "POLICY_ERROR"
                        for p in d.paths
                    }
                )
            ),
        )
        if any(o.effective_mode == "never" for o in outcomes):
            return ev
        if risk.band == RiskBand.CRITICAL:
            return result(
                ev,
                EventType.VERIFY
                if action.action_class == "finance.verify_request"
                else EventType.DENY_RISK,
            )
        if (
            action.action_class in policy.verification.require_requester_confirmation
            and not principal.requester_confirmed
        ):
            return result(ev, EventType.ASK_REQUESTER_CONFIRMATION)
        if ev.diagnostics:
            return result(ev, EventType.ASK_UNRESOLVED_CONDITION)
        gates: dict[str, Any] = {}
        if any(o.effective_mode == "ask" for o in outcomes):
            gates["constitution"] = [
                str(i) for i, o in enumerate(outcomes) if o.effective_mode == "ask"
            ]
        if not governance and facts.paused:
            gates["pause"] = True
        if risk.band == RiskBand.HIGH:
            gates["risk"] = [f.factor for f in risk.factors]
        if not governance and facts.quiet:
            gates["quiet"] = True
        budget = worst.budget
        if budget and not governance:
            ev.decision = ev.decision.model_copy(
                update={
                    "budget": BudgetEvidence(
                        local_date=local_date,
                        action_class=action.action_class,
                        used=used,
                        proposed=cost,
                        cap=budget.usd_per_day,
                    )
                }
            )
            if cost is None or used + cost > budget.usd_per_day:
                return result(ev, EventType.DENY_BUDGET)
            if used + cost == budget.usd_per_day:
                gates["budget"] = True
        # Facts behind a soft gate, not just the first displayed ASK, bind approval.
        if gates:
            gates["risk_band"] = list(RiskBand).index(risk.band)
            gates["risk_factors"] = sorted(f.factor for f in risk.factors)
            gates["conditions"] = [
                str(i) for i, o in enumerate(outcomes) if not o.conditions_met
            ]
        ev.gates = gates
        if "constitution" in gates or "pause" in gates:
            return result(ev, EventType.ASK_CONSTITUTION)
        if "risk" in gates:
            return result(ev, EventType.ASK_RISK)
        if "budget" in gates:
            return result(ev, EventType.ASK_BUDGET)
        if "quiet" in gates:
            return result(ev, EventType.ASK_CONSTITUTION)
        return result(ev, EventType.EXECUTE)

    async def boundary_check(
        self,
        ev: Evaluation,
        at: datetime,
        approval: dict[str, Any] | None = None,
        voter: Principal | None = None,
    ) -> Evaluation:
        assert ev.facts is not None
        roles = tuple(
            dict.fromkeys(
                (
                    ev.action.requested_by.role,
                    *(
                        [
                            cast(
                                Role,
                                ev.facts.policy.values["requester"]["claimed_role"],
                            )
                        ]
                        if ev.facts.policy.values["requester"].get("claimed_role")
                        else []
                    ),
                )
            )
        )
        results: dict[Role, bool] = {}
        approver = await self.requester(voter) if voter else None
        context_hash = "sha256:" + digest(ev.facts.policy.values)
        for role in roles:
            action = ev.action.model_copy(
                update={
                    "requested_by": ev.action.requested_by.model_copy(
                        update={"role": role}
                    )
                }
            )
            inputs = boundary_input(
                self.bundle.compiled,
                action,
                ev.facts.policy,
                ttl_minutes=ev.outcomes[0].approval.ttl_minutes,
                session_id=str(self.household_id) + ":" + action.action_id,
                approver_role=approver.role if approver else "",
                approval_channel=("app_push" if voter.surface == "app" else "alexa")
                if voter
                else "",
                quorum_satisfied=approval is not None,
            )
            events = (
                (
                    Event(
                        int(approval["approved_at"].timestamp()),
                        "governance.approve_action",
                        inputs,
                    ),
                )
                if approval
                else ()
            )
            try:
                answer = await self.boundary.authorize(
                    self.bundle.compiled,
                    Event(int(at.timestamp()), action.action_class, inputs),
                    events,
                )
                allowed = (
                    isinstance(answer, BoundaryResult)
                    and answer.allowed is True
                    and answer.engine == "dogwood-local"
                )
            except Exception:
                allowed = False
            results[role] = allowed
        ev.decision = ev.decision.model_copy(
            update={
                "boundary": BoundaryEvidence(
                    result="allow" if all(results.values()) else "deny",
                    reason="Both evaluators must permit",
                    context_hash=context_hash,
                    roles=results,
                )
            }
        )
        return result(
            ev, EventType.EXECUTE if all(results.values()) else EventType.DENY_BOUNDARY
        )

    async def evaluate(
        self,
        action: Action,
        principal: Principal,
        *,
        cost: Decimal | None = None,
        evidence: tuple[SupplementalEvidence, ...] = (),
        preview: PreviewEvidence | None = None,
    ) -> Decision:
        action, principal = (
            ingest(action),
            Principal.model_validate(principal.model_dump()),
        )
        estimate(cost)
        if self.connection.in_transaction():
            raise PipelineError("Pipeline requires an idle connection")
        try:
            # Read-only transaction also serializes against graph writers; no stale view.
            async with self.repo.write(self.clock):
                ev = await self.assess(
                    action,
                    principal,
                    cost,
                    evidence,
                    utc(self.clock()),
                    preview=preview,
                )
                if ev.decision.decision == "execute":
                    ev = await self.boundary_check(ev, utc(self.clock()))
                return ev.decision
        except Exception as exc:
            await self.connection.invalidate()
            await self.connection.rollback()
            log.error(
                "Pipeline.evaluate household=%s error=%s",
                self.household_id,
                type(exc).__name__,
            )
            raise PipelineError(
                "Pipeline evaluation failed; no authorization returned"
            ) from None

    async def record(self, ev: Evaluation, at: datetime) -> Decision:
        for path in ev.diagnostics:
            await self.audit.append(
                self.connection,
                self.household_id,
                at,
                EventType.POLICY_ERROR,
                {"paths": [path]},
            )
        seq = await self.audit.append(
            self.connection, self.household_id, at, ev.decision.event_type, ev.decision
        )
        return ev.decision.model_copy(update={"audit_id": seq})

    def binding(
        self, action: Action, principal: Principal, cost: Decimal | None, ev: Evaluation
    ) -> dict[str, Any]:
        return {
            "hash": action.content_hash,
            "requester": identity(principal),
            "resolved_requester": ev.action.requested_by.model_dump(),
            "cost": estimate(cost),
            "policy": self.bundle.fingerprint,
            "gates": wire(ev.gates),
        }

    async def pending(self, action_id: str) -> dict[str, Any] | None:
        row = (
            (
                await self.connection.execute(
                    sa.select(db.approvals)
                    .where(
                        self.scope(db.approvals),
                        db.approvals.c.action_id == action_id,
                        db.approvals.c.status.in_(["pending", "approved"]),
                    )
                    .with_for_update()
                )
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row else None

    async def status(self, approval: dict[str, Any], status: str) -> None:
        await self.connection.execute(
            db.approvals.update()
            .where(
                self.scope(db.approvals),
                db.approvals.c.approval_id == approval["approval_id"],
            )
            .values(status=status)
        )
        approval["status"] = status

    async def ask(
        self,
        ev: Evaluation,
        action: Action,
        principal: Principal,
        cost: Decimal | None,
        at: datetime,
    ) -> Evaluation:
        if ev.decision.decision != "ask" or ev.decision.event_type in {
            EventType.ASK_UNRESOLVED_CONDITION,
            EventType.ASK_REQUESTER_CONFIRMATION,
        }:
            return ev
        binding = self.binding(action, principal, cost, ev)
        pending = await self.pending(action.action_id)
        if pending and (
            at >= pending["expires_at"]
            or not self.compatible(pending["binding"], binding)
        ):
            await self.status(pending, "expired")
            await self.audit.append(
                self.connection,
                self.household_id,
                at,
                EventType.EXPIRED,
                {"approval_id": pending["approval_id"]},
            )
            pending = None
        if pending is None:
            pending = {
                "household_id": self.household_id,
                "action_id": action.action_id,
                "approval_id": "apr_" + uuid4().hex,
                "status": "pending",
                "binding": binding,
                "created_at": at,
                "expires_at": at
                + timedelta(minutes=ev.outcomes[0].approval.ttl_minutes),
            }
            await self.connection.execute(db.approvals.insert().values(**pending))
        ev.decision = ev.decision.model_copy(
            update={
                "approval": ApprovalEvidence(
                    approval_id=pending["approval_id"],
                    quorum=ev.outcomes[0].approval.quorum,
                    expires_at=pending["expires_at"],
                )
            }
        )
        return ev

    @staticmethod
    def compatible(old: dict[str, Any], new: dict[str, Any]) -> bool:
        if any(old[k] != new[k] for k in new if k != "gates"):
            return False
        for key, value in new["gates"].items():
            previous = old["gates"].get(key)
            if previous is None:
                return False
            if isinstance(value, list):
                if not set(value) <= set(previous):
                    return False
            elif key == "risk_band":
                if value > previous:
                    return False
            elif value != previous:
                return False
        return True

    async def proposal(
        self, action: Action, principal: Principal, cost: Decimal | None
    ) -> tuple[bool, int | None, Action]:
        row = (
            (
                await self.connection.execute(
                    sa.select(db.actions)
                    .where(
                        self.scope(db.actions),
                        db.actions.c.action_id == action.action_id,
                    )
                    .with_for_update()
                )
            )
            .mappings()
            .one_or_none()
        )
        serialized = action.model_dump(mode="json", by_alias=True)
        if row:
            return (
                (
                    row["proposal"] == serialized
                    and row["principal"] == identity(principal)
                    and row["cost"] == estimate(cost)
                ),
                row["grant_seq"],
                ingest(Action.model_validate(row["proposal"])),
            )
        await self.connection.execute(
            db.actions.insert().values(
                household_id=self.household_id,
                action_id=action.action_id,
                proposal=serialized,
                principal=identity(principal),
                cost=estimate(cost),
            )
        )
        return True, None, action

    async def propose(
        self,
        action: Action,
        principal: Principal,
        *,
        cost: Decimal | None = None,
        evidence: tuple[SupplementalEvidence, ...] = (),
    ) -> Decision:
        return await self.mutate(action, principal, cost, evidence, redeem=False)

    async def redeem(
        self,
        action: Action,
        principal: Principal,
        *,
        cost: Decimal | None = None,
        evidence: tuple[SupplementalEvidence, ...] = (),
        approval_id: str | None = None,
    ) -> Decision:
        return await self.mutate(
            action, principal, cost, evidence, redeem=True, approval_id=approval_id
        )

    async def eligible_votes(
        self, approval: dict[str, Any], ev: Evaluation
    ) -> tuple[bool, Principal | None]:
        requirements = ev.outcomes[0].approval
        eligible = set(
            (
                await self.connection.execute(
                    sa.select(db.members.c.id).where(
                        self.scope(db.members),
                        db.members.c.role.in_(requirements.approver_roles),
                    )
                )
            ).scalars()
        )
        rows = (
            await self.connection.execute(
                sa.select(db.approval_votes).where(
                    self.scope(db.approval_votes),
                    db.approval_votes.c.approval_id == approval["approval_id"],
                )
            )
        ).mappings()
        accepted: dict[UUID, Principal] = {}
        vote_times: list[datetime] = []
        for row in rows:
            voter = Principal.model_validate(row["principal"])
            member = await self.requester(voter)
            if (
                row["member_id"] in eligible
                and str(row["member_id"]) == member.member_id
                and self.channel_allowed(voter, ev)
            ):
                if not row["approved"]:
                    return False, None
                accepted[row["member_id"]] = voter
                vote_times.append(row["created_at"])
        satisfied = bool(eligible) and (
            eligible <= accepted.keys()
            if requirements.quorum == "all_adults"
            else bool(accepted)
        )
        if satisfied:
            approval["approved_at"] = max(vote_times)
        return satisfied, next(iter(accepted.values()), None)

    @staticmethod
    def channel_allowed(principal: Principal, ev: Evaluation) -> bool:
        channel = "app_push" if principal.surface == "app" else "alexa"
        return (
            principal.surface != "scheduler"
            and channel in ev.outcomes[0].approval.channels
            and (
                principal.claimed_role is None
                or principal.claimed_role in ev.outcomes[0].approval.approver_roles
            )
            and (
                not ev.action.action_class.startswith("security.")
                or principal.surface == "app"
                and principal.passkey_verified
                and principal.verified_action_hash == ev.action.content_hash
            )
        )

    async def mutate(
        self,
        action: Action,
        principal: Principal,
        cost: Decimal | None,
        evidence: tuple[SupplementalEvidence, ...],
        *,
        redeem: bool,
        approval_id: str | None = None,
    ) -> Decision:
        action, principal = (
            ingest(action),
            Principal.model_validate(principal.model_dump()),
        )
        estimate(cost)
        if self.connection.in_transaction():
            raise PipelineError("Pipeline requires an idle connection")
        try:
            async with self.repo.write(self.clock):
                at = utc(self.clock())
                matched, granted, stored = await self.proposal(action, principal, cost)
                ev = await self.assess(
                    stored if matched else action, principal, cost, evidence, at
                )
                if not matched:
                    ev = result(ev, EventType.DENY_APPROVAL_MISMATCH)
                elif granted is not None:
                    ev = result(ev, EventType.DENY_APPROVAL_USED)
                elif redeem:
                    ev = await self.authorize(
                        ev, action, principal, cost, at, approval_id
                    )
                else:
                    if ev.decision.decision == "execute":
                        ev = await self.boundary_check(ev, at)
                    ev = await self.ask(ev, action, principal, cost, at)
                return (
                    await self.record(ev, at)
                    if ev.decision.audit_id is None
                    else ev.decision
                )
        except Exception as exc:
            # A failed COMMIT hook/connection can leave a physical transaction open
            # after SQLAlchemy has closed its transaction object. Discard it.
            await self.connection.invalidate()
            await self.connection.rollback()
            if isinstance(exc, PipelineError):
                raise
            log.error(
                "Pipeline.mutate household=%s error=%s",
                self.household_id,
                type(exc).__name__,
            )
            raise PipelineError(
                "Pipeline transaction failed; no authorization returned"
            ) from None

    async def authorize(
        self,
        ev: Evaluation,
        action: Action,
        principal: Principal,
        cost: Decimal | None,
        at: datetime,
        approval_id: str | None,
    ) -> Evaluation:
        approval = None
        voter = None
        if ev.decision.decision == "deny":
            return ev
        if approval_id:
            row = (
                (
                    await self.connection.execute(
                        sa.select(db.approvals)
                        .where(
                            self.scope(db.approvals),
                            db.approvals.c.approval_id == approval_id,
                        )
                        .with_for_update()
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None or row["action_id"] != action.action_id:
                return result(ev, EventType.DENY_APPROVAL_MISMATCH)
            approval = dict(row)
            if approval["status"] == "redeemed":
                return result(ev, EventType.DENY_APPROVAL_USED)
            if at >= approval["expires_at"] or approval["status"] == "expired":
                await self.status(approval, "expired")
                return result(ev, EventType.DENY_APPROVAL_EXPIRED)
            if approval["status"] == "rejected":
                return result(ev, EventType.DENY_APPROVAL_UNAUTHORIZED)
        if ev.decision.decision in {"deny", "verify"} or ev.decision.event_type in {
            EventType.ASK_REQUESTER_CONFIRMATION,
            EventType.ASK_UNRESOLVED_CONDITION,
        }:
            return ev
        if approval:
            current = self.binding(action, principal, cost, ev)
            if not self.compatible(approval["binding"], current):
                await self.status(approval, "expired")
                return await self.ask(
                    result(ev, EventType.ASK_CONSTITUTION), action, principal, cost, at
                )
            satisfied, voter = await self.eligible_votes(approval, ev)
            if not satisfied:
                return result(ev, EventType.DENY_APPROVAL_UNAUTHORIZED)
        elif ev.decision.decision == "ask":
            return await self.ask(ev, action, principal, cost, at)
        ev = await self.boundary_check(ev, at, approval, voter)
        if ev.decision.decision != "execute":
            return ev
        # Recheck the Python deadline after the native boundary call too.
        if approval and utc(self.clock()) >= approval["expires_at"]:
            await self.status(approval, "expired")
            return result(ev, EventType.DENY_APPROVAL_EXPIRED)
        if ev.decision.budget:
            ev.decision = ev.decision.model_copy(
                update={
                    "budget": ev.decision.budget.model_copy(update={"reserved": cost})
                }
            )
        ev.decision = await self.record(ev, at)
        await self.connection.execute(
            db.actions.update()
            .where(self.scope(db.actions), db.actions.c.action_id == action.action_id)
            .values(grant_seq=ev.decision.audit_id)
        )
        if approval:
            await self.status(approval, "redeemed")
        if action.action_class.startswith("governance."):
            paused = action.action_class.endswith("pause_automation")
            current_home = await self.repo.get("households", {})
            assert current_home is not None
            from hirz.graph.repository import row_model

            home = cast(Household, row_model("households", current_home))
            if home.autonomy_paused != paused:
                await self.repo.put(
                    "households",
                    home.model_copy(update={"autonomy_paused": paused}),
                    expected_version=current_home["valid_from"],
                )
                await self.audit.append(
                    self.connection,
                    self.household_id,
                    at,
                    EventType.AUTONOMY_PAUSED if paused else EventType.AUTONOMY_RESUMED,
                    {"action_id": action.action_id},
                )
        return ev

    async def vote(
        self, approval_id: str, principal: Principal, *, approved: bool
    ) -> Decision:
        principal = Principal.model_validate(principal.model_dump())
        if type(approved) is not bool:
            raise ValueError("A Boolean vote is required")
        if self.connection.in_transaction():
            raise PipelineError("Pipeline requires an idle connection")
        try:
            async with self.repo.write(self.clock):
                at = utc(self.clock())
                row = (
                    (
                        await self.connection.execute(
                            sa.select(db.approvals)
                            .where(
                                self.scope(db.approvals),
                                db.approvals.c.approval_id == approval_id,
                            )
                            .with_for_update()
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is None:
                    policy = self.bundle.policy()
                    ev = Evaluation(
                        Decision(
                            decision="deny",
                            event_type=EventType.DENY_APPROVAL_MISMATCH,
                            action_id="unknown",
                            constitution=ConstitutionEvidence(
                                version=policy.version,
                                rule="unknown",
                                mode="never",
                                conditions_met=False,
                            ),
                        ),
                        cast(Action, None),
                        (),
                        None,
                        {},
                    )
                    return await self.record(ev, at)
                approval = dict(row)
                stored = (
                    (
                        await self.connection.execute(
                            sa.select(db.actions).where(
                                self.scope(db.actions),
                                db.actions.c.action_id == approval["action_id"],
                            )
                        )
                    )
                    .mappings()
                    .one()
                )
                action = ingest(Action.model_validate(stored["proposal"]))
                # Voting does not require resubmitting observations; current eligibility
                # and channels are checked here, all current gates at redemption.
                policy = self.bundle.policy()
                requester = await self.requester(
                    Principal.model_validate(stored["principal"])
                )
                outcome = resolve(
                    policy,
                    action.model_copy(update={"requested_by": requester}),
                    PolicyFacts(policy.household, at, {}),
                )
                ev = Evaluation(
                    Decision(
                        decision="ask",
                        event_type=EventType.ASK_CONSTITUTION,
                        action_id=action.action_id,
                        constitution=ConstitutionEvidence(
                            version=policy.version,
                            rule=action.action_class,
                            mode=outcome.effective_mode,
                            conditions_met=False,
                        ),
                    ),
                    action,
                    (outcome,),
                    None,
                    {},
                )
                member = await self.requester(principal)
                event = EventType.APPROVED if approved else EventType.REJECTED
                if approval["status"] == "redeemed":
                    event = EventType.DENY_APPROVAL_USED
                elif at >= approval["expires_at"] or approval["status"] == "expired":
                    await self.status(approval, "expired")
                    event = EventType.DENY_APPROVAL_EXPIRED
                elif (
                    approval["status"] == "rejected"
                    or member.role not in outcome.approval.approver_roles
                    or not self.channel_allowed(principal, ev)
                ):
                    event = EventType.DENY_APPROVAL_UNAUTHORIZED
                else:
                    existing = await self.connection.scalar(
                        sa.select(db.approval_votes.c.approved).where(
                            self.scope(db.approval_votes),
                            db.approval_votes.c.approval_id == approval_id,
                            db.approval_votes.c.member_id
                            == UUID(cast(str, member.member_id)),
                        )
                    )
                    if existing is None:
                        await self.connection.execute(
                            db.approval_votes.insert().values(
                                household_id=self.household_id,
                                approval_id=approval_id,
                                member_id=UUID(cast(str, member.member_id)),
                                approved=approved,
                                principal=principal.model_dump(mode="json"),
                                created_at=at,
                            )
                        )
                        await self.audit.append(
                            self.connection,
                            self.household_id,
                            at,
                            event,
                            {
                                "approval_id": approval_id,
                                "member_id": member.member_id,
                                "action_hash": action.content_hash,
                                "approved": approved,
                                "surface": principal.surface,
                                "passkey_verified": principal.passkey_verified,
                                "verified_action_hash": principal.verified_action_hash,
                            },
                        )
                        satisfied, _ = await self.eligible_votes(approval, ev)
                        await self.status(
                            approval,
                            "rejected"
                            if not approved
                            else "approved"
                            if satisfied
                            else "pending",
                        )
                    else:
                        approved = existing
                        event = EventType.APPROVED if approved else EventType.REJECTED
                ev.decision = ev.decision.model_copy(
                    update={
                        "approval": ApprovalEvidence(
                            approval_id=approval_id,
                            quorum=outcome.approval.quorum,
                            expires_at=approval["expires_at"],
                        )
                    }
                )
                # A vote is not an execution authorization.
                ev = result(ev, event)
                if event in {EventType.APPROVED, EventType.REJECTED}:
                    ev.decision = ev.decision.model_copy(
                        update={"decision": "ask" if approved else "deny"}
                    )
                return await self.record(ev, at)
        except Exception as exc:
            # A failed COMMIT hook/connection can leave a physical transaction open
            # after SQLAlchemy has closed its transaction object. Discard it.
            await self.connection.invalidate()
            await self.connection.rollback()
            if isinstance(exc, PipelineError):
                raise
            log.error(
                "Pipeline.vote household=%s error=%s",
                self.household_id,
                type(exc).__name__,
            )
            raise PipelineError(
                "Pipeline transaction failed; no authorization returned"
            ) from None
