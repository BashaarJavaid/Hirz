"""Canonical Action and risk assessment from ARCHITECTURE §4; no authority."""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictFloat,
    StrictInt,
    field_validator,
    model_validator,
)

from hirz.explainer.models import NarrationMetadata
from hirz.risk import CLASSES, RiskBand

Role = Literal["owner", "adult", "caregiver", "teen", "child", "guest", "unknown"]
ROLES: tuple[Role, ...] = (
    "owner",
    "adult",
    "caregiver",
    "teen",
    "child",
    "guest",
    "unknown",
)


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class RiskFactor(Model):
    factor: Literal[
        "unknown_requester",
        "occupant_asleep",
        "guest_present",
        "state_stale",
        "deviation_from_baseline",
        "scam_pattern",
        "outside_bounds",
        "scoring_error",
    ]
    effect: Literal["+1 band", "→ CRITICAL"]
    evidence: str


class RiskAssessment(Model):
    band: RiskBand
    base_band: RiskBand
    factors: tuple[RiskFactor, ...]


class Target(Model):
    adapter: str = Field(min_length=1)
    entity: str = Field(min_length=1)
    zone: str | None = None


class Requester(Model):
    member_id: str | None
    role: Role
    surface: Literal["alexa", "app", "scheduler"]
    speaker: str | None = None
    claimed_author: str | None = None


class ExpectedEffect(Model):
    entity: str
    attr: str
    value: JsonValue
    by: AwareDatetime


class Inverse(Model):
    action_class: str = Field(alias="class")
    target: Target
    params: dict[str, JsonValue]


class Revert(Model):
    after_s: StrictInt | StrictFloat = Field(ge=0.000001, allow_inf_nan=False)
    inverse: Inverse


class Action(Model):
    action_id: str = Field(min_length=1)
    action_class: str = Field(alias="class")
    target: Target
    params: dict[str, JsonValue]
    requested_by: Requester
    reason: str
    plan_id: str | None = None
    scheduled_for: datetime | None = None
    expected_effect: ExpectedEffect | None = None
    content_hash: str
    revert: Revert | None = Field(default=None, exclude_if=lambda value: value is None)

    @field_validator("action_class")
    @classmethod
    def known_class(cls, value: str) -> str:
        if value not in CLASSES:
            raise ValueError("Unknown action class")
        return value

    @field_validator("scheduled_for")
    @classmethod
    def aware_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("Action time must be timezone-aware")
        return value


class EventType(StrEnum):
    DRY_RUN = "DRY_RUN"
    PLAN_REFRESH = "PLAN_REFRESH"
    RESERVATION_ADJUSTED = "RESERVATION_ADJUSTED"
    EXECUTE = "EXECUTE"
    ASK_CONSTITUTION = "ASK_CONSTITUTION"
    ASK_RISK = "ASK_RISK"
    ASK_BUDGET = "ASK_BUDGET"
    ASK_UNRESOLVED_CONDITION = "ASK_UNRESOLVED_CONDITION"
    ASK_REQUESTER_CONFIRMATION = "ASK_REQUESTER_CONFIRMATION"
    DENY_CONSTITUTION = "DENY_CONSTITUTION"
    DENY_RISK = "DENY_RISK"
    DENY_BUDGET = "DENY_BUDGET"
    DENY_BOUNDARY = "DENY_BOUNDARY"
    DENY_APPROVAL_MISMATCH = "DENY_APPROVAL_MISMATCH"
    DENY_APPROVAL_EXPIRED = "DENY_APPROVAL_EXPIRED"
    DENY_APPROVAL_USED = "DENY_APPROVAL_USED"
    DENY_APPROVAL_UNAUTHORIZED = "DENY_APPROVAL_UNAUTHORIZED"
    VERIFY = "VERIFY"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    TWIN_CHECKPOINT = "TWIN_CHECKPOINT"
    SCHEDULED = "SCHEDULED"
    EXECUTION_HELD = "EXECUTION_HELD"
    EXECUTION_CANCELLED = "EXECUTION_CANCELLED"
    ENDING_AUTHORIZED = "ENDING_AUTHORIZED"
    OBSERVATIONS_RECORDED = "OBSERVATIONS_RECORDED"
    PLAN_APPROVED = "PLAN_APPROVED"
    PLAN_CANCELLED = "PLAN_CANCELLED"
    NOTICE_PENDING = "NOTICE_PENDING"
    EXECUTION_ATTEMPTED = "EXECUTION_ATTEMPTED"
    EXECUTED = "EXECUTED"
    VERIFIED = "VERIFIED"
    VERIFY_FAILED = "VERIFY_FAILED"
    ROLLED_BACK = "ROLLED_BACK"
    CONSTRAINT_RECORDED = "CONSTRAINT_RECORDED"
    CONSTRAINT_WITHDRAWN = "CONSTRAINT_WITHDRAWN"
    PLAN_CREATED = "PLAN_CREATED"
    PLAN_REVISED = "PLAN_REVISED"
    CONSTITUTION_PROPOSED = "CONSTITUTION_PROPOSED"
    CONSTITUTION_ACTIVATED = "CONSTITUTION_ACTIVATED"
    POLICY_ERROR = "POLICY_ERROR"
    ADAPTER_ERROR = "ADAPTER_ERROR"
    LINK_REJECTED = "LINK_REJECTED"
    OUT_OF_BAND_CHANGE = "OUT_OF_BAND_CHANGE"
    AUTONOMY_PAUSED = "AUTONOMY_PAUSED"
    AUTONOMY_RESUMED = "AUTONOMY_RESUMED"
    AUDIT_ANCHORED = "AUDIT_ANCHORED"
    MEMORY_PROPOSED = "MEMORY_PROPOSED"
    MEMORY_ACCEPTED = "MEMORY_ACCEPTED"
    MEMORY_REJECTED = "MEMORY_REJECTED"


