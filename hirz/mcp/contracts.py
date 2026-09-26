"""Flat MCP contracts; names and schemas are a promise to the host.

https://developer.amazon.com/docs/alexaplus/add-ons/mcp-addon-tools-schema-data-design.html
https://developer.amazon.com/docs/alexaplus/add-ons/mcp-addon-display-modes.html
Structured content supports native rendering and optional MCP App presentation.
"""

from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator
from pydantic.json_schema import GenerateJsonSchema, JsonSchemaValue
from pydantic_core import CoreSchema

from hirz.explainer.models import Speakable
from hirz.graph.context import ContextSnapshot
from hirz.graph.models import Scope
from hirz.mcp.presentation import (
    ApprovalCard,
    DoorbellCard,
    PlanCard,
    Presentation,
    Scorecard,
    VerificationCard,
)
from hirz.mcp.profiles import ProfileName
from hirz.pipeline.models import Action, Decision, Plan, VerificationCase
from hirz.planner.models import Objective
from hirz.risk import CONSUMER_ACTIONS

Reference = Annotated[str, Field(min_length=1, max_length=200)]
Sentence = Annotated[str, Field(min_length=1, max_length=2000)]
RequestKey = Annotated[str, Field(min_length=1, max_length=128)]
Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]


FIELD_DESCRIPTIONS = {
    "scope": "Which household information to read: people, energy, environment, constraints, member, or all.",
    "member": "One household member's exact displayed name or returned reference; required only for member scope.",
    "horizon": "Tonight, overnight and tomorrow morning end at the next household-local 8 AM; next_24h covers 24 hours.",
    "objective": "Optional temporary planning priority: cheapest minimizes electricity and wear cost; greenest reduces grid electricity, not measured emissions; most_comfortable minimizes occupied-room temperature deviation. Changing it requires request_id and a newly reviewed plan.",
    "request_id": "Host-generated retry key. Reuse only for an identical request; use a new key for changed intent.",
    "text": "The user's exact request or proposed rule, retained as provenance; never a source of identity or permissions.",
    "applies_to": "Exact household device or room name, or returned target reference; car means the unique household EV.",
    "kind": "Whether this is a preference, constraint, or one-time request. All revisions are temporary.",
    "operation": "Choose the operation explicitly; replacement and removal need the existing constraint reference, except a unique hold.",
    "change": "The requested planning change: car charge target or limit, start/ready time, temperature or range, or hold release.",
    "percent": "Requested car charge percentage, from zero through eighty; required for charge_car and car_target/car_limit changes.",
    "temperature_f": "Requested room temperature in degrees Fahrenheit; never guess a missing temperature.",
    "lower_f": "Lower temperature bound in degrees Fahrenheit; supply with upper_f for a temperature range.",
    "upper_f": "Upper temperature bound in degrees Fahrenheit; supply with lower_f for a temperature range.",
    "at": "Explicit household-local AM/PM or 24-hour time; ambiguous dates or daylight-saving times need a date and UTC offset.",
    "window_start": "Optional temporary constraint start, expressed as an explicit household-local time.",
    "window_end": "Optional constraint ending. Otherwise ends with the current plan, or after 24 hours when no plan exists.",
    "constraint_id": "Returned reference of the exact constraint being replaced or removed.",
    "claimed_author": "Name claimed in the sentence; recorded as unverified and never used to grant authority.",
    "plan_id": "Exact plan reference supplied by the user or a tool; copy verbatim, including non-UUID references. Optional for explaining the current plan.",
    "focus": "Explain summary, conflicts, or a returned action or goal reference within this plan.",
    "approved": "Explicit user approval or rejection of the exact reviewed plan version or pending action.",
    "version": "Exact plan version supplied by the user or a tool that the user reviewed; required with plan_id.",
    "action_id": "Returned reference of a household action; approvals also require its approval_id.",
    "approval_id": "Returned pending approval reference associated with action_id.",
    "action": "One immediate consumer action: charge or stop the car, set room temperature, switch a light, request door unlock, hold battery, apply a configured profile, or pause automation.",
    "profile": "Explicitly configured household bundle: recovery_morning, guests_arriving, night or away. Requests its thermostat/light settings; unavailable profiles do nothing. Later automation can change settings.",
    "room": "Device or room named by the user, such as living room or front door. Light and lamp are synonyms; the server resolves household targets and returns clarification if ambiguous.",
    "minutes": "Explicit maximum charging or requested door-unlock duration in minutes; required for those actions.",
    "beneficiary": "Exact household member for whom the temperature change is requested; does not establish who spoke.",
    "claimed_requester": "Unverified claimed speaker name; can only lower the linked account's authority.",
    "claimed_party": "Name of the person or organization the suspicious request claims to come from.",
    "party": "Whether the claimed party is a person or organization; organization verification is unavailable.",
    "presented_number": "Phone number explicitly supplied by the user. Omit when unknown; a stored-number match never proves identity.",
    "case_id": "Returned private verification case reference. Use it to disambiguate multiple pending checks.",
    "contact": "Exact trusted contact name or returned reference. Starting without a case also requires the request text.",
    "window": "Household-local history window: today, last night from 6 PM to 8 AM, or this week from Monday midnight.",
    "limit": "Maximum history entries, newest first; defaults to twenty and cannot exceed one hundred.",
    "cursor": "Opaque cursor returned by the preceding history page; keep the same window or action reference.",
}


