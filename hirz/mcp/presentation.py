"""Deterministic, optional card data. No card field grants authority."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field

from hirz.graph.models import Model


class Annualized(Model):
    usd: float = Field(allow_inf_nan=False)
    eligible_days: int = Field(ge=1)
    total_days: int = Field(ge=1)
    sha256: str
    profile: str
    household_variant: str
    wear_per_internal_kwh: float
    period: str
    label: str


class Card(Model):
    as_of: AwareDatetime
    valid_until: AwareDatetime
    source: Literal["live", "simulated"] = "simulated"


class PlanRow(Model):
    action_id: str
    label: str
    at: datetime | None = None


class PlanCard(Card):
    kind: Literal["plan"] = "plan"
    rows: tuple[PlanRow, ...]
    timeline: tuple[PlanRow, ...]
    annualized: Annualized | None = None
    car_limit: float | None = None
    can_approve: bool = False
    can_revise_car: bool = False
    rate_label: str | None = None


class ApprovalCard(Card):
    kind: Literal["approval"] = "approval"
    label: str
    rule: str
    risk_band: str
    can_respond: bool = False
    phone_required: bool = False
    plan_id: str | None = None
    version: int | None = None


class VerificationCard(Card):
    kind: Literal["verification"] = "verification"
    signals: tuple[str, ...]
    status: Literal[
        "assessed", "pending", "genuine", "not_genuine", "will_call", "no_answer"
    ]
    contact_name: str | None = None
    can_check: bool = False


class DoorbellCard(Card):
    kind: Literal["doorbell"] = "doorbell"
    context: tuple[str, ...]
    snapshot: Literal["twin"] | None = None
    lock_state: Literal["locked", "unlocked", "unknown"] = "unknown"
    can_request: bool = False
    room: str | None = None


class Counts(Model):
    autonomous: int = 0
    asked: int = 0
    blocked: int = 0
    verified: int = 0


class Scorecard(Card):
    kind: Literal["scorecard"] = "scorecard"
    counts: Counts
    annualized: Annualized | None = None
    window_start: AwareDatetime
    window_end: AwareDatetime


Presentation = Annotated[
    PlanCard | ApprovalCard | VerificationCard | DoorbellCard | Scorecard,
    Field(discriminator="kind"),
]