class Principal(Model):
    """Trusted internal authentication result; never parse this from tool input."""

    provider: str
    sub: str
    surface: Literal["alexa", "app", "scheduler"]
    claimed_role: Role | None = None
    requester_confirmed: StrictBool = False
    passkey_verified: StrictBool = False
    verified_action_hash: str | None = None
    credential_id: str | None = Field(default=None, exclude_if=lambda v: v is None)


class SupplementalEvidence(Model):
    household_id: UUID
    observed_at: AwareDatetime
    source: Literal["real", "real API, demo devices", "twin"]
    scam_pattern: StrictBool


class ConstitutionEvidence(Model):
    version: int
    rule: str
    mode: Literal["auto", "ask", "never"]
    conditions_met: bool


class BoundaryEvidence(Model):
    engine: Literal["dogwood-local", "agentcore-policy"] = "dogwood-local"
    result: Literal["allow", "deny", "not_evaluated"] = "not_evaluated"
    reason: str = "terminal before boundary"
    context_hash: str | None = None
    roles: dict[Role, bool] = Field(default_factory=dict)


class BudgetEvidence(Model):
    local_date: date
    action_class: str = Field(validation_alias="class", serialization_alias="class")
    used: Decimal
    proposed: Decimal | None
    cap: Decimal
    reserved: Decimal = Decimal(0)


class ApprovalEvidence(Model):
    approval_id: str
    quorum: Literal["any_adult", "owner", "all_adults"]
    expires_at: AwareDatetime


class Explanation(Model):
    facts: tuple[str, ...] = ()
    considered: tuple[str, ...] = ()
    rejected: tuple[str, ...] = ()


