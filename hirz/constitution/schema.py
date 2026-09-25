"""Validated, closed household policy schema. Loading never activates a policy."""

from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import BeforeValidator, Field, StrictInt, field_validator, model_validator
from yaml.nodes import ScalarNode

from hirz.constitution.conditions import TIME, number, parse
from hirz.graph.seeds import UniqueLoader
from hirz.pipeline.models import ROLES, Model, Role
from hirz.risk import CLASSES, RiskBand, floor_outcome


class ConstitutionLoader(UniqueLoader):
    """Retain decimal text before binary floating-point can round a policy bound."""


def decimal_scalar(loader: ConstitutionLoader, node: ScalarNode) -> Decimal:
    return number(loader.construct_scalar(node))


ConstitutionLoader.add_constructor("tag:yaml.org,2002:float", decimal_scalar)


Mode = Literal["auto", "ask", "never"]
Channel = Literal["alexa", "app_push"]
Quorum = Literal["any_adult", "owner", "all_adults"]
Numeric = Annotated[Decimal, BeforeValidator(number)]
TTL = Annotated[StrictInt, Field(ge=1, le=1440)]
RANK: dict[Mode, int] = {"auto": 0, "ask": 1, "never": 2}
DOMAINS = {name.split(".")[0] for name in CLASSES}


class Defaults(Model):
    unlisted_class: Literal["ask"] = "ask"
    approval_ttl_minutes: TTL = 30
    ask_channels: tuple[Channel, ...] = ("alexa", "app_push")

    @field_validator("ask_channels")
    @classmethod
    def channels(cls, value: tuple[Channel, ...]) -> tuple[Channel, ...]:
        if not value or len(set(value)) != len(value):
            raise ValueError("Approval channels must be nonempty and unique")
        return value


