"""Authenticated, single-selected playback over actual runtime services."""

import asyncio
import time
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Literal

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from hirz import db
from hirz.companion.api import Companion
from hirz.companion.governance import household
from hirz.executor.local import compose
from hirz.executor.local import policy as reload_policy
from hirz.executor.observations import ingest
from hirz.executor.refresh_worker import RefreshWorker
from hirz.executor.service import Executor
from hirz.host.simulator import Simulator, utterance_key
from hirz.mcp.household import HouseholdTools
from hirz.mcp.persistence import command
from hirz.mcp.worker import prepare_plans
from hirz.pipeline.models import Principal, VerificationCase
from hirz.twin.scenario import LoadedScenario


class Control(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: Literal["demo-evening", "parents-scam-check"]
    operation: Literal["select", "next", "play", "pause", "reply"]
    speed: Literal[1, 60] = 60
    reply: Literal["genuine", "not_genuine", "will_call", "no_answer"] | None = None


class Scenarios:
    def __init__(
        self,
        companion: Companion,
        loaded: dict[str, LoadedScenario],
        simulator: Simulator,
    ):
        self.companion, self.loaded, self.simulator = companion, loaded, simulator
        self.beat_started = {name: 0.0 for name in loaded}
        self.selected = "demo-evening"
        self.index = {name: 0 for name in loaded}
        self.beats: dict[str, dict[str, Any] | None] = {name: None for name in loaded}
        self.playing = False
        self.speed = 60
        self.last = time.monotonic()
        self.lock = asyncio.Lock()
        self.failure: str | None = None
        self.checkpoints: dict[str, dict[str, Any]] = {name: {} for name in loaded}

    def view(self) -> dict[str, Any]:
        return {
            "selected": self.selected,
            "playing": self.playing,
            "speed": self.speed,
            "failure": self.failure,
            "scenarios": {
                name: {
                    "at": item.world.clock().isoformat(),
                    "next": self.index[name],
                    "total": len(item.times),
                    "beat": self.beats[name],
                    "source": "twin",
                }
                for name, item in self.loaded.items()
            },
        }

    async def sweep(self, name: str) -> None:
        item = self.loaded[name]
        async with self.companion.pipeline(item.world.household.id) as p:
            async with p.connection.begin():
                status = await p.connection.scalar(
                    sa.select(db.constitution_versions.c.status).where(
                        p.scope(db.constitution_versions),
                        db.constitution_versions.c.version == p.bundle.policy().version,
                    )
                )
            if status != "active":
                return
            principal = Principal(
                provider="demo",
                sub="mom" if name == "parents-scam-check" else "malik",
                surface="scheduler",
            )
            registry = await compose(
                p,
                world=item.world,
                config="presence:twin,energy:"
                + (
                    "scenario" if item.spec.rate_plan == "comed_time_of_day" else "twin"
                ),
                scenario=True,
            )
            await registry.start()
            try:
                await ingest(p, registry, principal)
                await prepare_plans(p, item)
                await RefreshWorker(p, registry, world=item.world).batch()
                await Executor(
                    p,
                    registry,
                    world=item.world,
                    reload_policy=lambda: reload_policy(p),
                    freeze_twin_clock=True,
                ).sweep()
            finally:
                await registry.close()

    async def review(self, name: str) -> bool:
        """Pause simulated time for newly required consent, without granting it."""
        item = self.loaded[name]
        async with self.companion.pipeline(item.world.household.id) as p:
            async with p.connection.begin():
                pending = await p.connection.scalar(
                    sa.select(db.approvals.c.approval_id)
                    .join(
                        db.actions,
                        sa.and_(
                            db.actions.c.household_id == db.approvals.c.household_id,
                            db.actions.c.action_id == db.approvals.c.action_id,
                        ),
                    )
                    .where(
                        p.scope(db.approvals),
                        db.approvals.c.status == "pending",
                        db.approvals.c.expires_at > p.clock(),
                        db.actions.c.proposal["plan_id"].astext.is_not(None),
                    )
                    .limit(1)
                )
                renewed = await p.connection.scalar(
                    sa.select(db.plans.c.plan_id)
                    .where(
                        p.scope(db.plans),
                        db.plans.c.document["status"].astext == "awaiting_approval",
                        db.plans.c.approver.is_not(None),
                    )
                    .limit(1)
                )
        if not pending and not renewed:
            return False
        self.playing = False
        self.beats[name] = {
            "event": "review",
            "member": "malik",
            "text": "What's going on tonight?",
            "response": "Approve the pending action." if pending else "Do it.",
        }
        return True

    async def phone_plan_approved(self, name: str, beat: dict[str, Any]) -> bool:
        """Recognize existing phone consent; never grant or replay an approval."""
        if beat.get("script") != [
            {"tool": "approve_action", "arguments": {"plan": "current"}}
        ]:
            return False
        principal = Principal(provider="demo", sub=beat["member"], surface="app")
        async with self.companion.pipeline(self.loaded[name].world.household.id) as p:
            async with p.connection.begin():
                tools = HouseholdTools(p, principal)
                stored = await tools.current()
                member = await p.requester(principal)
                if (
                    stored is None
                    or stored["document"]["status"] != "approved"
                    or str(stored["member_id"]) != member.member_id
                    or await tools.pending_plan(stored) is not None
                ):
                    return False
                # The current version must have its own committed execute grant,
                # even when a refresh inherited an earlier phone approval.
                consent = await p.connection.scalar(
                    sa.select(db.audit_log.c.payload).where(
                        p.scope(db.audit_log),
                        db.audit_log.c.seq == stored["audit_seq"],
                        db.audit_log.c.event_type == "PLAN_APPROVED",
                        db.audit_log.c.payload["mutation"]["plan_id"].astext
                        == stored["plan_id"],
                    )
                )
                if not consent:
                    return False
                granted = await p.connection.scalar(
                    sa.select(db.audit_log.c.seq).where(
                        p.scope(db.audit_log),
                        db.audit_log.c.seq == consent["decision_seq"],
                        db.audit_log.c.event_type == "EXECUTE",
                        db.audit_log.c.payload["decision"].astext == "execute",
                        db.audit_log.c.payload["action_id"].astext
                        == consent["action_id"],
                    )
                )
                phone = await p.connection.scalar(
                    sa.select(db.audit_log.c.seq)
                    .join(
                        db.plans,
                        sa.and_(
                            db.plans.c.household_id == db.audit_log.c.household_id,
                            db.plans.c.plan_id
                            == db.audit_log.c.payload["mutation"]["plan_id"].astext,
                        ),
                    )
                    .where(
                        p.scope(db.audit_log),
                        db.plans.c.lineage_id == stored["lineage_id"],
                        db.audit_log.c.event_type == "PLAN_APPROVED",
                        db.audit_log.c.payload["surface"].astext == "app",
                        db.audit_log.c.payload["member_id"].astext == member.member_id,
                    )
                    .limit(1)
                )
                return granted is not None and phone is not None

    async def advance(self, name: str, target: datetime) -> bool:
        """Honor action/retry/approval deadlines and the existing five-minute twin poll."""
        item = self.loaded[name]
        while item.world.clock() < target:
            if await self.review(name):
                return False
            current = item.world.clock()
            candidates = [target, current + timedelta(minutes=5)]
            spec = item.spec.execution
            needed_by = (
                item.time(spec.ev_needed_by) if spec and spec.ev_needed_by else None
            )
            if needed_by and current < needed_by <= target:
                candidates.append(needed_by)
            async with self.companion.pipeline(item.world.household.id) as p:
                async with p.connection.begin():
                    for table, column, condition in (
                        (
                            db.actions,
                            db.actions.c.due_at,
                            db.actions.c.execution_status == "scheduled",
                        ),
                        (
                            db.plan_refresh_jobs,
                            db.plan_refresh_jobs.c.next_retry,
                            db.plan_refresh_jobs.c.state == "queued",
                        ),
                        (
                            db.approvals,
                            db.approvals.c.expires_at,
                            db.approvals.c.status == "pending",
                        ),
                    ):
                        deadline = await p.connection.scalar(
                            sa.select(sa.func.min(column)).where(
                                p.scope(table), condition, column > current
                            )
                        )
                        if deadline is not None:
                            candidates.append(deadline)
            item.world.clock.jump(min(candidates))
            item.world.read()
            if needed_by and item.world.clock() == needed_by:
                self.checkpoints[name]["ev_at_needed_by"] = {
                    "at": needed_by.isoformat(),
                    "soc": next(iter(item.world.read()[1].evs.values())).soc,
                }
            if item.world.clock() < target:
                await self.sweep(name)
        return True

    async def event(self, name: str) -> None:
        item, index = self.loaded[name], self.index[name]
        if index >= len(item.times):
            self.playing = False
            return
        event = item.spec.timeline[index]
        at = item.times[index]
        if (
            at <= item.world.clock()
            and event.event
            not in {
                "voice",
                "constitution.activate",
                "app.approve",
                "contact.checkin_reply",
            }
            and not event.event.startswith("link.")
        ):
            # Distinct same-time world changes need ordered temporal graph versions.
            at = item.world.clock() + timedelta(microseconds=1)
        if not await self.advance(name, max(at, item.world.clock())):
            return
        self.index[name] += 1
        if event.event in {
            "voice",
            "constitution.activate",
            "app.approve",
            "contact.checkin_reply",
        }:
            self.playing = False
            self.beats[name] = event.model_dump(mode="json", exclude_none=True)
            self.beat_started[name] = time.monotonic()
        elif event.event.startswith("link."):
            self.beats[name] = {"event": event.event, "deferred": event.deferred}
        else:
            # Only labeled world inputs reach this helper, never voice execution,
            # simulated activation or a prewritten contact response.
            await item.registry.start()
            try:
                await item.apply(index, set(), self.companion.boundary)
            finally:
                await item.registry.close()
        await self.sweep(name)

    async def run(self) -> None:
        while True:
            async with self.lock:
                sampled = time.monotonic()
                elapsed, self.last = sampled - self.last, sampled
                name = self.selected
                item = self.loaded[name]
                if self.playing and self.index[name] < len(item.times):
                    target = min(
                        item.times[self.index[name]],
                        item.world.clock() + timedelta(seconds=elapsed * self.speed),
                    )
                    advanced = await self.advance(name, target)
                    if advanced and target == item.times[self.index[name]]:
                        await self.event(name)
                await self.sweep(name)
            await asyncio.sleep(1)

    async def reply(self, name: str, principal: Principal, answer: str) -> None:
        item = self.loaded[name]
        beat = self.beats[name]
        if not beat or beat["event"] != "contact.checkin_reply":
            raise ValueError("No check-in reply beat is pending")
        async with self.companion.pipeline(item.world.household.id) as p:
            async with p.repo.write(p.clock):
                rows = (
                    (
                        await p.connection.execute(
                            sa.select(db.verification_cases).where(
                                p.scope(db.verification_cases),
                                db.verification_cases.c.document["verification"][
                                    "status"
                                ].astext
                                == "pending",
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
                if len(rows) != 1:
                    raise ValueError("A unique pending verification case is required")
                case = VerificationCase.model_validate(rows[0]["document"])
                state = case.verification
                assert state is not None
                if state.source != "twin":
                    raise ValueError(
                        "Only explicitly simulated cases accept simulated replies"
                    )
                if p.clock() >= state.expires_at:
                    raise ValueError("This case expired")
                case = case.model_copy(
                    update={"verification": state.model_copy(update={"status": answer})}
                )
                await command(
                    p,
                    "record_verification",
                    {"operation": "finish", "case": case.model_dump(mode="json")},
                    principal.model_copy(update={"surface": "scheduler"}),
                )
        self.beats[name] = None

    def router(self) -> APIRouter:
        api = APIRouter(prefix="/api/simulator")

        @api.get("/scenarios")
        async def view(request: Request) -> dict[str, Any]:
            async with self.companion.authorized(request) as (p, _):
                value = self.view()
                value["controllable"] = [
                    name
                    for name, item in self.loaded.items()
                    if item.world.household.id == p.household_id
                ]
                return value

        @api.post("/scenarios")
        async def control(value: Control, request: Request) -> dict[str, Any]:
            async with self.lock:
                async with self.companion.authorized(request) as (p, member):
                    if p.household_id != self.loaded[value.scenario].world.household.id:
                        raise HTTPException(403, "Sign into this scenario’s household")
                    active = await p.connection.scalar(
                        sa.select(db.constitution_versions.c.status).where(
                            p.scope(db.constitution_versions),
                            db.constitution_versions.c.version
                            == p.bundle.policy().version,
                        )
                    )
                    if active != "active":
                        raise HTTPException(
                            409,
                            "Activate this household’s seed rules with a passkey first",
                        )
                    await household(
                        p,
                        member["principal"],
                        "twin",
                        {
                            "operation": "inject",
                            "reference": "simulator:" + value.operation,
                        },
                    )
                if value.operation == "select":
                    self.playing = False
                    self.selected = value.scenario
                elif value.scenario != self.selected:
                    raise HTTPException(409, "Select this scenario first")
                elif value.operation == "reply":
                    if value.reply is None:
                        raise HTTPException(400, "Choose an explicitly simulated reply")
                    await self.reply(value.scenario, member["principal"], value.reply)
                elif value.operation == "pause":
                    self.playing = False
                else:
                    beat = self.beats[value.scenario]
                    if beat and beat["event"] == "review":
                        if await self.review(value.scenario):
                            raise HTTPException(
                                409,
                                "Review the current plan and respond to its pending request first",
                            )
                    if beat and beat["event"] == "voice":
                        completed = False
                        for browser in self.simulator.browsers.values():
                            echo = browser.echoes[beat["member"]]
                            events = [
                                e
                                for e in echo.events
                                if e["at_monotonic"]
                                >= self.beat_started[value.scenario]
                            ]
                            starts = [
                                i
                                for i, e in enumerate(events)
                                if e["kind"] == "user"
                                and utterance_key(e.get("text", ""))
                                == utterance_key(beat["text"])
                            ]
                            for start in starts:
                                # Clarifying follow-up utterances belong to this beat.
                                turn = events[start + 1 :]
                                results = [
                                    e
                                    for e in turn
                                    if e["kind"] == "tool"
                                    and not e.get("background")
                                    and not e["result"].get("isError")
                                    and e["status"]
                                    not in {"clarification", "failed", "unavailable"}
                                    and (
                                        e["tool"] != "approve_action"
                                        or (
                                            e.get("arguments", {}).get("approved")
                                            is True
                                            and (
                                                e["result"]
                                                .get("structuredContent", {})
                                                .get("data", {})
                                                .get("decision")
                                                or {}
                                            ).get("decision")
                                            == "execute"
                                        )
                                    )
                                ]
                                performed = Counter(e["tool"] for e in results)
                                # Starting by contact + text calls assess() inside
                                # verify(), then opens the real verification case.
                                # Do not require a redundant separate assessment.
                                if any(
                                    e["tool"] == "verify_trusted_identity"
                                    and e.get("arguments", {}).get("operation")
                                    == "start"
                                    and not e.get("arguments", {}).get("case_id")
                                    and e["result"]
                                    .get("structuredContent", {})
                                    .get("data", {})
                                    .get("case", {})
                                    .get("risk_band")
                                    for e in results
                                ):
                                    performed["assess_request_risk"] += 1
                                completed |= performed >= Counter(
                                    s if isinstance(s, str) else s["tool"]
                                    for s in beat.get("script", [])
                                ) and any(e["kind"] == "settled" for e in turn)
                        if not completed:
                            completed = await self.phone_plan_approved(
                                value.scenario, beat
                            )
                        if not completed:
                            raise HTTPException(
                                409,
                                "Finish this utterance through the named linked Echo first",
                            )
                    if beat and beat["event"] == "app.approve":
                        async with self.companion.pipeline(p.household_id) as current:
                            async with current.connection.begin():
                                approved = await current.connection.scalar(
                                    sa.select(sa.func.count())
                                    .select_from(db.approvals)
                                    .join(
                                        db.actions,
                                        sa.and_(
                                            db.actions.c.household_id
                                            == db.approvals.c.household_id,
                                            db.actions.c.action_id
                                            == db.approvals.c.action_id,
                                        ),
                                    )
                                    .where(
                                        current.scope(db.approvals),
                                        db.approvals.c.status.in_(
                                            ["approved", "redeemed"]
                                        ),
                                        db.actions.c.proposal["class"].astext
                                        == "security.door_unlock",
                                    )
                                )
                            if not approved:
                                raise HTTPException(
                                    409,
                                    "Approve the door request in the companion app first",
                                )
                    if beat and beat["event"] == "contact.checkin_reply":
                        raise HTTPException(409, "Choose the simulated reply first")
                    if beat and beat["event"] == "constitution.activate":
                        async with self.companion.pipeline(p.household_id) as current:
                            if current.bundle.policy().version != 8:
                                raise HTTPException(
                                    409,
                                    "Review and activate the proposed rule with your passkey first",
                                )
                    self.beats[value.scenario] = None
                    if value.operation == "next":
                        await self.event(value.scenario)
                    else:
                        self.speed, self.playing, self.last = (
                            value.speed,
                            True,
                            time.monotonic(),
                        )
                return self.view()

        return api