class ToolSchema(GenerateJsonSchema):
    """Publish constraints and descriptions without generated display titles."""

    def field_title_should_be_set(self, schema: CoreSchema) -> bool:
        return False

    def generate_inner(self, schema: CoreSchema) -> JsonSchemaValue:
        result = super().generate_inner(schema)
        if schema["type"] in {"model", "enum"}:
            # Enum metadata adds its title after enum_schema() returns.
            self.resolve_ref_schema(result).pop("title", None)
        return result


def output_schema(model: type["ToolResult"]) -> dict[str, Any]:
    return model.model_json_schema(schema_generator=ToolSchema)


def input_schema(model: type["Input"]) -> dict[str, Any]:
    schema = model.model_json_schema(schema_generator=ToolSchema)
    for name, field in schema["properties"].items():
        field["description"] = FIELD_DESCRIPTIONS[name]
    if model is VerifyInput:
        schema["properties"]["operation"]["description"] = (
            "Start a new simulated contact check, or read status when the user asks again. Starting requires a request key."
        )
    return schema


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class Empty(Input):
    pass


class ContextInput(Input):
    scope: Scope = "all"
    member: Reference | None = None

    @model_validator(mode="after")
    def combination(self) -> Self:
        if (self.scope == "member") != (self.member is not None):
            raise ValueError("Name a member only when requesting member context.")
        return self


class PlanInput(Input):
    horizon: Literal["tonight", "overnight", "tomorrow_morning", "next_24h"] = "tonight"
    objective: Objective | None = None
    request_id: RequestKey | None = None

    @model_validator(mode="after")
    def combination(self) -> Self:
        if self.objective is not None and self.request_id is None:
            raise ValueError("Changing a planning priority requires a request key.")
        return self


class RevisionInput(Input):
    text: Sentence
    applies_to: Reference
    kind: Literal["preference", "constraint", "one_time"]
    operation: Literal["add", "replace", "remove"]
    change: Literal[
        "car_target",
        "car_limit",
        "charge_after",
        "car_ready_by",
        "appliance_after",
        "appliance_ready_by",
        "temperature",
        "temperature_range",
        "release_hold",
    ]
    percent: Annotated[Number, Field(ge=0, le=80)] | None = None
    temperature_f: Number | None = None
    lower_f: Number | None = None
    upper_f: Number | None = None
    at: Reference | None = None
    window_start: Reference | None = None
    window_end: Reference | None = None
    constraint_id: Reference | None = None
    claimed_author: Reference | None = None
    request_id: RequestKey

    @model_validator(mode="after")
    def combination(self) -> Self:
        if self.operation == "add" and self.constraint_id is not None:
            raise ValueError("Adding a constraint cannot replace another constraint.")
        if (
            self.operation != "add"
            and self.constraint_id is None
            and self.change != "release_hold"
        ):
            raise ValueError("Identify the constraint to replace or remove.")
        if self.change == "release_hold" and self.operation != "remove":
            raise ValueError("Releasing a hold requires removal.")
        required = (
            set()
            if self.operation == "remove"
            else {
                "car_target": {"percent"},
                "car_limit": {"percent"},
                "temperature": {"temperature_f"},
                "temperature_range": {"lower_f", "upper_f"},
            }.get(self.change, {"at"})
        )
        supplied = {
            k
            for k in ("percent", "temperature_f", "lower_f", "upper_f", "at")
            if getattr(self, k) is not None
        }
        if supplied != required:
            raise ValueError("Supply exactly the values needed for this change.")
        if self.operation == "remove" and (self.window_start or self.window_end):
            raise ValueError("Removal does not accept a new window.")
        return self


