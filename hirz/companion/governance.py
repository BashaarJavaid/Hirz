"""Internal, audited companion mutations; private credential material stays out of actions."""

from typing import Literal
from uuid import UUID

from hirz.executor.plans import governance
from hirz.pipeline.models import Action, Decision, Principal
from hirz.pipeline.service import Pipeline


async def prepare(p: Pipeline, action: Action, principal: Principal) -> None:
    drafting = (
        action.action_class == "governance.constitution"
        and action.params.get("operation") in {"draft", "draft_failed"}
        and principal.surface == "scheduler"
    )
    publishing_run = (
        action.action_class == "governance.twin"
        and action.params.get("operation") == "publish"
        and principal.surface == "scheduler"
    )
    if (
        p._companion_command is None
        or p._companion_command.content_hash != action.content_hash
        or p._companion_command.params != action.params
        or p._companion_command.target != action.target
        or principal.surface != "app"
        and not drafting
        and not publishing_run
    ):
        raise ValueError("Companion mutations require an internal command")
    fresh = (
        action.action_class == "governance.credentials"
        or action.params.get("operation") == "activate"
    )
    if fresh and (
        not principal.passkey_verified
        or principal.verified_action_hash != action.content_hash
    ):
        raise ValueError("A bound passkey verification is required")
    if not await p.credential_current(principal):
        raise ValueError("Credential revoked")
    if (
        action.action_class != "governance.credentials"
        and principal.credential_id is None
        and not drafting
    ):
        raise ValueError("Constitution changes require an authenticated credential")


async def credentials(
    p: Pipeline,
    principal: Principal,
    member_id: UUID,
    operation: Literal["enroll", "recover", "revoke", "reinvite"],
) -> Decision:
    if p._companion_command is not None:
        raise ValueError("Nested companion mutation")
    if not principal.passkey_verified:
        raise ValueError("Verify the ceremony before changing credentials")
    action = governance(
        p,
        "credentials",
        {"operation": operation, "member_id": str(member_id)},
        principal,
    )
    p._companion_command = action
    try:
        decision = await p.mutate_locked(
            action,
            principal.model_copy(
                update={
                    "passkey_verified": True,
                    "verified_action_hash": action.content_hash,
                }
            ),
        )
        if decision.decision != "execute":
            raise ValueError("Credential mutation refused")
        return decision
    finally:
        p._companion_command = None


async def household(
    p: Pipeline,
    principal: Principal,
    name: Literal["contacts", "twin"],
    params: dict[str, str],
) -> Decision:
    if p._companion_command is not None:
        raise ValueError("Nested companion mutation")
    action = governance(p, name, params, principal)
    p._companion_command = action
    try:
        decision = await p.mutate_locked(action, principal)
        if decision.decision != "execute":
            raise ValueError("Household governance refused")
        return decision
    finally:
        p._companion_command = None


async def constitution(
    p: Pipeline,
    principal: Principal,
    operation: Literal["draft", "draft_failed", "review", "activate", "dismiss"],
    reference: str,
) -> Decision:
    if (
        p._companion_command is not None
        or operation == "activate"
        and not principal.passkey_verified
    ):
        raise ValueError("A fresh passkey is required for activation")
    action = governance(
        p, "constitution", {"operation": operation, "reference": reference}, principal
    )
    p._companion_command = action
    try:
        bound = principal.model_copy(
            update={"verified_action_hash": action.content_hash}
        )
        decision = await p.mutate_locked(action, bound)
        if decision.decision != "execute":
            raise ValueError("Constitution mutation refused")
        return decision
    finally:
        p._companion_command = None
