"""Explicit startup routing; an unknown household is never a local fallback."""

import json
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Route:
    engine_id: str
    gateway_arn: str
    gateway_url: str


@dataclass(frozen=True)
class Routing:
    managed: frozenset[UUID]
    local: frozenset[UUID]
    aws: Route

    def __post_init__(self) -> None:
        if self.managed & self.local:
            raise ValueError("Conflicting household assignments")

    @classmethod
    def parse(cls, text: str, route: Route) -> "Routing":
        data = json.loads(text)
        if not isinstance(data, dict) or set(data) != {"managed", "local"}:
            raise ValueError(
                "Explicit managed and local household assignments required"
            )
        if any(not isinstance(v, list) for v in data.values()):
            raise ValueError("Household assignments must be lists")
        managed = frozenset(UUID(v) for v in data["managed"])
        local = frozenset(UUID(v) for v in data["local"])
        if (
            managed & local
            or len(managed) != len(data["managed"])
            or len(local) != len(data["local"])
        ):
            raise ValueError("Conflicting household assignments")
        return cls(managed, local, route)

    def route(self, household: UUID) -> Route | None:
        if household in self.managed:
            return self.aws
        if household in self.local:
            return None
        raise ValueError("Unknown household boundary assignment")
