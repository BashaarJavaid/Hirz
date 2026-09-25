"""Explicit household-to-retained-backtest mappings, read only at startup."""

import json
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import yaml
from pydantic import Field, ValidationError

from hirz.graph.models import Model
from hirz.mcp.presentation import Annualized


class EvidenceMapping(Model):
    results_file: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile: str
    household_variant: str
    wear_per_internal_kwh: float = Field(ge=0, allow_inf_nan=False)


class EvidenceFile(Model):
    households: dict[UUID, EvidenceMapping]


def load(path: Path | None) -> dict[UUID, Annualized]:
    if path is None:
        return {}
    try:
        mappings = EvidenceFile.model_validate(yaml.safe_load(path.read_text()))
    except (OSError, ValueError, yaml.YAMLError):
        return {}
    result: dict[UUID, Annualized] = {}
    for household, mapping in mappings.households.items():
        try:
            raw = (path.parent / mapping.results_file).read_bytes()
            if sha256(raw).hexdigest() != mapping.sha256:
                continue
            document = json.loads(raw)
            matches = [
                r
                for r in document["runs"]
                if r["profile"] == mapping.profile
                and r["household"] == mapping.household_variant
                and r["wear_per_internal_kwh"] == mapping.wear_per_internal_kwh
            ]
            if len(matches) != 1:
                continue
            metrics = matches[0]["metrics"]
            result[household] = Annualized(
                usd=metrics["annualized_extrapolation_usd"],
                eligible_days=metrics["eligible_days"],
                total_days=metrics["total_days"],
                sha256=mapping.sha256,
                profile=mapping.profile,
                household_variant=mapping.household_variant,
                wear_per_internal_kwh=mapping.wear_per_internal_kwh,
                period=f"{document['start']} to {document['end']}",
                label=document["label"],
            )
        except (OSError, ValueError, KeyError, TypeError, ValidationError):
            continue
    return result
