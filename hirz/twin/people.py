"""Deterministic presence, recovery, contact scripts and device state machines."""

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, Field, model_validator

from hirz.adapters.base import AdapterError
from hirz.graph.models import Model, ObservationState, utc
from hirz.twin.environment import stream
from hirz.twin.physics import Nonnegative, changed


class Presence(Model):
    present: bool
    sleeping: bool
    zone_id: UUID | None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.sleeping and (not self.present or self.zone_id is None):
            raise ValueError("Sleep requires presence and a zone.")
        if not self.present and self.zone_id is not None:
            raise ValueError("Absent members cannot occupy a zone.")
        return self


class WeeklyTransition(Model):
    weekday: Annotated[int, Field(ge=0, le=6)]
    minute: Annotated[int, Field(ge=0, lt=1440)]
    kind: Literal["arrive", "leave", "sleep", "wake"]
    zone_id: UUID | None
    jitter_minutes: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def sleep(self) -> Self:
        if self.kind == "sleep" and self.zone_id is None:
            raise ValueError("A sleep transition requires a zone.")
        if self.kind in {"sleep", "wake"} and self.jitter_minutes:
            raise ValueError("Jitter applies to arrivals and departures only.")
        return self


def local_instant(day: date, minute: int, timezone: str) -> datetime:
    naive = datetime.combine(day, time()) + timedelta(minutes=minute)
    # fold=0 selects the first occurrence; the UTC round trip shifts gaps forward.
    return naive.replace(tzinfo=ZoneInfo(timezone), fold=0).astimezone(UTC)


def presence_change(state: Presence, transition: WeeklyTransition) -> Presence:
    if transition.kind == "leave":
        return Presence(present=False, sleeping=False, zone_id=None)
    if transition.kind == "arrive":
        return Presence(present=True, sleeping=False, zone_id=transition.zone_id)
    if transition.kind == "wake":
        return changed(state, sleeping=False)
    return changed(
        state,
        sleeping=state.present,
        zone_id=transition.zone_id if state.present else None,
    )


class Recovery(Model):
    score: Annotated[int, Field(ge=0, le=100)]
    mean: Annotated[float, Field(ge=0, le=100)]
    rho: Annotated[float, Field(ge=-1, le=1)]
    noise_sd: Nonnegative

    def next_day(self, day: date, seed: int, home: UUID, member: UUID) -> Self:
        noise = stream(seed, home, "recovery", str(member), day.isoformat()).gauss(
            0, self.noise_sd
        )
        return changed(
            self,
            score=max(
                0,
                min(
                    100, round(self.mean + self.rho * (self.score - self.mean) + noise)
                ),
            ),
        )


class Device(Model):
    state: ObservationState
    delays: dict[str, Nonnegative]
    fail_next: str | None
    expected_visitor_hint: str | None = None
    pending_kind: str | None = None
    pending_at: AwareDatetime | None = None
    pending_state: ObservationState | None = None
    failed: Annotated[int, Field(ge=0)] = 0

    @model_validator(mode="after")
    def pending(self) -> Self:
        if (
            len(
                {
                    v is None
                    for v in (self.pending_kind, self.pending_at, self.pending_state)
                }
            )
            != 1
        ):
            raise ValueError("Device transition must be complete.")
        if self.fail_next is not None and self.fail_next not in self.delays:
            raise ValueError("Unknown injected failure.")
        if self.pending_kind is not None and self.pending_kind not in self.delays:
            raise ValueError("Unknown pending transition.")
        return self

    def transition(self, kind: str, state: ObservationState, at: datetime) -> Self:
        if (
            self.pending_at is not None
            or kind not in self.delays
            or self.state.available is False
        ):
            raise AdapterError("Device transition unavailable or already pending.")
        return changed(
            self,
            pending_kind=kind,
            pending_at=utc(at) + timedelta(seconds=self.delays[kind]),
            pending_state=state,
        )

    def advance(self, at: datetime) -> Self:
        if self.pending_at is None or utc(at) < utc(self.pending_at):
            return self
        failed = self.fail_next == self.pending_kind
        return changed(
            self,
            state=self.state if failed else self.pending_state,
            failed=self.failed + int(failed),
            fail_next=None if failed else self.fail_next,
            pending_kind=None,
            pending_at=None,
            pending_state=None,
        )


class ContactScript(Model):
    contact_id: UUID
    requested_at: AwareDatetime
    deadline: AwareDatetime
    reply_at: AwareDatetime | None
    reply: Literal["genuine", "not_genuine", "will_call", "no_answer"]

    @model_validator(mode="after")
    def order(self) -> Self:
        if utc(self.deadline) <= utc(self.requested_at):
            raise ValueError("Check-in deadline must follow request.")
        if self.reply == "no_answer":
            if self.reply_at is not None:
                raise ValueError("No-answer has no reply timestamp.")
        elif self.reply_at is None or not utc(self.requested_at) <= utc(
            self.reply_at
        ) < utc(self.deadline):
            raise ValueError("Reply must precede deadline.")
        return self

    def status(self, at: datetime) -> str:
        at = utc(at)
        if at < utc(self.requested_at):
            raise AdapterError("Check-in has not been requested in this simulation.")
        if self.reply_at is not None and at >= utc(self.reply_at):
            return self.reply
        return "no_answer" if at >= utc(self.deadline) else "pending"


class InboundCall(Model):
    """Private world information, deliberately absent from every adapter read."""

    at: AwareDatetime
    presented_number: str | None
    summary: str