class ExplainInput(Input):
    plan_id: Reference | None = None
    focus: Reference = "summary"


class ApprovalInput(Input):
    approved: StrictBool
    plan_id: Reference | None = None
    version: Annotated[int, Field(strict=True, ge=1)] | None = None
    action_id: Reference | None = None
    approval_id: Reference | None = None
    request_id: RequestKey

    @model_validator(mode="after")
    def combination(self) -> Self:
        if (self.plan_id is None) != (self.version is None):
            raise ValueError("A plan requires its exact identifier and version.")
        if (self.action_id is None) != (self.approval_id is None):
            raise ValueError(
                "An action requires its exact action and approval references."
            )
        if self.plan_id is None and self.action_id is None:
            raise ValueError("Identify the plan or action you reviewed.")
        return self


class ActionInput(Input):
    action: str = Field(json_schema_extra={"enum": list(CONSUMER_ACTIONS)})
    profile: ProfileName | None = None
    room: Reference | None = None
    temperature_f: Number | None = None
    percent: Annotated[Number, Field(ge=0, le=80)] | None = None
    minutes: Annotated[Number, Field(gt=0, le=1440)] | None = None
    beneficiary: Reference | None = None
    claimed_requester: Reference | None = None
    request_id: RequestKey

    @model_validator(mode="after")
    def combination(self) -> Self:
        if self.action not in CONSUMER_ACTIONS:
            raise ValueError(
                "Choose a supported household action. Money requests require a risk assessment."
            )
        allowed = {
            "charge_car": {"percent", "minutes"},
            "stop_charging": set(),
            "set_temperature": {"temperature_f", "beneficiary"},
            "turn_on_light": set(),
            "turn_off_light": set(),
            "request_door_unlock": {"minutes"},
            "hold_battery": set(),
            "pause_automation": set(),
            "apply_profile": {"profile"},
        }[self.action]
        supplied = {
            k
            for k in ("temperature_f", "percent", "minutes", "beneficiary", "profile")
            if getattr(self, k) is not None
        }
        if (
            supplied - allowed
            or self.action in {"pause_automation", "apply_profile"}
            and self.room is not None
        ):
            raise ValueError("Remove values that do not apply to this action.")
        # Missing values become a clarification, never a guessed device setting.
        return self


class PermissionInput(ActionInput):
    at: Reference | None = None


class RiskInput(Input):
    text: Sentence
    claimed_party: Reference
    party: Literal["person", "organization"]
    presented_number: Reference | None = None
    request_id: RequestKey


class VerifyInput(Input):
    operation: Literal["start", "status"]
    case_id: Reference | None = None
    contact: Reference | None = None
    text: Sentence | None = None
    request_id: RequestKey | None = None

    @model_validator(mode="after")
    def combination(self) -> Self:
        if self.operation == "start":
            if not self.request_id or not (self.case_id or self.contact and self.text):
                raise ValueError(
                    "A new check needs a case or contact and request text, plus a request key."
                )
        elif self.text is not None or self.request_id is not None:
            raise ValueError("A status read does not accept new text or a request key.")
        return self


class ProposalInput(Input):
    text: Sentence
    request_id: RequestKey


