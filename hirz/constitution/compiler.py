"""Cedar/Dogwood compilation from validated syntax, never evaluator outcomes."""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from hirz.constitution.conditions import (
    ATTRIBUTES,
    FactError,
    Node,
    PolicyFacts,
    attribute,
    parse,
    predicate,
    typed,
)
from hirz.constitution.evaluator import guards, policy_values
from hirz.constitution.schema import Constitution, Rule
from hirz.pipeline.models import ROLES, Action
from hirz.risk import CLASSES

REVISION = "996d756de1013b7ae209a14f566a80375a59f2f0"
APPROVE = 'AgentCore::Action::"HirzActions___governance_approve_action"'
INPUT = "context.input"


def action_name(name: str) -> str:
    return "AgentCore::Action::" + literal("HirzActions___" + name.replace(".", "_"))


def field(path: str) -> str:
    # Canonical identity fields have one boundary representation, not shadow copies.
    return {"action.class": "action_class", "requester.role": "requester_role"}.get(
        path, "f_" + path.replace(".", "_")
    )


def call_field(node: Node) -> str:
    return "p_" + hashlib.sha256(repr(node).encode()).hexdigest()[:16]


def literal(value: Any, *, trace: bool = False) -> str:
    if isinstance(value, Decimal):
        text = format(value, "f")
        text = text if "." in text else text + ".0"
        return text if trace else f'decimal("{text}")'
    if isinstance(value, Mapping):
        return (
            "{ "
            + ", ".join(f"{k}: {literal(v, trace=trace)}" for k, v in value.items())
            + " }"
        )
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(literal(v, trace=trace) for v in value) + "]"
    return json.dumps(value)


def conjunction(parts: list[str]) -> str:
    parts = list(dict.fromkeys(p for p in parts if p != "true"))
    return (
        "false"
        if "false" in parts
        else "(" + " && ".join(parts) + ")"
        if parts
        else "true"
    )


def disjunction(parts: list[str]) -> str:
    parts = list(dict.fromkeys(p for p in parts if p != "false"))
    return (
        "true"
        if "true" in parts
        else "(" + " || ".join(parts) + ")"
        if parts
        else "false"
    )


def has(path: str) -> str:
    return (
        "true"
        if path in ("action.class", "requester.role")
        else f"{INPUT} has {field(path)}"
    )


def compare(left: str, op: str, right: str, numeric: bool) -> str:
    if numeric and op in ("<", "<=", ">", ">="):
        method = {
            "<": "lessThan",
            "<=": "lessThanOrEqual",
            ">": "greaterThan",
            ">=": "greaterThanOrEqual",
        }[op]
        return f"{left}.{method}({right})"
    return f"{left} {op} {right}"


def known(node: Node) -> str:
    if node.kind == "attr":
        return has(node.value)
    if node.kind in ("set", "unset"):
        path = node.children[0].value
        return f"({has(path)} || {INPUT}.nulls.contains({literal(path)}))"
    parts = [known(c) for c in node.children]
    if node.kind == "call":
        parts.append(f"{INPUT} has {call_field(node)}")
    return conjunction(parts)


def expression(node: Node) -> str:
    children = node.children
    if node.kind == "attr":
        return f"{INPUT}.{field(node.value)}"
    if node.kind == "literal":
        return literal(node.value)
    if node.kind == "call":
        return f"{INPUT}.{call_field(node)}"
    if node.kind in ("set", "unset"):
        if children[0].value in ("action.class", "requester.role"):
            return "true" if node.kind == "set" else "false"
        check = f"{INPUT}.nulls.contains({literal(children[0].value)})"
        return check if node.kind == "unset" else f"!{check}"
    if node.kind == "not":
        return f"!({expression(children[0])})"
    if node.kind in ("and", "or"):
        return (conjunction if node.kind == "and" else disjunction)(
            [expression(c) for c in children]
        )
    kind = ATTRIBUTES[children[0].value]
    left = expression(children[0])
    right = [literal(typed(c.value, kind)) for c in children[1:]]
    if node.kind == "in":
        return f"[{', '.join(right)}].contains({left})"
    return compare(left, node.kind, right[0], kind == "number")


