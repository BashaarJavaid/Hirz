"""Small typed Boolean grammar, with whole-expression fact preflight."""

import ast
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any, Literal

Kind = Literal["number", "string", "bool", "time", "strings"]
ATTRIBUTES: dict[str, Kind] = {
    "context.hour": "number",
    "context.weekday": "string",
    "context.time": "time",
    "context.is_quiet_hours": "bool",
    "context.price_band": "string",
    "context.unexpected_visitor": "bool",
    "occupancy.sleeping_any": "bool",
    "occupancy.present_members": "strings",
    "action.class": "string",
    "action.target.adapter": "string",
    "action.target.entity": "string",
    "action.target.zone": "string",
    "requester.role": "string",
    "requester.member_id": "string",
    "requester.claimed_role": "string",
    "requester.surface": "string",
    "asset.policy.needed_by": "string",
    "asset.policy.soc_min": "number",
    "risk.band": "string",
    "risk.factors": "strings",
    "household.budget_used_today": "number",
}
for _name in ("target_f", "ev_soc_floor", "open_minutes", "minutes", "soc", "power_kw"):
    ATTRIBUTES[f"action.params.{_name}"] = "number"
for _name in ("mode", "needed_by", "operation"):
    ATTRIBUTES[f"action.params.{_name}"] = "string"
for _name in ("soc", "temp_f", "target_f", "power_kw", "recovery_score"):
    ATTRIBUTES[f"asset.state.{_name}"] = "number"
for _name in ("present", "sleeping", "plugged_in", "available", "locked", "on"):
    ATTRIBUTES[f"asset.state.{_name}"] = "bool"
ATTRIBUTES["asset.state.zone_id"] = "string"
FUNCTIONS = {
    "occupancy.present": 1,
    "occupancy.sleeping_in": 1,
    "schedule.expected_within": 2,
}
TIME = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d\Z")
TOKEN = re.compile(
    r"""\s*(>=|<=|==|!=|[<>()\[\],]|(?:[01]\d|2[0-3]):[0-5]\d|-?\d+(?:\.\d+)?|"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*)"""
)


