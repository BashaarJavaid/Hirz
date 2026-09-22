"""Validated graph inputs. No adapter credentials or authority decisions live here."""

from collections.abc import Mapping, Set
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, Self, get_args
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    field_validator,
    model_validator,
)

from hirz.constitution.conditions import number
from hirz.pipeline.models import PlanConstraint


def policy_number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Policy fact must be numeric")
    rounded = round(value, 4)
    number(rounded)
    return float(rounded)


PolicyNumber = Annotated[float, BeforeValidator(policy_number)]
Text = Annotated[str, Field(min_length=1)]
Source = Literal["real", "real API, demo devices", "twin"]
AdapterDomain = Literal[
    "devices",
    "ev",
    "energy",
    "wearable",
    "calendar",
    "contacts",
    "doorbell",
    "notify",
    "presence",
]
ADAPTER_DOMAINS = get_args(AdapterDomain)
RoomKind = Literal["bedroom", "other"]
Role = Literal["owner", "adult", "teen", "child", "guest", "caregiver"]
RatePlan = Literal["comed_time_of_day", "comed_hourly", "twin"]
AssetKind = Literal[
    "ev",
    "home_battery",
    "solar",
    "appliance",
    "hvac_zone",
    "lock",
    "camera",
    "light",
    "doorbell",
    "shade",
]
ASSET_DOMAINS: dict[AssetKind, AdapterDomain] = {
    "ev": "ev",
    "home_battery": "energy",
    "solar": "energy",
    "doorbell": "doorbell",
    "appliance": "devices",
    "hvac_zone": "devices",
    "lock": "devices",
    "camera": "devices",
    "light": "devices",
    "shade": "devices",
}
Scope = Literal["all", "people", "member", "energy", "environment", "constraints"]
SCOPES = ("all", "people", "member", "energy", "environment", "constraints")


class GraphError(ValueError):
    """Safe, caller-facing graph failure; never include input payloads."""


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise GraphError("A timezone-aware timestamp is required.")
    return value.astimezone(UTC)


def now() -> datetime:
    return datetime.now(UTC)


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Location(Model):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    source: Literal["declared", "twin"]
    street_address: Text | None = None


class Household(Model):
    autonomy_paused: bool = False
    id: UUID
    name: Text
    timezone: Text
    locale: Text
    rate_plan: RatePlan | None = None
    constitution_version: int | None = Field(default=None, gt=0)
    location: Location | None = None

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (KeyError, ValueError):
            raise ValueError("Unknown timezone") from None
        return value


class Entity(Model):
    household_id: UUID
    id: UUID


class Member(Entity):
    display_name: Text
    role: Role


class MemberAccount(Model):
    household_id: UUID
    provider: Text
    sub: Text
    member_id: UUID


class TrustedContact(Entity):
    display_name: Text
    relationship: Text
    member_id: UUID | None = None
    safe_word_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = None


class ContactChannel(Entity):
    contact_id: UUID
    kind: Literal["phone", "email", "hirz_app"]
    value_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    verified_at: AwareDatetime | None = None
    source: Source


class PhysicalParameters(Model):
    capacity_kwh: float | None = Field(default=None, gt=0)
    charger_kw: float | None = Field(default=None, gt=0)
    power_kw: float | None = Field(default=None, gt=0)
    efficiency: float | None = Field(default=None, gt=0, le=1)
    reserve_soc: float | None = Field(default=None, ge=0, le=1)
    kw_peak: float | None = Field(default=None, gt=0)
    cycle_minutes: int | None = Field(default=None, gt=0)
    cycle_kwh: float | None = Field(default=None, gt=0)
    thermal_mass_kwh_per_f: float | None = Field(default=None, gt=0)
    resistance_f_per_kw: float | None = Field(default=None, gt=0)
    hvac_kw: float | None = Field(default=None, gt=0)
    tilt_degrees: float | None = Field(default=None, ge=0, le=90)
    orientation_degrees: float | None = Field(default=None, ge=0, lt=360)


class Asset(Entity):
    name: Text
    kind: AssetKind
    room_kind: RoomKind | None = None
    owner_member_id: UUID | None = None
    capabilities: tuple[Text, ...] | None = None
    physical: PhysicalParameters | None = None


class AssetBinding(Entity):
    asset_id: UUID
    adapter: Text
    entity_id: Text


class AssetPolicy(Entity):
    asset_id: UUID
    soc_min: PolicyNumber | None = Field(default=None, ge=0, le=1)
    needed_by: AwareDatetime | None = None


class Schedule(Entity):
    name: Text
    member_id: UUID | None = None


class ScheduleEvent(Entity):
    schedule_id: UUID
    member_id: UUID | None = None
    zone_id: UUID | None = None
    kind: Literal["arrival", "departure", "calendar", "quiet_hours"]
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    expected_at: AwareDatetime | None = None
    title: Text | None = None

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.ends_at <= self.starts_at:
            raise ValueError("Event must have positive duration")
        if self.expected_at is not None and not (
            self.starts_at <= self.expected_at < self.ends_at
        ):
            raise ValueError("Expected time must be inside the event window")
        return self