class AuditInput(Input):
    window: Literal["today", "last_night", "this_week"] | None = None
    action_id: Reference | None = None
    limit: Annotated[int, Field(strict=True, ge=1, le=100)] = 20
    cursor: Reference | None = None

    @model_validator(mode="after")
    def combination(self) -> Self:
        if self.window and self.action_id:
            raise ValueError("Choose a time window or one action.")
        return self


class AuditSummary(Input):
    at: str
    summary: str
    action_id: str | None = None


class ToolData(Input):
    status: Literal[
        "ok",
        "clarification",
        "queued",
        "preparing",
        "failed",
        "unavailable",
        "denied",
        "recorded",
        "phone_required",
    ] = "ok"
    code: str | None = None


class Data(ToolData):
    presentation: Presentation | None = None
    actions: tuple[Action, ...] = ()
    context: ContextSnapshot | None = None
    plan: Plan | None = None
    action: Action | None = None
    decision: Decision | None = None
    decisions: tuple[Decision, ...] = ()
    case: VerificationCase | None = None
    reference: str | None = None
    constraint_id: str | None = None
    audit: tuple[AuditSummary, ...] = ()
    cursor: str | None = None
    source: Literal["real", "real API, demo devices", "twin"] | None = None
    available_tools: tuple[str, ...] = ()


class Result(Input):
    speakable: Speakable
    data: Data


class ToolResult(Input):
    speakable: Speakable


class WhatCanYouDoData(ToolData):
    available_tools: tuple[str, ...] = ()


class WhatCanYouDoResult(ToolResult):
    data: WhatCanYouDoData


class GetHouseholdContextData(ToolData):
    context: ContextSnapshot | None = None
    presentation: DoorbellCard | None = None


class GetHouseholdContextResult(ToolResult):
    data: GetHouseholdContextData


class GetHouseholdPlanData(ToolData):
    plan: Plan | None = None
    actions: tuple[Action, ...] = ()
    reference: str | None = None
    presentation: PlanCard | None = None


class GetHouseholdPlanResult(ToolResult):
    data: GetHouseholdPlanData


class ReviseHouseholdPlanData(ToolData):
    decision: Decision | None = None
    constraint_id: str | None = None


class ReviseHouseholdPlanResult(ToolResult):
    data: ReviseHouseholdPlanData


class ExplainPlanData(ToolData):
    plan: Plan | None = None
    action: Action | None = None
    actions: tuple[Action, ...] = ()
    reference: str | None = None
    presentation: PlanCard | None = None


class ExplainPlanResult(ToolResult):
    data: ExplainPlanData


class ApproveActionData(ToolData):
    decision: Decision | None = None
    decisions: tuple[Decision, ...] = ()
    plan: Plan | None = None
    action: Action | None = None
    source: Literal["real", "real API, demo devices", "twin"] | None = None
    presentation: ApprovalCard | None = None


class ApproveActionResult(ToolResult):
    data: ApproveActionData


class ExecuteHouseholdActionData(ToolData):
    decision: Decision | None = None
    decisions: tuple[Decision, ...] = ()
    action: Action | None = None
    source: Literal["real", "real API, demo devices", "twin"] | None = None
    presentation: ApprovalCard | None = None


class ExecuteHouseholdActionResult(ToolResult):
    data: ExecuteHouseholdActionData


class AssessRequestRiskData(ToolData):
    case: VerificationCase | None = None
    presentation: VerificationCard | None = None


class AssessRequestRiskResult(ToolResult):
    data: AssessRequestRiskData


class VerifyTrustedIdentityData(ToolData):
    case: VerificationCase | None = None
    decision: Decision | None = None
    source: Literal["real", "real API, demo devices", "twin"] | None = None
    presentation: VerificationCard | None = None


class VerifyTrustedIdentityResult(ToolResult):
    data: VerifyTrustedIdentityData


class ProposeHouseholdRuleData(ToolData):
    reference: str | None = None


class ProposeHouseholdRuleResult(ToolResult):
    data: ProposeHouseholdRuleData


class EvaluatePermissionData(ToolData):
    decision: Decision | None = None
    decisions: tuple[Decision, ...] = ()


class EvaluatePermissionResult(ToolResult):
    data: EvaluatePermissionData


