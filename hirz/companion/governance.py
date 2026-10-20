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
    publishing = (
        action.action_class == "governance.constitution"
        and action.params.get("operation") == "publish"
        and principal.surface == "scheduler"
        and p.policy_route is not None
    )
    publishing_run = (
        action.action_class == "governance.twin"
        and action.params.get("operation") == "publish"
        and principal.surface == "scheduler"
    )
    contact_worker = (
        action.action_class == "governance.contacts"
        and action.params.get("operation") == "process"
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
        and not contact_worker
        and not publishing
    ):
        raise ValueError("Companion mutations require an internal command")
    fresh = (
        action.action_class == "governance.credentials"
        or action.params.get("operation") == "activate"
        or action.action_class == "governance.contacts"
        and action.params.get("operation") not in {"guess", "process"}
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
        and not contact_worker
        and not publishing
    ):
        raise ValueError("Constitution changes require an authenticated credential")


async def credentials(
    p: Pipeline,
    principal: Principal,
    member_id: UUID,
    operation: Literal["enroll", "recover", "revoke", "reinvite"],
    *,
    account: tuple[str, str] | None = None,
) -> Decision:
    if p._companion_command is not None:
        raise ValueError("Nested companion mutation")
    if not principal.passkey_verified:
        raise ValueError("Verify the ceremony before changing credentials")
    params = {"operation": operation, "member_id": str(member_id)}
    if account is not None:
        if operation != "enroll" or not all(account):
            raise ValueError("Account proof belongs only to credential enrollment")
        params.update(
            credential_kind="cognito_link", provider=account[0], sub=account[1]
        )
    action = governance(p, "credentials", params, principal)
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
    operation: Literal[
        "draft", "draft_failed", "review", "activate", "dismiss", "publish"
    ],
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
