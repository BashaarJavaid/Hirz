"""Pure rule resolution. Approval authentication and budgets are later stages."""

from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Literal

from hirz.constitution.conditions import (
    FactError,
    PolicyFacts,
    attribute,
    evaluate,
    freeze,
    parse,
)
from hirz.constitution.schema import (
    RANK,
    Bounds,
    Budget,
    Channel,
    Constitution,
    Mode,
    Quorum,
    Rule,
)
from hirz.pipeline.models import Action, Model, Role


class Diagnostic(Model):
    code: Literal["POLICY_ERROR", "DENY_CONSTITUTION", "DENY_BOUNDS"]
    paths: tuple[str, ...] = ()


class ApprovalRequirements(Model):
    ttl_minutes: int
    quorum: Quorum
    channels: tuple[Channel, ...]
    approver_roles: tuple[Role, ...]


class RuleOutcome(Model):
    constitution_version: int
    selected_rule: str
    effective_mode: Mode
    conditions_met: bool
    approval: ApprovalRequirements
    bounds: Bounds | None
    budget: Budget | None
    max_open_minutes: Decimal | None
    max_minutes: Decimal | None
    diagnostics: tuple[Diagnostic, ...]


def policy_values(action: Action, facts: PolicyFacts) -> Mapping[str, Any]:
    values = dict(facts.values)
    values["action"] = action.model_dump(by_alias=True, exclude_unset=True)
    requester = dict(values.get("requester", {}))
    requester.update(action.requested_by.model_dump())
    values["requester"] = requester
    return freeze(values)  # type: ignore[no-any-return]


def guards(rule: Rule) -> tuple[tuple[str, str, Decimal], ...]:
    result: list[tuple[str, str, Decimal]] = []
    if rule.bounds:
        for name, path, op in (
            ("min_f", "target_f", ">="),
            ("max_f", "target_f", "<="),
            ("ev_soc_floor", "ev_soc_floor", ">="),
        ):
            value = getattr(rule.bounds, name)
            if value is not None:
                result.append((f"action.params.{path}", op, value))
    for name, path in (
        ("max_open_minutes", "open_minutes"),
        ("max_minutes", "minutes"),
    ):
        value = getattr(rule, name)
        if value is not None:
            result.append((f"action.params.{path}", "<=", value))
    return tuple(result)


def resolve(
    policy: Constitution, action: Action, facts: PolicyFacts, *, hard_only: bool = False
) -> RuleOutcome:
    name, role = action.action_class, action.requested_by.role
    rule = policy.rule(name, role)
    mode = policy.role_mode(name, role)
    if name == "governance.credentials" and (
        not action.params.get("member_id")
        or not action.requested_by.member_id
        or role != "owner"
        and action.params["member_id"] != action.requested_by.member_id
    ):
        mode = "never"
    conditions_met = True
    errors: set[str] = set()
    diagnostics: list[Diagnostic] = []
    values = policy_values(action, facts)
    if facts.household != policy.household:
        mode = "never"
        errors.add("household")
    # Terminal restrictions never become an ask just because other facts are missing.
    if mode != "never":
        for path, op, bound in guards(rule):
            try:
                value = attribute(values, path)
                if value is None:
                    raise FactError(path)
                if (op == ">=" and value < bound) or (op == "<=" and value > bound):
                    mode = "never"
                    diagnostics.append(Diagnostic(code="DENY_BOUNDS", paths=(path,)))
            except FactError as exc:
                errors.update(exc.paths)
                mode = "never"
        if "unexpected_visitor" in rule.never_for:
            try:
                visitor = attribute(values, "context.unexpected_visitor")
                if visitor is None:
                    raise FactError("context.unexpected_visitor")
                if visitor:
                    mode = "never"
            except FactError as exc:
                mode = "never"
                errors.update(exc.paths)
        for condition in (
            rule.conditions if not hard_only or name.startswith("governance.") else ()
        ):
            try:
                conditions_met = (
                    evaluate(parse(condition), values, facts) and conditions_met
                )
            except FactError as exc:
                conditions_met = False
                errors.update(exc.paths)
        for override in () if hard_only else rule.overrides:
            try:
                if evaluate(parse(override.when), values, facts):
                    if RANK[override.mode] > RANK[mode]:
                        mode = override.mode
                    break
            except FactError as exc:
                errors.update(exc.paths)
                # An unresolved earlier branch prevents choosing a later branch.
                break
        if mode == "auto" and (not conditions_met or errors):
            # Reserved governance authority is terminal, matching native forbids;
            # collecting approvals can never turn an invalid surface/role into one.
            mode = "never" if name.startswith("governance.") else "ask"
    if errors:
        diagnostics.append(Diagnostic(code="POLICY_ERROR", paths=tuple(sorted(errors))))
    if mode == "never" and not diagnostics:
        diagnostics.append(Diagnostic(code="DENY_CONSTITUTION"))
    return RuleOutcome(
        constitution_version=policy.version,
        selected_rule=name,
        effective_mode=mode,
        conditions_met=conditions_met,
        approval=ApprovalRequirements(
            ttl_minutes=rule.approval_ttl_minutes
            or policy.defaults.approval_ttl_minutes,
            quorum=rule.quorum,
            channels=rule.ask_channels or policy.defaults.ask_channels,
            approver_roles=policy.approvers(name, rule.quorum),
        ),
        bounds=rule.bounds,
        budget=rule.budget,
        max_open_minutes=rule.max_open_minutes,
        max_minutes=rule.max_minutes,
        diagnostics=tuple(diagnostics),
    )