def override_path(rule: Rule, autonomous: bool, index: int = 0) -> str:
    if index == len(rule.overrides):
        return "true"
    override = rule.overrides[index]
    node = parse(override.when)
    match = (
        "true"
        if override.mode == "auto" or (not autonomous and override.mode == "ask")
        else "false"
    )
    return conjunction(
        [
            known(node),
            f"(if {expression(node)} then {match} else {override_path(rule, autonomous, index + 1)})",
        ]
    )


def requirements(rule: Rule) -> list[str]:
    parts = [known(parse(c)) for c in rule.conditions]
    for path, op, bound in guards(rule):
        parts.extend(
            [has(path), compare(f"{INPUT}.{field(path)}", op, literal(bound), True)]
        )
    if rule.never_for:
        parts.extend(
            [
                has("context.unexpected_visitor"),
                f"!{INPUT}.{field('context.unexpected_visitor')}",
            ]
        )
    return parts


@dataclass(frozen=True)
class Compiled:
    policy: str
    schema: str
    manifest: dict[str, Any]
    predicates: tuple[Node, ...]


def compile_policy(
    policy: Constitution, gateway_resource: str = "hirz-local"
) -> Compiled:
    resource = f"AgentCore::Gateway::{literal(gateway_resource)}"
    household = f"{INPUT}.household == {literal(policy.household)}"
    policies: list[str] = []
    ttls: dict[int, list[str]] = {}
    calls: set[Node] = set()
    for name in CLASSES:
        common = policy.rule(name, "owner")
        for text in (*common.conditions, *(o.when for o in common.overrides)):
            calls.update(n for n in parse(text).walk() if n.kind == "call")
        # Unlisted classes differ only by adult derivation. Group equal role modes.
        allowed_roles = [r for r in ROLES if policy.role_mode(name, r) != "never"]
        auto_roles = [r for r in ROLES if policy.role_mode(name, r) == "auto"]
        agreement = f"{INPUT}.action_class == {literal(name)}"
        safe = (
            conjunction(
                [
                    agreement,
                    f"{literal(allowed_roles)}.contains({INPUT}.requester_role)",
                    *requirements(common),
                    *(
                        [
                            conjunction(
                                [
                                    has("action.params.member_id"),
                                    has("requester.member_id"),
                                    f'({INPUT}.requester_role == "owner" || {INPUT}.{field("action.params.member_id")} == {INPUT}.{field("requester.member_id")})',
                                ]
                            )
                        ]
                        if name == "governance.credentials"
                        else []
                    ),
                    *(
                        [expression(parse(c)) for c in common.conditions]
                        if name.startswith("governance.")
                        else []
                    ),
                    override_path(common, False),
                ]
            )
            if allowed_roles
            else "false"
        )
        scope = f"principal, action == {action_name(name)}, resource == {resource}"
        policies.append(f"forbid ({scope}) when {{ {household} && !{safe} }};")
        if auto_roles:
            autonomous = conjunction(
                [
                    safe,
                    f"{literal(auto_roles)}.contains({INPUT}.requester_role)",
                    *[expression(parse(c)) for c in common.conditions],
                    override_path(common, True),
                ]
            )
            policies.append(f"permit ({scope}) when {{ {household} && {autonomous} }};")
        if allowed_roles and not name.startswith("governance."):
            ttl = common.approval_ttl_minutes or policy.defaults.approval_ttl_minutes
            ttls.setdefault(ttl, []).append(
                conjunction(
                    [
                        f"action == {action_name(name)}",
                        agreement,
                        f"{INPUT}.ttl_minutes == {ttl}",
                    ]
                )
            )
            approval = conjunction(
                [
                    household,
                    safe,
                    f"{INPUT}.ttl_minutes == {ttl}",
                    f"{literal(policy.approvers(name, common.quorum))}.contains({INPUT}.approver_role)",
                    f"{literal(common.ask_channels or policy.defaults.ask_channels)}.contains({INPUT}.approval_channel)",
                    f"{INPUT}.quorum_satisfied",
                ]
            )
            policies.append(
                f"permit (principal, action == {APPROVE}, resource == {resource}) when {{ {approval} }};"
            )
    if len(ttls) > 25 or any(ttl > 1440 for ttl in ttls):
        raise ValueError("Temporal quota exceeded")
    for ttl, classes in sorted(ttls.items()):
        # One formerly operator; field correlations do not consume operator quota.
        policies.append(f"""permit (principal, action, resource == {resource})
when {{ {household} && {disjunction(classes)} }}
when temporal {{ formerly within {ttl}m {APPROVE}::response {{
  callerResource: resource,
  callerPrincipal: principal,
  input.household: {INPUT}.household,
  input.action_class: {INPUT}.action_class,
  input.action_hash: {INPUT}.action_hash,
  input.session_id: {INPUT}.session_id,
  input.ttl_minutes: {ttl},
  output.ttl_minutes: {ttl},
  output.approved: true
}} }};""")
    fields: dict[str, str] = {
        "household": "String",
        "action_class": "String",
        "action_hash": "String",
        "session_id": "String",
        "requester_role": "String",
        "ttl_minutes": "Long",
        "approver_role": "String",
        "approval_channel": "String",
        "quorum_satisfied": "Bool",
        "nulls": "Set<String>",
    }
    kinds = {
        "number": "decimal",
        "string": "String",
        "bool": "Bool",
        "time": "Long",
        "strings": "Set<String>",
    }
    fields.update(
        {
            field(p) + "?": kinds[k]
            for p, k in ATTRIBUTES.items()
            if field(p) not in fields
        }
    )
    ordered_calls = tuple(sorted(calls, key=repr))
    fields.update({call_field(n) + "?": "Bool" for n in ordered_calls})
    declarations = ",\n".join(f"    {k}: {v}" for k, v in fields.items())
    names = [action_name(n).split("::")[-1] for n in CLASSES] + [
        APPROVE.split("::")[-1]
    ]
    schema = (
        "namespace AgentCore {\nentity Worker;\nentity Gateway;\ntype Input = {\n"
        + declarations
        + "\n};\n"
        + "\n".join(
            f"action {n} appliesTo {{ principal: [Worker], resource: [Gateway], context: {{ input: Input, output?: {{approved: Bool, ttl_minutes: Long}} }} }};"
            for n in names
        )
        + "\n}"
    )
    manifest = {
        "engine": "dogwood-local",
        "revision": REVISION,
        "household": policy.household,
        "version": policy.version,
        "gateway_resource": gateway_resource,
        "analysis": "not analyzed: local mode",
        "temporal_policies": len(ttls),
        "temporal_operators_per_policy": 1 if ttls else 0,
        "ttl_groups": sorted(ttls),
        "actions": {n: action_name(n) for n in CLASSES},
        "input_fields": fields,
        "deferred_enforcement": [
            "budgets",
            "quiet_hours",
            "risk",
            "approval_authentication",
            "single_use",
        ],
    }
    return Compiled("\n\n".join(policies), schema, manifest, ordered_calls)


def boundary_input(
    compiled: Compiled,
    action: Action,
    facts: PolicyFacts,
    *,
    ttl_minutes: int,
    approver_role: str = "",
    approval_channel: str = "",
    quorum_satisfied: bool = False,
    session_id: str = "local",
) -> dict[str, Any]:
    values = policy_values(action, facts)
    result: dict[str, Any] = {
        "household": facts.household,
        "action_class": action.action_class,
        "action_hash": action.content_hash,
        "requester_role": action.requested_by.role,
        "ttl_minutes": ttl_minutes,
        "approver_role": approver_role,
        "approval_channel": approval_channel,
        "quorum_satisfied": quorum_satisfied,
        "session_id": session_id,
        "nulls": [],
    }
    for path in ATTRIBUTES:
        try:
            value = attribute(values, path)
            if value is None:
                result["nulls"].append(path)
            else:
                result[field(path)] = value
        except FactError:
            pass  # Absence, invalid facts and null remain distinct at the boundary.
    for node in compiled.predicates:
        try:
            result[call_field(node)] = predicate(node, values, facts)
        except FactError:
            pass
    return result
