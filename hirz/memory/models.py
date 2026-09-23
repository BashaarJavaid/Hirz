"""Internal memory contracts; no transcript or provider hint grants authority."""

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from hirz.graph.models import Model, PolicyNumber
from hirz.pipeline.models import Decision


class Session(Model):
    household_id: UUID
    member_id: UUID
    surface: Literal["alexa", "app", "scheduler"]
    session_id: str = Field(min_length=1, max_length=256)


class References(Model):
    plan: str | None = Field(default=None, min_length=1)
    action: str | None = Field(default=None, min_length=1)
    verification_case: str | None = Field(default=None, min_length=1)


class TurnInput(Model):
    session_id: str = Field(min_length=1, max_length=256)
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=8000)
    references: References = References()


class Turn(TurnInput):
    id: UUID
    session: Session
    sequence: int = Field(gt=0)
    recorded_at: AwareDatetime
    decision_seq: int = Field(gt=0)

    @model_validator(mode="after")
    def same_session(self) -> Self:
        if self.session_id != self.session.session_id:
            raise ValueError("Turn session identity mismatch")
        return self


class Candidate(Model):
    key: Literal["temperature_target_f"] = "temperature_target_f"
    value: PolicyNumber
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)


class Proposal(Model):
    id: UUID
    household_id: UUID
    member_id: UUID
    source_turn: UUID
    candidate: Candidate
    preference_id: UUID | None
    preference_version: AwareDatetime | None
    status: Literal["pending", "accepted", "rejected"] = "pending"
    created_at: AwareDatetime
    decision_seq: int = Field(gt=0)
    audit_seq: int = Field(gt=0)
    review_seq: int | None = None


class MutationResult(Model):
    decision: Decision
    record: Turn | Proposal | None = None


class Page(Model):
    after: int = Field(default=0, ge=0, strict=True)
    limit: int = Field(default=50, ge=1, le=100, strict=True)
