"""Same-origin passkey endpoints. Household mutations are added only after activation."""

import asyncio
import os
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncEngine

from hirz import db
from hirz.companion import auth, policy, push, twin
from hirz.constitution.boundary import Dogwood
from hirz.constitution.schema import loads
from hirz.graph.models import now
from hirz.pipeline.audit import AuditWriter
from hirz.pipeline.service import Pipeline, PolicyBundle
from hirz.twin.world import TwinWorld


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Begin(Input):
    operation: Literal[
        "login", "enroll", "add_credential", "revoke", "reinvite", "activate", "approve"
    ]
    token: str | None = Field(default=None, min_length=32, max_length=128)
    credential_id: str | None = Field(default=None, max_length=2048)
    member_id: UUID | None = None
    confirm_lockout: bool = False
    draft_id: str | None = None
    candidate_hash: str | None = None
    approval_id: str | None = None
    action_hash: str | None = None
    approved: bool | None = None

    @model_validator(mode="after")
    def fields_for_operation(self) -> "Begin":
        allowed = {
            "login": set(),
            "enroll": {"token"},
            "add_credential": set(),
            "revoke": {"credential_id", "confirm_lockout"},
            "reinvite": {"member_id"},
            "activate": {"draft_id", "candidate_hash"},
            "approve": {"approval_id", "action_hash", "approved"},
        }[self.operation]
        if self.model_fields_set - {"operation"} - allowed:
            raise ValueError("Fields do not belong to this ceremony")
        if any(getattr(self, field) is None for field in allowed - {"confirm_lockout"}):
            raise ValueError("Missing ceremony binding")
        return self


class Finish(Input):
    id: str = Field(min_length=32, max_length=128)
    credential: dict[str, Any]
    label: str = Field(default="My passkey", min_length=1, max_length=100)


class Draft(Input):
    yaml: str = Field(max_length=131072)
    sentence: str = Field(default="", max_length=2000)
    proposal_id: str | None = Field(default=None, max_length=128)


class Reference(Input):
    id: str


class RecordedDraft(Input):
    sentence: str = Field(min_length=1, max_length=2000)
    proposal_id: str | None = None