def number(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("Invalid decimal")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Invalid decimal") from None
    # Cedar decimal uses a signed 64-bit fixed-point integer, scale 10,000.
    if (
        not result.is_finite()
        or isinstance(result.as_tuple().exponent, int)
        and int(result.as_tuple().exponent) < -4
        or not (
            Decimal("-922337203685477.5808")
            <= result
            <= Decimal("922337203685477.5807")
        )
    ):
        raise ValueError(
            "Decimal must fit Cedar range with at most four fractional digits"
        )
    return result


def typed(value: object, kind: Kind) -> Any:
    if kind == "number":
        return number(value)
    if kind == "bool" and type(value) is bool:
        return value
    if kind == "string" and isinstance(value, str):
        return value
    if kind == "time" and isinstance(value, str) and TIME.fullmatch(value):
        return int(value[:2]) * 60 + int(value[3:])
    if (
        kind == "strings"
        and isinstance(value, (tuple, list))
        and all(isinstance(v, str) for v in value)
    ):
        return tuple(value)
    raise ValueError("Invalid attribute type")


@dataclass(frozen=True)
class Node:
    kind: str
    value: Any = None
    children: tuple["Node", ...] = ()

    def walk(self) -> tuple["Node", ...]:
        return (self,) + tuple(n for c in self.children for n in c.walk())


class Parser:
    def __init__(self, source: str):
        self.tokens: list[str] = []
        pos = 0
        source = source.strip()
        if len(source) > 4096:
            raise ValueError("Condition too long")
        while pos < len(source):
            match = TOKEN.match(source, pos)
            if not match:
                raise ValueError("Invalid condition syntax")
            self.tokens.append(match[1])
            pos = match.end()
        self.pos = 0

    def take(self, token: str) -> bool:
        if self.pos < len(self.tokens) and self.tokens[self.pos] == token:
            self.pos += 1
            return True
        return False

    def pop(self) -> str:
        if self.pos == len(self.tokens):
            raise ValueError("Incomplete condition")
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def expect(self, token: str) -> None:
        if not self.take(token):
            raise ValueError(f"Expected {token}")

    def boolean(self, op: str) -> Node:
        child: Callable[[], Node] = (
            (lambda: self.boolean("and")) if op == "or" else self.term
        )
        result = child()
        while self.take(op):
            result = Node(op, children=(result, child()))
        return result

    def argument(self) -> Node:
        token = self.pop()
        if TIME.fullmatch(token):
            return Node("literal", token)
        if token in ATTRIBUTES:
            return Node("attr", token)
        if token.startswith(("'", '"')):
            try:
                return Node("literal", ast.literal_eval(token))
            except (SyntaxError, ValueError):
                raise ValueError("Invalid string literal") from None
        if token in ("true", "false"):
            return Node("literal", token == "true")
        try:
            return Node("literal", number(token))
        except ValueError:
            raise ValueError(f"Unknown attribute or literal: {token}") from None

    def term(self) -> Node:
        if self.take("not"):
            return Node("not", children=(self.term(),))
        if self.take("("):
            result = self.boolean("or")
            self.expect(")")
            return result
        if self.pos < len(self.tokens) and self.tokens[self.pos] in FUNCTIONS:
            fn = self.pop()
            self.expect("(")
            args = [self.argument()]
            while self.take(","):
                args.append(self.argument())
            self.expect(")")
            if len(args) != FUNCTIONS[fn]:
                raise ValueError("Invalid predicate arity")
            for i, arg in enumerate(args):
                kind: Kind = "number" if i == 1 else "string"
                if arg.kind == "attr":
                    if ATTRIBUTES[arg.value] != kind:
                        raise ValueError("Invalid predicate argument type")
                else:
                    typed(arg.value, kind)
            if len(args) == 2 and args[1].kind == "literal" and args[1].value < 0:
                raise ValueError("Arrival horizon must be nonnegative")
            return Node("call", fn, tuple(args))
        attr = self.argument()
        if attr.kind != "attr":
            raise ValueError("Comparison must start with an attribute")
        if self.take("is"):
            unset = self.take("not")
            self.expect("set")
            return Node("unset" if unset else "set", children=(attr,))
        op = self.pop()
        if op == "in":
            self.expect("[")
            args = [self.argument()]
            while self.take(","):
                args.append(self.argument())
            self.expect("]")
        elif op in ("==", "!=", "<", "<=", ">", ">="):
            args = [self.argument()]
        else:
            raise ValueError("Invalid comparison operator")
        kind = ATTRIBUTES[attr.value]
        if kind == "strings" or (
            op in ("<", "<=", ">", ">=") and kind not in ("number", "time")
        ):
            raise ValueError("Invalid comparison for attribute type")
        for arg in args:
            if arg.kind != "literal":
                raise ValueError("Only literal comparisons are supported")
            typed(arg.value, kind)
        return Node(op, children=(attr, *args))


def parse(source: str) -> Node:
    parser = Parser(source)
    try:
        result = parser.boolean("or")
    except RecursionError:
        raise ValueError("Condition nesting too deep") from None
    if parser.pos != len(parser.tokens):
        raise ValueError("Trailing condition input")
    return result


def freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(freeze(v) for v in value)
    return value


@dataclass(frozen=True)
class PolicyFacts:
    household: str
    as_of: datetime
    values: Mapping[str, Any]
    member_ids: tuple[str, ...] = ()
    zone_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.as_of.utcoffset() is None:
            raise ValueError("Snapshot time must be timezone-aware")
        object.__setattr__(self, "values", freeze(self.values))
        object.__setattr__(self, "member_ids", tuple(self.member_ids))
        object.__setattr__(self, "zone_ids", tuple(self.zone_ids))


class FactError(ValueError):
    def __init__(self, *paths: str):
        self.paths = tuple(sorted(set(paths)))
        super().__init__("Unresolved policy facts: " + ", ".join(self.paths))


def lookup(values: Mapping[str, Any], path: str) -> Any:
    current: Any = values
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            raise FactError(path)
        current = current[part]
    return current


def attribute(values: Mapping[str, Any], path: str) -> Any:
    value = lookup(values, path)
    if value is None:
        return None
    try:
        return typed(value, ATTRIBUTES[path])
    except (ValueError, TypeError):
        raise FactError(path) from None


def predicate(node: Node, values: Mapping[str, Any], facts: PolicyFacts) -> bool:
    args = [
        attribute(values, n.value) if n.kind == "attr" else n.value
        for n in node.children
    ]
    path = (
        "schedule.arrivals"
        if node.value.startswith("schedule.")
        else "occupancy.members"
    )
    rows = lookup(values, path)
    ids = facts.zone_ids if node.value == "occupancy.sleeping_in" else facts.member_ids
    if args[0] not in ids or not isinstance(rows, tuple):
        raise FactError(path, *(n.value for n in node.children if n.kind == "attr"))
    if node.value == "schedule.expected_within" and (args[1] is None or args[1] < 0):
        raise FactError(path)
    matches = []
    try:
        for row in rows:
            if row["member_id"] not in facts.member_ids:
                raise ValueError()
            if node.value == "schedule.expected_within":
                at = datetime.fromisoformat(row["expected_at"])
                if at.utcoffset() is None or args[1] is None or args[1] < 0:
                    raise ValueError()
                seconds = Decimal(str((at - facts.as_of).total_seconds()))
                matches.append(
                    row["member_id"] == args[0] and 0 <= seconds <= args[1] * 60
                )
            elif node.value == "occupancy.present":
                matches.append(
                    row["member_id"] == args[0] and typed(row["present"], "bool")
                )
                typed(row["present"], "bool")
            else:
                if row.get("present") is False:
                    matches.append(False)
                    continue
                if row["zone_id"] not in facts.zone_ids:
                    raise ValueError()
                sleeping = typed(row["sleeping"], "bool")
                matches.append(row["zone_id"] == args[0] and sleeping)
    except (KeyError, TypeError, ValueError):
        raise FactError(path) from None
    return any(matches)


def evaluate(node: Node, values: Mapping[str, Any], facts: PolicyFacts) -> bool:
    resolved: dict[Node, Any] = {}
    errors: set[str] = set()
    nullable = {n.children[0] for n in node.walk() if n.kind in ("set", "unset")}
    required = {
        c
        for n in node.walk()
        if n.kind not in ("set", "unset")
        for c in n.children
        if c.kind == "attr"
    }
    for item in node.walk():
        try:
            if item.kind == "attr":
                value = attribute(values, item.value)
                if value is None and (item not in nullable or item in required):
                    raise FactError(item.value)
                resolved[item] = value
            elif item.kind == "call":
                resolved[item] = predicate(item, values, facts)
        except FactError as exc:
            errors.update(exc.paths)
    if errors:
        raise FactError(*errors)

    def run(n: Node) -> Any:
        if n.kind in ("attr", "call"):
            return resolved[n]
        if n.kind == "literal":
            return n.value
        children = [run(c) for c in n.children]
        if n.kind == "and":
            return all(children)
        if n.kind == "or":
            return any(children)
        if n.kind == "not":
            return not children[0]
        if n.kind in ("set", "unset"):
            return (children[0] is None) == (n.kind == "unset")
        a, *rest = children
        rest = [typed(v, ATTRIBUTES[n.children[0].value]) for v in rest]
        b = rest[0]
        if n.kind == "in":
            return a in rest
        return {
            "==": lambda: a == b,
            "!=": lambda: a != b,
            "<": lambda: a < b,
            "<=": lambda: a <= b,
            ">": lambda: a > b,
            ">=": lambda: a >= b,
        }[n.kind]()

    return bool(run(node))