class GetActionAuditData(ToolData):
    audit: tuple[AuditSummary, ...] = ()
    cursor: str | None = None
    plan: Plan | None = None
    presentation: Scorecard | None = None


class GetActionAuditResult(ToolResult):
    data: GetActionAuditData


OUTPUTS: dict[str, type[ToolResult]] = {
    "what_can_you_do": WhatCanYouDoResult,
    "get_household_context": GetHouseholdContextResult,
    "get_household_plan": GetHouseholdPlanResult,
    "revise_household_plan": ReviseHouseholdPlanResult,
    "explain_plan": ExplainPlanResult,
    "approve_action": ApproveActionResult,
    "execute_household_action": ExecuteHouseholdActionResult,
    "assess_request_risk": AssessRequestRiskResult,
    "verify_trusted_identity": VerifyTrustedIdentityResult,
    "propose_household_rule": ProposeHouseholdRuleResult,
    "evaluate_permission": EvaluatePermissionResult,
    "get_action_audit": GetActionAuditResult,
}


def response(
    headline: str,
    *,
    details: tuple[str, ...] = (),
    options: tuple[str, ...] = (),
    **data: object,
) -> Result:
    return Result(
        speakable=Speakable(headline=headline, details=details, options=options),
        data=Data.model_validate(data),
    )


TOOLS: dict[str, tuple[type[Input], str, str]] = {
    "what_can_you_do": (
        Empty,
        "",
        "Describe Hirz's household rules, energy planning and suspicious-request checks.",
    ),
    "get_household_context": (
        ContextInput,
        "read",
        "Read household people, schedules, energy, environment or constraints with sources and availability.",
    ),
    "get_household_plan": (
        PlanInput,
        "plan",
        "Read the current plan or request its preparation, including requests to optimize energy tonight. Use the default objective when none is specified; no clarification is needed just to start planning. No execution consent is implied.",
    ),
    "revise_household_plan": (
        RevisionInput,
        "plan",
        "Record a temporary planning constraint, such as a car charge limit or appliance start time. Text is provenance; supply structured values. Replanning finishes later.",
    ),
    "explain_plan": (
        ExplainInput,
        "read",
        "Answer why or how a plan was arranged using stored facts. Call directly with focus=summary for a general explanation; omit plan_id for the current plan. No preliminary get_household_plan call is needed.",
    ),
    "approve_action": (
        ApprovalInput,
        "act",
        "Submit the user's approval or rejection for server validation. For a reviewed plan, provide approved, plan_id, version and request_id; omit action_id and approval_id. For a pending action, provide approved, action_id, approval_id and request_id; omit plan_id and version. User-supplied references are sufficient: copy them verbatim without another confirmation or preliminary fetch. The server refuses missing, stale or foreign references and never approves an unseen replacement. Door approvals require a phone.",
    ),
    "execute_household_action": (
        ActionInput,
        "act",
        "Request one device setting change, a configured household profile, a door unlock, or pause automation. Profiles use action=apply_profile and the named profile. Future automation may change settings. Ask for missing values. Money cannot be moved.",
    ),
    "assess_request_risk": (
        RiskInput,
        "verify",
        "Assess requests to send money, pay someone, transfer funds, share a code or grant access, including direct commands to send or pay money. Call this tool before giving risk advice; Hirz cannot transfer money. Does not initiate contact. Include a number only if the user supplied it.",
    ),
    "verify_trusted_identity": (
        VerifyInput,
        "verify",
        "Explicitly start a simulated contact check or read its status after the user asks again. No real communication is available.",
    ),
    "propose_household_rule": (
        ProposalInput,
        "plan",
        "Record a proposed household rule sentence for the companion inbox. A worker may draft it; only an owner's phone passkey can activate it.",
    ),
    "evaluate_permission": (
        PermissionInput,
        "read",
        "Preview whether household rules allow an action, optionally at a hypothetical time. Never executes or grants authority.",
    ),
    "get_action_audit": (
        AuditInput,
        "read",
        "Read newest-first household action summaries for a household-local window or one action. Private verification history is withheld.",
    ),
}
