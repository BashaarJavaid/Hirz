"""Reviewed constitution candidates and atomic local activation, never model decisions."""

from difflib import unified_diff
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa

from hirz import db
from hirz.companion.auth import digest
from hirz.companion.governance import constitution
from hirz.constitution.preview import preview
from hirz.constitution.schema import Constitution, dump, loads
from hirz.graph.models import Household
from hirz.graph.repository import row_model
from hirz.pipeline.models import ROLES, EventType, Principal
from hirz.pipeline.service import Pipeline, PolicyBundle
from hirz.risk import CLASSES
from hirz.twin.scenario import Patch


class ReviewError(ValueError):
    """Safe, actionable review failures for the authenticated owner."""


def patched(base: Constitution, patch: Patch) -> Constitution:
    if patch.base_version != base.version or patch.version != base.version + 1:
        raise ValueError("Draft base version changed")
    data = base.model_dump(mode="json", by_alias=True)
    for domain, rules in patch.autonomy.items():
        for name, rule in rules.items():
            # Whole-rule replacement, exactly the existing scenario patch contract.
            data["autonomy"].setdefault(domain, {})[name] = rule
    data["version"] = patch.version
    return Constitution.model_validate(data)


def changed_classes(old: Constitution, new: Constitution) -> set[str]:
    if old.model_dump(exclude={"version", "autonomy"}) != new.model_dump(
        exclude={"version", "autonomy"}
    ):
        return set(CLASSES)
    return {
        name
        for name in CLASSES
        if any(
            old.rule(name, role) != new.rule(name, role)
            or old.role_mode(name, role) != new.role_mode(name, role)
            for role in ROLES
        )
    }


async def current(p: Pipeline) -> dict[str, Any]:
    row = (
        (
            await p.connection.execute(
                sa.select(db.constitution_versions)
                .join(
                    db.households,
                    sa.and_(
                        db.households.c.id == db.constitution_versions.c.household_id,
                        db.households.c.constitution_version
                        == db.constitution_versions.c.version,
                    ),
                )
                .where(db.households.c.id == p.household_id)
            )
        )
        .mappings()
        .one()
    )
    if digest(row["yaml"]) != row["hash"]:
        raise ValueError("Stored policy integrity check failed")
    return dict(row)


async def draft(
    p: Pipeline, principal: Principal, candidate: str, sentence: str = ""
) -> dict[str, Any]:
    if len(candidate) > 131072 or len(sentence) > 2000:
        raise ValueError("Rule draft is too large")
    member = await p.requester(principal)
    base = await current(p)
    old, new = loads(base["yaml"]), loads(candidate)
    if new.household != old.household:
        raise ValueError("A draft cannot change households")
    new = new.model_copy(
        update={
            "version": old.version
            if base["status"] == "unvalidated"
            else old.version + 1
        }
    )
    bundle = await PolicyBundle.validate(p.household_id, new, p.boundary)
    candidate = dump(new)
    review = preview(old, new)
    changed = changed_classes(old, new)
    # A scenario corpus is not a proof over every possible situation. Show structural
    # rule changes as well, including changes with no differing sampled outcome.
    described = {
        row["class"]
        for row in review["situations"]
        if any(line.startswith(f"{row['label']}:") for line in review["lines"])
    }
    review["lines"].extend(
        f"{name}: rule settings changed; review the full YAML"
        for name in sorted(changed - described)
    )
    review |= {
        "changed_classes": sorted(changed),
        "cedar": bundle.compiled.policy,
        "analysis": "not analyzed: local mode",
        "engine": "dogwood-local",
        "yaml_diff": "".join(
            unified_diff(
                dump(old).splitlines(keepends=True),
                candidate.splitlines(keepends=True),
                fromfile="current",
                tofile="candidate",
            )
        ),
    }
    draft_id = uuid4().hex
    await constitution(p, principal, "draft", draft_id)
    await p.connection.execute(
        db.companion_drafts.insert().values(
            id=draft_id,
            household_id=p.household_id,
            member_id=UUID(str(member.member_id)),
            base_version=old.version,
            base_hash=base["hash"],
            candidate=candidate,
            candidate_hash=digest(candidate),
            sentence=sentence,
            review=review,
            created_at=p.clock(),
        )
    )
    return {
        "id": draft_id,
        "candidate_hash": digest(candidate),
        "sentence": sentence,
        "review": review,
        "candidate": candidate,
    }


