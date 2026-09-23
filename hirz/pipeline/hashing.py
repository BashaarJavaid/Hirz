"""RFC 8785 wire hashes. Money is explicitly a string, never a binary float."""

import hashlib
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

import rfc8785

from hirz.graph.models import utc
from hirz.pipeline.models import Action


def timestamp(value: datetime) -> str:
    return utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


def wire(value: Any) -> Any:
    if isinstance(value, datetime):
        return timestamp(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Invalid money")
        return format(value, "f")
    if isinstance(value, Mapping):
        return {k: wire(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [wire(v) for v in value]
    return value


def digest(value: Any) -> str:
    try:
        return hashlib.sha256(rfc8785.dumps(wire(value))).hexdigest()
    except (ValueError, TypeError):
        raise ValueError("Invalid canonical data") from None


def action_hash(action: Action) -> str:
    return "sha256:" + digest(
        {
            "class": action.action_class,
            "target": action.target.model_dump(),
            "params": action.params,
            "scheduled_for": action.scheduled_for,
            **(
                {"revert": action.revert.model_dump(by_alias=True)}
                if action.revert
                else {}
            ),
        }
    )


def ingest(action: Action) -> Action:
    try:
        result = Action.model_validate(action.model_dump(mode="python", by_alias=True))
        computed = action_hash(result)
    except (ValueError, TypeError):
        raise ValueError("Invalid action") from None
    if result.content_hash != computed:
        raise ValueError("Invalid action content hash")
    return result.model_copy(
        update={
            "scheduled_for": utc(result.scheduled_for) if result.scheduled_for else None
        }
    )