class RoleDefinition(Model):
    inherits: Role | None = None
    limited_to: tuple[str, ...] | None = None

    @field_validator("limited_to")
    @classmethod
    def domains(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        if value is not None and (not value or not set(value) <= DOMAINS):
            raise ValueError("Unknown or empty role domains")
        return value


class Bounds(Model):
    min_f: Numeric | None = None
    max_f: Numeric | None = None
    ev_soc_floor: Annotated[Numeric, Field(ge=0, le=1)] | None = None

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if (
            self.min_f is not None
            and self.max_f is not None
            and self.min_f > self.max_f
        ):
            raise ValueError("Minimum exceeds maximum")
        return self


class Budget(Model):
    usd_per_day: Annotated[Numeric, Field(gt=0)]


class Override(Model):
    when: str
    mode: Mode

    @field_validator("when")
    @classmethod
    def expression(cls, value: str) -> str:
        parse(value)
        return value


class Tightening(Model):
    mode: Mode


class Rule(Model):
    mode: Mode
    conditions: tuple[str, ...] = ()
    overrides: tuple[Override, ...] = ()
    bounds: Bounds | None = None
    budget: Budget | None = None
    quorum: Quorum = "any_adult"
    ask_channels: tuple[Channel, ...] | None = None
    approval_ttl_minutes: TTL | None = None
    allowed_requesters: tuple[Role, ...] | None = None
    never_for: tuple[Literal["unexpected_visitor"], ...] = ()
    max_open_minutes: Annotated[Numeric, Field(gt=0)] | None = None
    max_minutes: Annotated[Numeric, Field(gt=0)] | None = None

    @model_validator(mode="after")
    def restrictions(self) -> Self:
        for condition in self.conditions:
            parse(condition)
        if any(RANK[o.mode] < RANK[self.mode] for o in self.overrides):
            raise ValueError("Override may only tighten the base mode")
        if self.ask_channels is not None:
            Defaults.channels(self.ask_channels)
        return self


class QuietHours(Model):
    days: tuple[Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"], ...]
    from_time: str = Field(alias="from")
    to_time: str = Field(alias="to")
    affects: tuple[str, ...]

    @model_validator(mode="after")
    def valid(self) -> Self:
        if (
            not self.days
            or not self.affects
            or not TIME.fullmatch(self.from_time)
            or not TIME.fullmatch(self.to_time)
        ):
            raise ValueError("Invalid quiet-hour interval")
        if self.from_time == self.to_time:
            raise ValueError("Quiet-hour interval must have nonzero duration")
        for name in self.affects:
            if (
                name not in CLASSES
                and sum(c.split(".")[1] == name for c in CLASSES) != 1
            ):
                raise ValueError("Unknown or ambiguous quiet-hour class")
        return self


class Verification(Model):
    require_requester_confirmation: tuple[str, ...] = ()
    trusted_contact_methods_order: tuple[
        Literal["app_confirmation", "verified_callback", "safe_word", "verified_email"],
        ...,
    ] = ()

    @field_validator("require_requester_confirmation")
    @classmethod
    def classes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not set(value) <= CLASSES.keys():
            raise ValueError("Unknown verification class")
        return value


class Learning(Model):
    accept_memory_proposals: Literal["manual", "never"] = "manual"


class Constitution(Model):
    version: Annotated[StrictInt, Field(ge=1)]
    household: Annotated[str, Field(min_length=1)]
    defaults: Defaults = Defaults()
    roles: dict[Role, RoleDefinition]
    autonomy: dict[str, dict[str, Rule]]
    per_role: dict[Role, dict[str, Tightening]] = Field(default_factory=dict)
    quiet_hours: tuple[QuietHours, ...] = ()
    verification: Verification = Verification()
    learning: Learning = Learning()

    def lineage(self, role: Role) -> tuple[Role, ...]:
        result: list[Role] = []
        while role not in result:
            result.append(role)
            parent = self.roles[role].inherits
            if parent is None:
                return tuple(reversed(result))
            role = parent
        raise ValueError("Cyclic role inheritance")

    def domain_allowed(self, role: Role, action_class: str) -> bool:
        domain = action_class.split(".")[0]
        return all(
            self.roles[r].limited_to is None
            or domain in (self.roles[r].limited_to or ())
            for r in self.lineage(role)
        )

    def rule(self, action_class: str, role: Role) -> Rule:
        if action_class == "governance.memory":
            operations = (
                ("append_turn", "reject")
                if self.learning.accept_memory_proposals == "never"
                else ("append_turn", "propose", "accept", "reject")
            )
            allowed = " or ".join(
                f'action.params.operation == "{op}"' for op in operations
            )
            return Rule(
                mode="auto",
                conditions=(
                    f"({allowed})",
                    '((action.params.operation != "accept" and action.params.operation != "reject") or requester.surface == "app")',
                ),
            )
        if action_class in {
            "governance.pause_automation",
            "governance.resume_automation",
            "governance.record_tool_request",
            "governance.propose_rule",
            "governance.request_plan",
            "governance.record_verification",
            "governance.record_constraint",
            "governance.withdraw_constraint",
            "governance.refresh_plan",
            "governance.record_plan",
            "governance.approve_plan",
            "governance.revise_plan",
            "governance.cancel_plan",
            "governance.record_observations",
        }:
            return Rule(
                mode="auto",
                conditions=('requester.surface == "app"',)
                if action_class.endswith("resume_automation")
                else (),
            )
        domain, name = action_class.split(".")
        return self.autonomy.get(domain, {}).get(
            name, Rule(mode="ask" if "adult" in self.lineage(role) else "never")
        )

    def role_mode(self, action_class: str, role: Role) -> Mode:
        if action_class == "governance.resume_automation":
            return "auto" if "adult" in self.lineage(role) else "never"
        if action_class.startswith("governance."):
            return "never" if role == "unknown" else "auto"
        rule = self.rule(action_class, role)
        if not self.domain_allowed(role, action_class) or (
            rule.allowed_requesters is not None and role not in rule.allowed_requesters
        ):
            return "never"
        mode = rule.mode
        for ancestor in self.lineage(role):
            entries = self.per_role.get(ancestor, {})
            entry = entries.get(action_class, entries.get("*"))
            if entry is not None and RANK[entry.mode] > RANK[mode]:
                mode = entry.mode
        return mode

    def approvers(self, action_class: str, quorum: Quorum) -> tuple[Role, ...]:
        return tuple(
            r
            for r in ROLES
            if self.domain_allowed(r, action_class)
            and (r == "owner" if quorum == "owner" else "adult" in self.lineage(r))
        )

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if set(self.roles) != set(ROLES):
            raise ValueError("Exactly the seven documented roles are required")
        for role in ROLES:
            self.lineage(role)
        # These authority relationships are fixed; inheritance may only add restrictions.
        if (
            self.roles["adult"].inherits is not None
            or self.roles["owner"].inherits != "adult"
            or self.roles["caregiver"].inherits != "adult"
        ):
            raise ValueError("Owner and caregiver must inherit adult; adult is a root")
        if any(
            self.roles[r].inherits is not None
            for r in ("teen", "child", "guest", "unknown")
        ):
            raise ValueError("Restricted roles cannot inherit adult authority")
        caregiver = self.roles["caregiver"].limited_to
        if caregiver is None or not set(caregiver) <= {
            "environment",
            "health",
            "communication",
        }:
            raise ValueError("Caregiver must retain its documented domain restrictions")
        for domain, rules in self.autonomy.items():
            if domain not in DOMAINS:
                raise ValueError("Unknown action domain")
            for name, rule in rules.items():
                action_class = f"{domain}.{name}"
                if domain == "governance":
                    raise ValueError("Governance controls are reserved")
                if action_class not in CLASSES:
                    raise ValueError("Unknown action class")
                if (
                    floor_outcome(RiskBand[CLASSES[action_class]["band"]]) != "none"
                    and rule.mode == "auto"
                ):
                    raise ValueError("Static HIGH/CRITICAL classes cannot be auto")
                if domain == "security" and "alexa" in (
                    rule.ask_channels
                    if rule.ask_channels is not None
                    else self.defaults.ask_channels
                ):
                    raise ValueError(
                        f"{action_class}: security approval channels must exclude alexa, including never rules"
                    )
        # Defaults apply to unlisted security classes too.
        for name in CLASSES:
            if name.startswith("security.") and "alexa" in (
                self.rule(name, "owner").ask_channels or self.defaults.ask_channels
            ):
                raise ValueError(
                    f"{name}: security approval channels must exclude alexa"
                )
        for role, entries in self.per_role.items():
            if any(name != "*" and name not in CLASSES for name in entries):
                raise ValueError("Unknown per-role class")
            for name in CLASSES:
                entry = entries.get(name, entries.get("*"))
                if entry is None:
                    continue
                base = self.rule(name, role).mode
                for parent in self.lineage(role)[:-1]:
                    parent_entries = self.per_role.get(parent, {})
                    inherited = parent_entries.get(name, parent_entries.get("*"))
                    if inherited and RANK[inherited.mode] > RANK[base]:
                        base = inherited.mode
                if not self.domain_allowed(role, name):
                    base = "never"
                if RANK[entry.mode] < RANK[base]:
                    raise ValueError(
                        "Per-role entry may only tighten inherited restrictions"
                    )
        return self


def load(path: Path) -> Constitution:
    return loads(path.read_text())


def loads(text: str) -> Constitution:
    """Parse stored or file-backed policy text through the same validation path."""
    documents = list(yaml.load_all(text, Loader=ConstitutionLoader))
    if any(not isinstance(doc, dict) for doc in documents):
        raise ValueError("Constitution documents must be mappings")
    if len(documents) == 2:
        if not isinstance(documents[0].get("household"), dict):
            raise ValueError("Expected graph then constitution seed envelope")
        if documents[0]["household"].get("slug") != documents[1].get("household"):
            raise ValueError("Seed household mismatch")
    elif len(documents) != 1:
        raise ValueError("Expected one constitution or a two-document seed")
    return Constitution.model_validate(documents[-1])


def dump(policy: Constitution) -> str:
    return yaml.safe_dump(
        policy.model_dump(mode="json", by_alias=True, exclude_none=True), sort_keys=True
    )
