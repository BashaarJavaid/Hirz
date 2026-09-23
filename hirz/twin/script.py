"""Strict simulation interfaces for the internal scripted host (not MCP)."""

from typing import Any, Literal, Self

from pydantic import Field, StrictBool, model_validator

from hirz.graph.models import Model
from hirz.pipeline.models import EventType
from hirz.risk import CLASSES


class GetPlan(Model):
    pass


class Revise(Model):
    text: str = Field(min_length=1)
    replaces: str | None = None


class Approve(Model):
    plan: str = "current"
    approved: StrictBool = True


class Execute(Model):
    asset: str
    on: StrictBool
    duration_s: int | None = Field(default=None, gt=0, strict=True)


ARGUMENTS: dict[str, type[Model]] = {
    "get_household_plan": GetPlan,
    "get_household_context": GetPlan,
    "revise_household_plan": Revise,
    "approve_action": Approve,
    "execute_household_action": Execute,
}


class ScriptCall(Model):
    tool: str
    arguments: dict[str, Any]
    save_as: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]*$")

    @model_validator(mode="after")
    def valid(self) -> Self:
        if self.tool not in ARGUMENTS:
            raise ValueError("Unsupported internal scripted call")
        ARGUMENTS[self.tool].model_validate(self.arguments)
        return self


class Binding(Model):
    adapter: Literal["twin", "ha"]
    entity: str = Field(min_length=1)


class Response(Model):
    start: str
    end: str
    member: str
    surface: Literal["alexa", "app"]
    action_class: Literal[
        "energy.hvac_adjust", "energy.appliance_start", "environment.lights"
    ]
    asset: str
    approved: StrictBool


class Execution(Model):
    plan_at: str | None = None
    member: str
    ev_target: float = Field(default=0.5, ge=0, le=0.8)
    ev_needed_by: str | None = None
    rooms: dict[str, Literal["bedroom", "other"]]
    responses: tuple[Response, ...] = ()


class Range(Model):
    min: float | None = Field(default=None, allow_inf_nan=False)
    max: float | None = Field(default=None, allow_inf_nan=False)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if (
            self.min is None
            and self.max is None
            or self.min is not None
            and self.max is not None
            and self.min > self.max
        ):
            raise ValueError("An ordered assertion range is required")
        return self

    def matches(self, value: float | None, tolerance: float = 1e-6) -> bool:
        return (
            value is not None
            and (self.min is None or value >= self.min - tolerance)
            and (self.max is None or value <= self.max + tolerance)
        )


def selector(value: str) -> tuple[str, str | None]:
    event, sep, action_class = value.partition(":")
    EventType(event)
    if (
        sep
        and action_class not in CLASSES
        and action_class not in {"finance.*", "security.*", "energy.*", "environment.*"}
    ):
        raise ValueError("Unknown audit action class selector")
    return event, action_class if sep else None
