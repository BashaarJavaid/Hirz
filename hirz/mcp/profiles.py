"""Explicit local household bundles, loaded once before serving tools."""

from pathlib import Path
from typing import Annotated, Literal, Self
from uuid import UUID

import yaml
from pydantic import Field, model_validator

from hirz.graph.models import Model

ProfileName = Literal["recovery_morning", "guests_arriving", "night", "away"]


class Setting(Model):
    action: Literal["set_temperature", "turn_on_light", "turn_off_light"]
    room: str = Field(min_length=1, max_length=200)
    temperature_f: (
        Annotated[float, Field(strict=True, ge=66, le=76, allow_inf_nan=False)] | None
    ) = None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if (self.action == "set_temperature") != (self.temperature_f is not None):
            raise ValueError("Only thermostat settings require a temperature")
        return self


class Profile(Model):
    settings: tuple[Setting, ...] = Field(min_length=1, max_length=20)


class Profiles(Model):
    households: dict[UUID, dict[ProfileName, Profile]] = {}


def load(path: Path | None) -> Profiles:
    return (
        Profiles.model_validate(yaml.safe_load(path.read_text()))
        if path
        else Profiles()
    )