class Companion:
    def __init__(
        self,
        engine: AsyncEngine,
        audit: AuditWriter,
        config: auth.Config,
        *,
        demo_world: TwinWorld | None = None,
    ):
        if demo_world is not None and not str(engine.url.database).startswith(
            "hirz_ha_smoke_"
        ):
            raise ValueError("Phone twin fixtures require a disposable database")
        self.engine, self.audit, self.config = engine, audit, config
        self.boundary = Dogwood()
        self.demo_world = demo_world
        self.demo_lock = asyncio.Lock()

    @asynccontextmanager
    async def pipeline(self, household: UUID) -> AsyncIterator[Pipeline]:
        async with self.engine.connect() as c:
            row = (
                (
                    await c.execute(
                        sa.select(db.constitution_versions)
                        .join(
                            db.households,
                            sa.and_(
                                db.households.c.id
                                == db.constitution_versions.c.household_id,
                                db.households.c.constitution_version
                                == db.constitution_versions.c.version,
                            ),
                        )
                        .where(db.households.c.id == household)
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None or auth.digest(row["yaml"]) != row["hash"]:
                raise ValueError("Household policy unavailable")
            bundle = await PolicyBundle.validate(
                household, loads(row["yaml"]), self.boundary
            )
            await c.rollback()
            # Disposable observations and their validation use the same clock.
            # A monotonic twin clock can drift ahead of wall time; do not relax
            # the Registry's rejection of future observations to accommodate it.
            clock = (
                self.demo_world.clock
                if self.demo_world and self.demo_world.household.id == household
                else now
            )
            yield Pipeline(
                c, bundle, self.boundary, self.audit, clock=clock, require_active=True
            )

    def guard(
        self, request: Request, *, authenticated: bool = False
    ) -> tuple[str, str | None]:
        token = request.cookies.get(auth.SESSION_COOKIE)
        if authenticated and not token:
            raise ValueError("Sign in first")
        auth.guard(
            self.config,
            request.headers.get("origin"),
            token,
            request.headers.get("x-hirz-csrf"),
        )
        browser = request.cookies.get(auth.BROWSER_COOKIE)
        if not browser:
            raise ValueError("Open the sign-in page first")
        return browser, token

    @asynccontextmanager
    async def authorized(
        self, request: Request
    ) -> AsyncIterator[tuple[Pipeline, dict[str, Any]]]:
        token = request.cookies.get(auth.SESSION_COOKIE, "")
        if request.method != "GET":
            self.guard(request, authenticated=True)
        async with self.engine.begin() as c:
            member = await auth.session(c, token, now())
        async with self.pipeline(member["household_id"]) as p:
            async with p.repo.write(p.clock):
                member = await auth.session(p.connection, token, p.clock())
                yield p, member


def cookie(response: Response, name: str, token: str) -> None:
    response.set_cookie(
        name,
        token,
        secure=True,
        httponly=True,
        samesite="strict",
        max_age=43200,
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"


def router(service: Companion) -> APIRouter:
    api = APIRouter(prefix="/api")

    @api.post("/twin/doorbell")
    async def ring_twin(request: Request) -> dict[str, str]:
        from hirz.companion.governance import household
        from hirz.executor.local import compose
        from hirz.executor.observations import ingest

        async with service.demo_lock:
            async with service.authorized(request) as (p, member):
                world = service.demo_world
                if world is None or world.household.id != p.household_id:
                    raise HTTPException(
                        404, "No disposable phone fixture is configured"
                    )
                await household(
                    p,
                    member["principal"],
                    "twin",
                    {"operation": "inject", "reference": "phone-doorbell-fixture"},
                )
            world.doorbell_event("doorbell.front_door", None, "press", None)
            async with service.pipeline(world.household.id) as p:
                registry = await compose(
                    p, world=world, config="presence:twin,energy:twin"
                )
                await registry.start()
                try:
                    await ingest(p, registry, member["principal"])
                finally:
                    await registry.close()
            return {"source": "twin"}

    @api.get("/twin")
    async def twin_view(request: Request, response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        async with service.authorized(request) as (p, member):
            return await twin.view(p)

    @api.post("/twin/control")
    async def twin_control(value: twin.Command, request: Request) -> dict[str, str]:
        async with service.authorized(request) as (p, member):
            return {"id": await twin.command(p, member["principal"], value)}

    @api.get("/auth/session")
    async def current(request: Request, response: Response) -> dict[str, Any]:
        cookie(
            response,
            auth.BROWSER_COOKIE,
            request.cookies.get(auth.BROWSER_COOKIE) or secrets.token_urlsafe(32),
        )
        token = request.cookies.get(auth.SESSION_COOKIE)
        if not token:
            return {"authenticated": False}
        try:
            async with service.engine.begin() as c:
                member = await auth.session(c, token, now())
                return {
                    "authenticated": True,
                    "csrf": auth.csrf(token),
                    "member": {
                        key: member[key]
                        for key in ("member_id", "display_name", "role")
                    },
                }
        except ValueError:
            response.delete_cookie(
                auth.SESSION_COOKIE,
                path="/",
                secure=True,
                httponly=True,
                samesite="strict",
            )
            return {"authenticated": False}

    @api.post("/auth/begin")
    async def begin(
        value: Begin, request: Request, response: Response
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        try:
            browser, token = service.guard(
                request, authenticated=value.operation not in {"login", "enroll"}
            )
            if (value.operation == "enroll") != (value.token is not None):
                raise ValueError("Enrollment token required only for enrollment")
            if value.operation == "revoke" and value.credential_id is None:
                raise ValueError("Choose a credential")
            if value.operation == "reinvite" and value.member_id is None:
                raise ValueError("Choose a member")
            if value.operation == "activate" and (
                value.draft_id is None or value.candidate_hash is None
            ):
                raise ValueError("Choose the reviewed candidate")
            binding = (
                None
                if value.operation in {"login", "enroll"}
                else value.model_dump(mode="json", exclude={"token"}, exclude_none=True)
            )
            if value.operation == "add_credential":
                binding = {"operation": "add_credential"}
            async with service.engine.begin() as c:
                return await auth.ceremony(
                    c,
                    service.config,
                    browser,
                    token=value.token,
                    session_token=token,
                    binding=binding,
                )
        except ValueError:
            raise HTTPException(
                400, "Passkey request refused. Check your session and request."
            ) from None

    @api.post("/auth/finish")
    async def finish(
        value: Finish, request: Request, response: Response
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        try:
            browser, token = service.guard(request)
            async with service.engine.begin() as c:
                record = await auth.consume(c, value.id, browser, token, now())
            async with service.engine.connect() as c:
                if record["kind"] == "register":
                    household = UUID(record["binding"]["household_id"])
                else:
                    found_household = await c.scalar(
                        sa.select(db.member_passkeys.c.household_id).where(
                            db.member_passkeys.c.credential_id
                            == value.credential.get("id")
                        )
                    )
                    if found_household is None:
                        raise ValueError("Credential unavailable")
                    household = found_household
            async with service.pipeline(household) as p:
                async with p.repo.write(p.clock):
                    if record["kind"] == "register":
                        result = await auth.register(
                            p,
                            service.config,
                            record,
                            value.credential,
                            value.label,
                            token,
                        )
                    else:
                        key = await auth.assertion(
                            p.connection,
                            service.config,
                            record,
                            value.credential,
                            p.clock(),
                        )
                        if record["kind"] == "login":
                            result = {
                                "session": await auth.create_session(
                                    p.connection, key["credential_id"], p.clock()
                                )
                            }
                        else:
                            current = await auth.session(
                                p.connection, token or "", p.clock()
                            )
                            principal = current["principal"].model_copy(
                                update={"passkey_verified": True}
                            )
                            binding = record["binding"]
                            if binding["operation"] == "revoke":
                                await auth.revoke(
                                    p,
                                    principal,
                                    binding["credential_id"],
                                    binding["confirm_lockout"],
                                )
                                result = {}
                            elif binding["operation"] == "reinvite":
                                result = {
                                    "invitation": await auth.reinvite(
                                        p, principal, UUID(binding["member_id"])
                                    )
                                }
                            elif binding["operation"] == "activate":
                                version = await policy.activate(
                                    p,
                                    principal,
                                    binding["draft_id"],
                                    binding["candidate_hash"],
                                    current["digest"],
                                )
                                result = {"version": str(version)}
                            elif binding["operation"] == "approve":
                                from hirz.pipeline.models import Action

                                approval = await p.approval(binding["approval_id"])
                                if approval is None:
                                    raise ValueError("Approval unavailable")
                                document = await p.connection.scalar(
                                    sa.select(db.actions.c.proposal).where(
                                        p.scope(db.actions),
                                        db.actions.c.action_id == approval["action_id"],
                                    )
                                )
                                action = Action.model_validate(document)
                                if (
                                    action.content_hash != binding["action_hash"]
                                    or type(binding["approved"]) is not bool
                                ):
                                    raise ValueError("Reviewed action changed")
                                principal = principal.model_copy(
                                    update={
                                        "verified_action_hash": action.content_hash,
                                        "requester_confirmed": True,
                                    }
                                )
                                from hirz.mcp.contracts import ApprovalInput
                                from hirz.mcp.household import HouseholdTools

                                if action.plan_id is not None:
                                    raise ValueError("Use the plan approval path")
                                output = await HouseholdTools(p, principal).approve(
                                    ApprovalInput(
                                        action_id=action.action_id,
                                        approval_id=approval["approval_id"],
                                        approved=binding["approved"],
                                        request_id=value.id,
                                    )
                                )
                                result = {"message": output.speakable.headline}
                            else:
                                raise ValueError("Unsupported confirmation")
            if session_token := result.pop("session", None):
                cookie(response, auth.SESSION_COOKIE, session_token)
                result["csrf"] = auth.csrf(session_token)
            return {"ok": True, **result}
        except policy.ReviewError as error:
            raise HTTPException(409, str(error)) from None
        except Exception:
            # Verification/library errors must not disclose credential material or SQL.
            raise HTTPException(
                400, "Passkey verification failed. Start a new request."
            ) from None

    @api.post("/auth/logout")
    async def logout(request: Request, response: Response) -> dict[str, bool]:
        try:
            _, token = service.guard(request, authenticated=True)
            async with service.engine.begin() as c:
                await c.execute(
                    db.companion_sessions.delete().where(
                        db.companion_sessions.c.digest == auth.digest(token or "")
                    )
                )
            response.delete_cookie(
                auth.SESSION_COOKIE,
                path="/",
                secure=True,
                httponly=True,
                samesite="strict",
            )
            return {"ok": True}
        except ValueError:
            raise HTTPException(403, "Sign out refused") from None

    @api.get("/constitution")
    async def constitution_view(request: Request, response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        async with service.authorized(request) as (p, member):
            row = await policy.current(p)
            history = (
                (
                    await p.connection.execute(
                        sa.select(
                            db.constitution_versions.c.version,
                            db.constitution_versions.c.status,
                            db.constitution_versions.c.yaml,
                        )
                        .where(p.scope(db.constitution_versions))
                        .order_by(db.constitution_versions.c.version.desc())
                    )
                )
                .mappings()
                .all()
            )
            proposals = (
                (
                    await p.connection.execute(
                        sa.select(
                            db.rule_proposals, db.members.c.display_name.label("author")
                        )
                        .outerjoin(
                            db.members,
                            sa.and_(
                                db.members.c.household_id
                                == db.rule_proposals.c.household_id,
                                db.members.c.id == db.rule_proposals.c.member_id,
                            ),
                        )
                        .where(p.scope(db.rule_proposals))
                        .order_by(db.rule_proposals.c.created_at.desc())
                        .limit(100)
                    )
                )
                .mappings()
                .all()
            )
            drafts = (
                (
                    await p.connection.execute(
                        sa.select(db.companion_drafts)
                        .where(p.scope(db.companion_drafts))
                        .order_by(db.companion_drafts.c.created_at.desc())
                        .limit(50)
                    )
                )
                .mappings()
                .all()
            )
            from hirz.constitution.schema import Constitution

            return {
                "yaml": row["yaml"],
                "document": loads(row["yaml"]).model_dump(mode="json", by_alias=True),
                "schema": Constitution.model_json_schema(by_alias=True),
                "version": row["version"],
                "status": row["status"],
                "history": [dict(r) for r in history],
                "proposals": [dict(r) for r in proposals],
                "drafts": [
                    {k: v for k, v in r.items() if k != "reviewed_session"}
                    for r in drafts
                ],
                "drafting": os.environ.get("HIRZ_LLM", "off"),
                "recorded_demo": service.demo_world is not None,
                "engine": "dogwood-local",
                "analysis": "not analyzed: local mode",
            }

    @api.post("/constitution/draft")
    async def draft(value: Draft, request: Request) -> dict[str, Any]:
        async with service.authorized(request) as (p, member):
            if value.proposal_id:
                return await policy.proposal_draft(
                    p, member["principal"], value.proposal_id, value.yaml
                )
            return await policy.draft(
                p, member["principal"], value.yaml, value.sentence
            )

    @api.post("/constitution/recorded-draft")
    async def recorded_draft(value: RecordedDraft, request: Request) -> dict[str, Any]:
        import yaml

        from hirz.constitution.schema import dump
        from hirz.twin.scenario import Patch

        if service.demo_world is None:
            raise HTTPException(
                404, "Recorded patches require an explicit disposable demo"
            )
        if value.sentence != "Never unlock for an unexpected visitor":
            raise HTTPException(
                409,
                "The recorded fixture supports only: Never unlock for an unexpected visitor",
            )
        async with service.authorized(request) as (p, member):
            patch = Patch.model_validate(
                yaml.safe_load(
                    (
                        Path(__file__).resolve().parents[2]
                        / "scenarios/fixtures/patch-never-unexpected-visitor.yaml"
                    ).read_text()
                )
            )
            candidate = policy.patched(loads((await policy.current(p))["yaml"]), patch)
            if value.proposal_id:
                sentence = await p.connection.scalar(
                    sa.select(db.rule_proposals.c.text).where(
                        p.scope(db.rule_proposals),
                        db.rule_proposals.c.id == value.proposal_id,
                    )
                )
                if sentence != value.sentence:
                    raise HTTPException(
                        409, "The proposal does not match this recorded fixture"
                    )
                result = await policy.proposal_draft(
                    p, member["principal"], value.proposal_id, dump(candidate)
                )
            else:
                result = await policy.draft(
                    p, member["principal"], dump(candidate), value.sentence
                )
            return result | {"recorded": True}

    @api.post("/constitution/dismiss")
    async def dismiss(value: Reference, request: Request) -> dict[str, bool]:
        async with service.authorized(request) as (p, member):
            await policy.dismiss(p, member["principal"], value.id)
            return {"ok": True}

    @api.post("/constitution/review")
    async def review(value: Reference, request: Request) -> dict[str, Any]:
        async with service.authorized(request) as (p, member):
            return await policy.review_complete(
                p, member["principal"], value.id, member["digest"]
            )

    @api.get("/household")
    async def household_view(request: Request, response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        async with service.authorized(request) as (p, member):
            snapshot = await p.snapshot(p.clock())
            query = sa.select(
                db.member_passkeys.c.credential_id,
                db.member_passkeys.c.member_id,
                db.member_passkeys.c.label,
                db.member_passkeys.c.added_at,
                db.member_passkeys.c.revoked_at,
            ).where(p.scope(db.member_passkeys))
            if member["role"] != "owner":
                query = query.where(
                    db.member_passkeys.c.member_id == member["member_id"]
                )
            keys = (await p.connection.execute(query)).mappings().all()
            from hirz.graph.context import project

            return {
                "graph": project(snapshot.data, "all", None),
                "credentials": [dict(k) for k in keys],
            }

    @api.post("/constitution/parse")
    async def parse(value: Draft, request: Request) -> dict[str, Any]:
        async with service.authorized(request):
            return loads(value.yaml).model_dump(mode="json", by_alias=True)

    @api.get("/tonight")
    async def tonight(request: Request, response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        from hirz.mcp.household import HouseholdTools

        async with service.authorized(request) as (p, member):
            stored = await HouseholdTools(p, member["principal"]).current()
            row = await policy.current(p)
            snapshot = await p.snapshot(p.clock())
            preparation = await p.connection.scalar(
                sa.select(db.plan_requests.c.status)
                .where(p.scope(db.plan_requests))
                .order_by(db.plan_requests.c.created_at.desc())
                .limit(1)
            )
            return {
                "plan": stored["document"] if stored else None,
                "preparation": preparation,
                "devices": [
                    {"name": a["name"], "kind": a["kind"]}
                    for a in snapshot.data["assets"]
                ],
                "policy_status": row["status"],
                "paused": snapshot.data["households"][0].get("autonomy_paused", False),
            }

    @api.post("/tools/{name}")
    async def tool(
        name: str, value: dict[str, Any], request: Request
    ) -> dict[str, Any]:
        from hirz.mcp.contracts import TOOLS
        from hirz.mcp.household import HouseholdTools

        if name not in TOOLS:
            raise HTTPException(404, "Unknown household operation")
        service.guard(request, authenticated=True)
        token = request.cookies.get(auth.SESSION_COOKIE, "")
        async with service.engine.begin() as c:
            member = await auth.session(c, token, now())
        async with service.pipeline(member["household_id"]) as p:
            result = await HouseholdTools(p, member["principal"]).call(name, value)
            return result.model_dump(mode="json", by_alias=True)

    @api.post("/resume")
    async def resume(request: Request) -> dict[str, Any]:
        from hirz.executor.plans import governance

        async with service.authorized(request) as (p, member):
            principal = member["principal"]
            decision = await p.mutate_locked(
                governance(p, "resume_automation", {}, principal), principal
            )
            return decision.model_dump(mode="json", by_alias=True)

    @api.get("/approvals")
    async def approvals(request: Request, response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        async with service.authorized(request) as (p, member):
            rows = (
                (
                    await p.connection.execute(
                        sa.select(db.approvals, db.actions.c.proposal)
                        .join(
                            db.actions,
                            sa.and_(
                                db.actions.c.household_id
                                == db.approvals.c.household_id,
                                db.actions.c.action_id == db.approvals.c.action_id,
                            ),
                        )
                        .where(
                            p.scope(db.approvals),
                            db.approvals.c.status.in_(["pending", "approved"]),
                            db.approvals.c.expires_at > p.clock(),
                        )
                        .order_by(db.approvals.c.expires_at)
                    )
                )
                .mappings()
                .all()
            )
            result = []
            for row in rows:
                rule = p.bundle.policy().rule(row["proposal"]["class"], member["role"])
                if member["role"] in p.bundle.policy().approvers(
                    row["proposal"]["class"], rule.quorum
                ) and "app_push" in (
                    rule.ask_channels or p.bundle.policy().defaults.ask_channels
                ):
                    result.append(
                        {
                            "id": row["approval_id"],
                            "status": row["status"],
                            "expires_at": row["expires_at"],
                            "quorum": rule.quorum,
                            "risk_band": ["low", "medium", "high", "critical"][
                                row["binding"]["gates"]["risk_band"]
                            ],
                            "action": row["proposal"],
                        }
                    )
            from hirz.mcp.card_data import doorbell

            snapshot = await p.snapshot(p.clock())
            door = doorbell(snapshot)
            locks = []
            for asset in snapshot.data["assets"]:
                if asset["kind"] != "lock":
                    continue
                observations = [
                    o
                    for o in snapshot.data["observations"]
                    if o.get("asset_id") == asset["id"] and o["domain"] == "devices"
                ]
                observation = (
                    max(observations, key=lambda o: str(o["observed_at"]))
                    if observations
                    else None
                )
                if observation:
                    from datetime import datetime

                    from hirz.risk import CLASSES

                    age = (
                        snapshot.as_of
                        - datetime.fromisoformat(str(observation["observed_at"]))
                    ).total_seconds()
                    if (
                        snapshot.stale
                        or not 0
                        <= age
                        <= CLASSES["security.door_unlock"]["freshness_seconds"]
                    ):
                        observation = None
                locks.append({"name": asset["name"], "observation": observation})
            return {
                "approvals": result,
                "locks": locks,
                "door": door.model_dump(mode="json") if door else None,
                "demo_controls": bool(
                    service.demo_world
                    and service.demo_world.household.id == p.household_id
                    and member["role"] == "owner"
                ),
            }

    @api.get("/audit")
    async def audit_view(
        request: Request,
        response: Response,
        event: str | None = None,
        before: int | None = None,
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        async with service.authorized(request) as (p, member):
            query = sa.select(
                db.audit_log.c.seq,
                db.audit_log.c.event_type,
                db.audit_log.c.created_at,
                db.audit_log.c.payload,
                db.audit_log.c.curr_hash,
            ).where(p.scope(db.audit_log))
            if event:
                query = query.where(db.audit_log.c.event_type == event)
            if before is not None:
                query = query.where(db.audit_log.c.seq < before)
            rows = (
                (
                    await p.connection.execute(
                        query.order_by(db.audit_log.c.seq.desc()).limit(100)
                    )
                )
                .mappings()
                .all()
            )
            from hirz.audit import LIMITATION

            return {"rows": [dict(r) for r in rows], "anchoring": LIMITATION}

    @api.get("/audit/export")
    async def audit_export(request: Request) -> Response:
        from fastapi.responses import JSONResponse

        from hirz.audit import export_document, verify_database

        token = request.cookies.get(auth.SESSION_COOKIE, "")
        async with service.engine.begin() as c:
            member = await auth.session(c, token, now())
        async with service.engine.connect() as c:
            verified, rows = await verify_database(
                c, member["household_id"], service.audit.key.public_key(), collect=True
            )
        return JSONResponse(
            export_document(
                member["household_id"], service.audit.key.public_key(), rows
            ),
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": 'attachment; filename="hirz-audit.json"',
                "X-Hirz-Verification": verified["status"],
            },
        )

    @api.get("/push")
    async def push_state(request: Request, response: Response) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        async with service.authorized(request) as (p, member):
            config = push.Config.environment()
            rows = (
                (
                    await p.connection.execute(
                        sa.select(
                            db.companion_delivery.c.status,
                            db.companion_delivery.c.attempts,
                            db.companion_delivery.c.expires_at,
                        )
                        .join(db.companion_push)
                        .where(
                            p.scope(db.companion_push),
                            db.companion_push.c.member_id == member["member_id"],
                        )
                        .order_by(db.companion_delivery.c.expires_at.desc())
                        .limit(20)
                    )
                )
                .mappings()
                .all()
            )
            return {
                "available": config is not None,
                "public_key": config.vapid_public_key if config else None,
                "deliveries": [
                    dict(r)
                    | {
                        "status": "expired"
                        if r["status"] != "sent" and r["expires_at"] <= p.clock()
                        else r["status"]
                    }
                    for r in rows
                ],
            }

    @api.post("/push/subscribe")
    async def subscribe(value: push.Subscription, request: Request) -> dict[str, str]:
        config = push.Config.environment()
        if config is None:
            raise HTTPException(503, "Push is not configured; use your approval inbox")
        async with service.authorized(request) as (p, member):
            return {
                "id": await push.subscribe(
                    p, member["principal"], member["member_id"], value, config
                )
            }

    @api.post("/contacts/remove")
    async def remove_contact(value: Reference, request: Request) -> dict[str, bool]:
        from hirz.companion.contacts import remove

        async with service.authorized(request) as (p, member):
            await remove(p, member["principal"], UUID(value.id))
            return {"ok": True}

    return api
