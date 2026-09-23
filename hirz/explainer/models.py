"""Narration wire metadata, independent of canonical decision models."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TextModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NarrationMetadata(TextModel):
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    version: str
    provider: Literal["template", "bedrock"]
    model_id: str | None = None
    screen_summary: str = Field(max_length=500)
    fallback_reason: Literal["provider_error", "invalid_response"] | None = None


class Details(TextModel):
    details: tuple[str, ...] = Field(max_length=3)
    screen_summary: str = Field(max_length=500)


class Speakable(TextModel):
    headline: str = Field(min_length=1)
    details: tuple[str, ...] = Field(max_length=3)
    options: tuple[str, ...] = Field(max_length=5)

    @model_validator(mode="after")
    def duration(self) -> Self:
        import re

        if (
            len(self.headline.split()) > 20
            or len(re.findall(r"[.!?](?:\s|$)", self.headline)) > 2
        ):
            raise ValueError("Headline exceeds speech limit")
        if (
            sum(len(s.split()) for s in (self.headline, *self.details, *self.options))
            >= 75
        ):
            raise ValueError("Spoken turn must be under thirty seconds")
        return self


class Narration(TextModel):
    speakable: Speakable
    narration: NarrationMetadata