async def get(p: Pipeline, draft_id: str) -> dict[str, Any]:
    row = (
        (
            await p.connection.execute(
                sa.select(db.companion_drafts).where(
                    p.scope(db.companion_drafts),
                    db.companion_drafts.c.id == draft_id,
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["status"] != "ready":
        raise ValueError("Draft is unavailable")
    return dict(row)


async def review_complete(
    p: Pipeline, principal: Principal, draft_id: str, session_digest: str
) -> dict[str, Any]:
    row = await get(p, draft_id)
    await constitution(p, principal, "review", draft_id)
    await p.connection.execute(
        db.companion_drafts.update()
        .where(
            p.scope(db.companion_drafts),
            db.companion_drafts.c.id == draft_id,
        )
        .values(reviewed_session=session_digest)
    )
    return row


async def activate(
    p: Pipeline,
    principal: Principal,
    draft_id: str,
    candidate_hash: str,
    session_digest: str,
) -> int:
    row = await get(p, draft_id)
    base = await current(p)
    if (
        candidate_hash != row["candidate_hash"]
        or digest(row["candidate"]) != candidate_hash
    ):
        raise ReviewError("Reviewed candidate changed")
    if base["hash"] != row["base_hash"] or base["version"] != row["base_version"]:
        raise ReviewError("Stale preview; review a new draft")
    if len(row["review"]["lines"]) > 3 and row["reviewed_session"] != session_digest:
        raise ReviewError("Open the complete review before activation")
    candidate = loads(row["candidate"])
    bundle = await PolicyBundle.validate(p.household_id, candidate, p.boundary)
    changed = changed_classes(loads(base["yaml"]), candidate)
    pending = (
        (
            await p.connection.execute(
                sa.select(db.approvals, db.actions.c.proposal)
                .join(
                    db.actions,
                    sa.and_(
                        db.actions.c.household_id == db.approvals.c.household_id,
                        db.actions.c.action_id == db.approvals.c.action_id,
                    ),
                )
                .where(
                    p.scope(db.approvals),
                    db.approvals.c.status.in_(["pending", "approved"]),
                    db.approvals.c.expires_at > p.clock(),
                )
            )
        )
        .mappings()
        .all()
    )
    blockers = [v["approval_id"] for v in pending if v["proposal"]["class"] in changed]
    if blockers:
        raise ReviewError("Pending approvals block activation: " + ", ".join(blockers))
    decision = await constitution(p, principal, "activate", draft_id)
    if base["status"] == "unvalidated":
        if candidate.version != base["version"]:
            raise ValueError("First activation must preserve the seed version")
        await p.connection.execute(
            db.constitution_versions.update()
            .where(
                p.scope(db.constitution_versions),
                db.constitution_versions.c.version == base["version"],
            )
            .values(
                yaml=row["candidate"],
                hash=candidate_hash,
                status="active",
                compiled_cedar=bundle.compiled.policy,
                activated_at=p.clock(),
            )
        )
    else:
        if candidate.version != base["version"] + 1:
            raise ValueError("Activation must create the next policy version")
        await p.connection.execute(
            db.constitution_versions.update()
            .where(
                p.scope(db.constitution_versions),
                db.constitution_versions.c.version == base["version"],
            )
            .values(status="superseded")
        )
        await p.connection.execute(
            db.constitution_versions.insert().values(
                household_id=p.household_id,
                version=candidate.version,
                yaml=row["candidate"],
                hash=candidate_hash,
                status="active",
                compiled_cedar=bundle.compiled.policy,
                activated_at=p.clock(),
            )
        )
    home_row = await p.repo.get("households", {})
    assert home_row is not None
    home = Household.model_validate(row_model("households", home_row).model_dump())
    await p.repo.put(
        "households",
        home.model_copy(update={"constitution_version": candidate.version}),
        expected_version=home_row["valid_from"],
    )
    await p.audit.append(
        p.connection,
        p.household_id,
        p.clock(),
        EventType.CONSTITUTION_ACTIVATED,
        {
            "version": candidate.version,
            "previous_version": base["version"],
            "candidate_hash": candidate_hash,
            "draft_id": draft_id,
            "credential_id": principal.credential_id,
            "decision_seq": decision.audit_id,
            "engine": "dogwood-local",
            "analysis": "not analyzed: local mode",
        },
    )
    for prior in pending:
        await p.status(dict(prior), "expired")
        await p.connection.execute(
            db.approvals.insert().values(
                household_id=p.household_id,
                approval_id="apr_" + uuid4().hex,
                action_id=prior["action_id"],
                status="pending",
                created_at=p.clock(),
                expires_at=prior["expires_at"],
                binding=dict(prior["binding"], policy=bundle.fingerprint),
            )
        )
    await p.connection.execute(
        db.companion_drafts.update()
        .where(
            p.scope(db.companion_drafts),
            db.companion_drafts.c.id == draft_id,
        )
        .values(status="activated")
    )
    await p.connection.execute(
        db.rule_proposals.update()
        .where(p.scope(db.rule_proposals), db.rule_proposals.c.draft_id == draft_id)
        .values(status="activated")
    )
    return candidate.version


async def proposal_draft(
    p: Pipeline, principal: Principal, proposal_id: str, candidate: str
) -> dict[str, Any]:
    row = (
        (
            await p.connection.execute(
                sa.select(db.rule_proposals).where(
                    p.scope(db.rule_proposals),
                    db.rule_proposals.c.id == proposal_id,
                    db.rule_proposals.c.status.in_(["queued", "failed", "ready"]),
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ReviewError("Proposal unavailable")
    result = await draft(p, principal, candidate, row["text"])
    if row["draft_id"]:
        await p.connection.execute(
            db.companion_drafts.update()
            .where(
                p.scope(db.companion_drafts),
                db.companion_drafts.c.id == row["draft_id"],
                db.companion_drafts.c.status == "ready",
            )
            .values(status="dismissed")
        )
    await p.connection.execute(
        db.rule_proposals.update()
        .where(
            p.scope(db.rule_proposals),
            db.rule_proposals.c.id == proposal_id,
        )
        .values(status="ready", draft_id=result["id"], failure=None)
    )
    return result


async def dismiss(p: Pipeline, principal: Principal, proposal_id: str) -> None:
    row = (
        (
            await p.connection.execute(
                sa.select(db.rule_proposals).where(
                    p.scope(db.rule_proposals),
                    db.rule_proposals.c.id == proposal_id,
                    db.rule_proposals.c.status.in_(["queued", "ready", "failed"]),
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ReviewError("Proposal unavailable")
    await constitution(p, principal, "dismiss", proposal_id)
    if row["draft_id"]:
        await p.connection.execute(
            db.companion_drafts.update()
            .where(
                p.scope(db.companion_drafts),
                db.companion_drafts.c.id == row["draft_id"],
                db.companion_drafts.c.status == "ready",
            )
            .values(status="dismissed")
        )
    await p.connection.execute(
        db.rule_proposals.update()
        .where(
            p.scope(db.rule_proposals),
            db.rule_proposals.c.id == proposal_id,
        )
        .values(status="dismissed")
    )