class Decision(Model):
    decision: Literal["execute", "ask", "deny", "verify"]
    event_type: EventType
    action_id: str
    risk: RiskAssessment | None = None
    constitution: ConstitutionEvidence
    boundary: BoundaryEvidence = BoundaryEvidence()
    approval: ApprovalEvidence | None = None
    budget: BudgetEvidence | None = None
    explain: Explanation = Explanation()
    audit_id: int | None = None
    status: (
        Literal[
            "executing",
            "verified",
            "failed",
            "held",
            "cancelled",
            "skipped",
            "dispatched",
        ]
        | None
    ) = Field(default=None, exclude_if=lambda value: value is None)
    narration: NarrationMetadata | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    speakable: dict[str, JsonValue] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class AuditEvent(Model):
    """The stored signed row; payloads remain opaque canonical JSON objects."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    household_id: UUID
    seq: int = Field(gt=0)
    event_type: str = Field(min_length=1)
    payload: dict[str, JsonValue]
    prev_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    curr_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    key_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    signature: bytes = Field(min_length=1)
    created_at: AwareDatetime


class PlanHorizon(Model):
    start: AwareDatetime
    end: AwareDatetime
    slot_minutes: Literal[15] = 15

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end.timestamp() <= self.start.timestamp():
            raise ValueError("Plan horizon must be positive")
        return self


class PlanConstraint(Model):
    member_id: UUID | None = Field(default=None, exclude_if=lambda value: value is None)
    source: str
    surface: Literal["alexa", "app", "scheduler"] | None = None
    claimed_author: str | None = None
    recorded_at: AwareDatetime
    text: str
    encoded: dict[str, JsonValue]


class ComparisonValidity(Model):
    valid: bool
    reasons: tuple[str, ...] = ()


class PlanAlternative(Model):
    model_config = ConfigDict(allow_inf_nan=False)

    label: Literal["timer", "immediate", "greedy"]
    cost_delta_usd: float | None
    why_rejected: str
    validity: ComparisonValidity

    @model_validator(mode="after")
    def honest_delta(self) -> Self:
        if not self.validity.valid and self.cost_delta_usd is not None:
            raise ValueError("Invalid comparison cannot claim savings")
        return self


class PlanSummary(Model):
    model_config = ConfigDict(allow_inf_nan=False)

    estimated_savings_usd: float | None
    peak_kwh_avoided: float | None
    grid_kwh: float
    solar_kwh: float
    exported_kwh: float
    electricity_usd: float
    wear_usd: float
    comfort_violations_minutes: float


class Plan(Model):
    """A proposal is data, never a Pipeline grant or approval."""

    plan_id: str
    household_id: UUID
    version: int = Field(ge=1)
    supersedes: str | None = None
    horizon: PlanHorizon
    goals: tuple[str, ...]
    constraints: tuple[PlanConstraint, ...]
    actions: tuple[str, ...]
    summary: PlanSummary
    alternatives: tuple[PlanAlternative, ...]
    explain: Explanation
    narration: NarrationMetadata | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    speakable: dict[str, JsonValue]
    status: Literal[
        "proposed",
        "refreshing",
        "awaiting_approval",
        "approved",
        "active",
        "superseded",
        "completed",
        "abandoned",
    ] = "proposed"
    method: Literal["milp", "timeout_incumbent", "greedy"]
    optimality_gap: float | None = Field(default=None, ge=0)
    comparison_validity: ComparisonValidity

    @model_validator(mode="after")
    def honest_summary(self) -> Self:
        if not self.comparison_validity.valid and (
            self.summary.estimated_savings_usd is not None
            or self.summary.peak_kwh_avoided is not None
        ):
            raise ValueError("Invalid comparison cannot claim savings or avoided peak")
        return self


class VerificationClaim(Model):
    text: str = Field(min_length=1, max_length=2000)
    channel: Literal["reported"] = "reported"
    presented_number: str | None = Field(default=None, max_length=200)


class VerificationSubject(Model):
    contact_id: str | None = None
    trusted: bool
    claimed_party: str = Field(min_length=1, max_length=200)
    party: Literal["person", "organization"]


class VerificationSignal(Model):
    signal: Literal[
        "financial_or_access_request",
        "unfamiliar_channel_reported",
        "secrecy",
        "third_party_recipient",
        "urgency_language",
        "claimed_authority",
    ]
    weight: Literal[1, 2]


class VerificationState(Model):
    method: Literal["app_confirmation"] = "app_confirmation"
    status: Literal["pending", "genuine", "not_genuine", "will_call", "no_answer"]
    sent_to: str
    started_at: AwareDatetime
    expires_at: AwareDatetime
    source: Literal["twin"] = "twin"


class VerificationCase(Model):
    case_id: str
    claim: VerificationClaim
    subject: VerificationSubject
    signals: tuple[VerificationSignal, ...]
    risk_band: RiskBand
    recommended: tuple[Literal["verify_via_verified_channel", "do_not_transfer"], ...]
    number_comparison: (
        Literal["matches", "does_not_match", "insufficient_information"] | None
    ) = None
    verification: VerificationState | None = None
    speakable: dict[str, JsonValue]
