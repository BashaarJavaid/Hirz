"""Explicit simulated world events, not a Ring webhook transport."""

from collections.abc import Mapping
from importlib.resources import files
from typing import Literal, Self

from pydantic import AwareDatetime, model_validator

from hirz.adapters.base import AdapterError
from hirz.graph.models import AdapterDomain, Model, Observation
from hirz.twin.adapters import TwinAdapter


class TwinDoorbellEvent(Model):
    kind: Literal["press", "motion", "online", "offline"]
    entity_id: str
    at: AwareDatetime
    classification: Literal["human", "animal", "vehicle"] | None = None

    @model_validator(mode="after")
    def motion(self) -> Self:
        if (self.kind == "motion") != (self.classification is not None):
            raise ValueError("Only motion requires a classification.")
        return self


class TwinDoorbell(TwinAdapter):
    domain: AdapterDomain = "doorbell"
    capabilities = frozenset({"on_event", "snapshot", "live_view_url"})

    async def on_event(
        self, body: bytes, headers: Mapping[str, str]
    ) -> tuple[Observation, ...]:
        if not self.started or headers:
            raise AdapterError(
                "Twin events require a started adapter and empty headers."
            )
        try:
            event = TwinDoorbellEvent.model_validate_json(body)
        except ValueError:
            raise AdapterError(
                "Malformed twin doorbell event; payload withheld."
            ) from None
        return (
            self.world.doorbell_event(
                event.entity_id, event.at, event.kind, event.classification
            ),
        )

    async def snapshot(self, entity_id: str) -> bytes | None:
        observation = self.asset_state(entity_id, "doorbell")
        if observation.state.available is False:
            return None
        return files(__package__).joinpath("snapshot.svg").read_bytes()

    async def live_view_url(self, entity_id: str) -> str | None:
        self.asset_state(entity_id, "doorbell")
        return None
