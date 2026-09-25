"""Validated action catalog and the single band-to-floor mapping."""

from enum import StrEnum
from importlib.resources import files
from typing import Literal, NotRequired, TypedDict, cast

import yaml


class RiskBand(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


def floor_outcome(band: RiskBand) -> Literal["none", "ask", "never_auto"]:
    floors: dict[RiskBand, Literal["none", "ask", "never_auto"]] = {
        RiskBand.LOW: "none",
        RiskBand.MEDIUM: "none",
        RiskBand.HIGH: "ask",
        RiskBand.CRITICAL: "never_auto",
    }
    return floors[band]


class Profile(TypedDict):
    consumer_actions: NotRequired[list[str]]
    impact: int
    reversibility: str
    band: str
    freshness_seconds: int


def load_catalog(text: str) -> dict[str, Profile]:
    catalog = yaml.safe_load(text)
    if not isinstance(catalog, dict) or not catalog:
        raise ValueError("Invalid risk catalog")
    for name, profile in catalog.items():
        if (
            not isinstance(name, str)
            or len(name.split(".")) != 2
            or not all(part.isidentifier() for part in name.split("."))
            or not isinstance(profile, dict)
            or set(profile) - {"consumer_actions"} != set(Profile.__required_keys__)
            or not isinstance(profile.get("consumer_actions", []), list)
            or any(
                not isinstance(a, str) or not a.isidentifier()
                for a in profile.get("consumer_actions", [])
            )
            or type(profile["impact"]) is not int
            or not 1 <= profile["impact"] <= 5
            or not isinstance(profile["reversibility"], str)
            or not profile["reversibility"].strip()
            or not isinstance(profile["band"], str)
            or profile["band"] not in RiskBand.__members__
            or type(profile["freshness_seconds"]) is not int
            or profile["freshness_seconds"] <= 0
        ):
            raise ValueError("Invalid risk catalog profile")
    return cast(dict[str, Profile], catalog)


CLASSES = load_catalog(files(__package__).joinpath("classes.yaml").read_text())

CONSUMER_ACTIONS = {
    action: name
    for name, profile in CLASSES.items()
    for action in profile.get("consumer_actions", [])
}