class Routine(Entity):
    name: Text
    member_id: UUID | None = None
    days: tuple[Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"], ...]
    from_time: Annotated[str, Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")]
    to_time: Annotated[str, Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")]


class Preference(Entity):
    member_id: UUID
    scope: Literal["household", "member"]
    key: Text
    value: JsonValue
    source: Literal["declared", "learned_accepted"]
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def temperature(self) -> Self:
        if self.key == "temperature_target_f":
            object.__setattr__(self, "value", policy_number(self.value))
        return self


class ObservationState(Model):
    charging: StrictBool | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    charge_limit: PolicyNumber | None = Field(
        default=None, ge=0, le=1, exclude_if=lambda value: value is None
    )
    dispatch_kw: PolicyNumber | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    soc: PolicyNumber | None = Field(default=None, ge=0, le=1)
    temp_f: PolicyNumber | None = None
    target_f: PolicyNumber | None = None
    mode: Literal["heat", "cool", "off"] | None = None
    power_kw: PolicyNumber | None = None
    present: StrictBool | None = None
    sleeping: StrictBool | None = None
    zone_id: UUID | None = None
    plugged_in: bool | None = None
    available: StrictBool | None = None
    locked: bool | None = None
    on: bool | None = None
    recovery_score: int | None = Field(default=None, ge=0, le=100)
    last_press_at: AwareDatetime | None = None
    price_band: Text | None = None
    camera_armed: StrictBool | None = None
    cover_position_percent: PolicyNumber | None = Field(default=None, ge=0, le=100)
    motion_classification: Literal["human", "animal", "vehicle"] | None = None
    last_motion_at: AwareDatetime | None = None


class Observation(Entity):
    domain: AdapterDomain | None = None
    member_id: UUID | None = None
    asset_id: UUID | None = None
    observed_at: AwareDatetime
    source: Source
    state: ObservationState

    @model_validator(mode="after")
    def one_subject(self) -> Self:
        if self.member_id is not None and self.asset_id is not None:
            raise ValueError("An observation has only one subject")
        if (
            self.state.last_press_at is not None
            and self.state.last_press_at > self.observed_at
        ):
            raise ValueError("A press cannot follow its observation")
        # Legacy rows remain readable without assigning them an inferred domain.
        if self.domain is not None:
            state = self.state
            if (
                state.last_motion_at is not None
                and state.last_motion_at > self.observed_at
            ):
                raise ValueError("Motion cannot follow its observation")
            if (state.last_motion_at is None) != (state.motion_classification is None):
                raise ValueError("Motion requires both timestamp and classification")
            if state.last_motion_at is not None and (
                self.domain != "doorbell" or self.asset_id is None
            ):
                raise ValueError("Motion requires a doorbell observation")
            if (
                state.camera_armed is not None
                or state.cover_position_percent is not None
            ) and (self.domain != "devices" or self.asset_id is None):
                raise ValueError("Camera and shade state require device observations")
            if any(
                v is not None for v in (state.present, state.sleeping, state.zone_id)
            ):
                if self.domain != "presence" or self.member_id is None:
                    raise ValueError(
                        "Presence facts require a member presence observation"
                    )
            if state.recovery_score is not None:
                if self.domain != "wearable" or self.member_id is None:
                    raise ValueError("Recovery requires a member wearable observation")
            if state.last_press_at is not None:
                if self.domain != "doorbell" or self.asset_id is None:
                    raise ValueError("Presses require a doorbell observation")
            if state.price_band is not None:
                if (
                    self.domain != "energy"
                    or self.member_id is not None
                    or self.asset_id is not None
                ):
                    raise ValueError(
                        "Price bands require a household energy observation"
                    )
        return self


def observation_subject(observation: Observation) -> UUID:
    return observation.asset_id or observation.member_id or observation.household_id


def validate_observation_scope(
    observation: Observation,
    household_id: UUID,
    members: Set[UUID],
    assets: Mapping[UUID, AssetKind],
    at: datetime,
) -> None:
    """Shared household/time/domain checks for graph, registry and previews."""
    if observation.household_id != household_id or observation.observed_at > utc(at):
        raise GraphError("Invalid observation scope or time.")
    if observation.member_id is not None:
        if observation.member_id not in members:
            raise GraphError("Unknown observation member.")
        if observation.domain is not None and observation.domain not in {
            "presence",
            "wearable",
        }:
            raise GraphError("Invalid member observation domain.")
    elif observation.asset_id is not None:
        kind = assets.get(observation.asset_id)
        if kind is None:
            raise GraphError("Unknown observation asset.")
        if observation.domain is not None and observation.domain != ASSET_DOMAINS[kind]:
            raise GraphError("Invalid asset observation domain.")
    elif observation.domain is not None and observation.domain != "energy":
        raise GraphError("Invalid household observation domain.")
    if (
        observation.state.charging is not None
        or observation.state.charge_limit is not None
    ) and (
        observation.domain != "ev"
        or observation.asset_id is None
        or assets.get(observation.asset_id) != "ev"
    ):
        raise GraphError("Charging controls require an EV observation")
    if observation.state.dispatch_kw is not None and (
        observation.domain != "energy"
        or observation.asset_id is None
        or assets.get(observation.asset_id) != "home_battery"
    ):
        raise GraphError("Battery dispatch requires a battery observation")
    if observation.state.mode is not None and (
        observation.domain != "devices"
        or observation.asset_id is None
        or assets.get(observation.asset_id) != "hvac_zone"
    ):
        raise GraphError(
            "Thermostat mode requires a device observation for an HVAC asset."
        )
    if observation.state.camera_armed is not None and (
        observation.asset_id is None or assets.get(observation.asset_id) != "camera"
    ):
        raise GraphError("Camera state requires a camera asset.")
    if observation.state.cover_position_percent is not None and (
        observation.asset_id is None or assets.get(observation.asset_id) != "shade"
    ):
        raise GraphError("Cover position requires a shade asset.")
    if (
        observation.state.zone_id is not None
        and assets.get(observation.state.zone_id) != "hvac_zone"
    ):
        raise GraphError("Zone must be an HVAC asset in this household.")


class ConstraintSpec(Model):
    kind: Literal[
        "ev_target",
        "ev_ceiling",
        "ev_not_before",
        "ev_deadline",
        "appliance_not_before",
        "appliance_deadline",
        "temperature",
        "temperature_band",
        "manual_hold",
    ]
    asset_id: UUID
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    at: AwareDatetime | None = None
    value: float | None = None
    upper: float | None = None
    mode: Literal["heat", "cool", "off"] | None = None

    @model_validator(mode="after")
    def payload(self) -> Self:
        if utc(self.ends_at) <= utc(self.starts_at):
            raise ValueError("Constraint window must be positive")
        timed = self.kind in {
            "ev_not_before",
            "ev_deadline",
            "appliance_not_before",
            "appliance_deadline",
        }
        if timed != (self.at is not None) or timed == (self.value is not None):
            raise ValueError("Wrong constraint payload")
        if (
            self.kind in {"ev_target", "ev_ceiling"}
            and not 0 <= float(self.value or 0) <= 0.8
        ):
            raise ValueError("Supported EV range is zero through eighty percent")
        if (self.kind == "temperature_band") != (self.upper is not None):
            raise ValueError("Only a temperature band has an upper bound")
        if self.upper is not None and (self.value is None or self.value > self.upper):
            raise ValueError("Temperature band is reversed")
        if (self.kind == "manual_hold") != (self.mode is not None):
            raise ValueError("A manual hold requires its observed mode")
        if self.kind == "manual_hold" and utc(self.ends_at) - utc(
            self.starts_at
        ) != timedelta(hours=2):
            raise ValueError("Manual holds last exactly two hours")
        return self


class ConstraintRecord(Entity):
    member_id: UUID
    asset_id: UUID
    provenance: PlanConstraint
    action_id: Text
    decision_seq: int = Field(gt=0)
    recorded_seq: int = Field(gt=0)
    withdrawn_at: AwareDatetime | None = None
    withdrawn_seq: int | None = Field(default=None, gt=0)
    withdrawal_decision_seq: int | None = Field(default=None, gt=0)
    replaces: UUID | None = None

    @property
    def spec(self) -> ConstraintSpec:
        return ConstraintSpec.model_validate(self.provenance.encoded)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if (
            self.provenance.member_id is not None
            and self.provenance.member_id != self.member_id
        ):
            raise ValueError("Constraint submitter mismatch")
        if self.spec.asset_id != self.asset_id:
            raise ValueError("Constraint asset mismatch")
        if (
            len(
                {
                    self.withdrawn_at is None,
                    self.withdrawn_seq is None,
                    self.withdrawal_decision_seq is None,
                }
            )
            != 1
        ):
            raise ValueError("Withdrawal requires signed evidence")
        return self


# Closed table/model mapping: callers cannot supply SQL identifiers or arbitrary models.
MODELS: dict[str, type[Model]] = {
    "households": Household,
    "members": Member,
    "member_accounts": MemberAccount,
    "trusted_contacts": TrustedContact,
    "contact_channels": ContactChannel,
    "assets": Asset,
    "asset_bindings": AssetBinding,
    "asset_policies": AssetPolicy,
    "schedules": Schedule,
    "schedule_events": ScheduleEvent,
    "routines": Routine,
    "preferences": Preference,
    "observations": Observation,
    "constraints": ConstraintRecord,
}
