import os
import re
from pathlib import Path

from hirz.explainer.models import Speakable


def assert_no_identifiers(speakable: Speakable) -> None:
    for text in (speakable.headline, *speakable.details, *speakable.options):
        assert (
            not re.search(
                r"\b[0-9a-f]{32}\b|\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
                text,
                re.IGNORECASE,
            )
            and "{" not in text
            and "}" not in text
        ), speakable.model_dump()


dogwood = Path(__file__).resolve().parents[1] / ".tools" / "dogwood"
if "HIRZ_DOGWOOD" not in os.environ and dogwood.exists():
    os.environ["HIRZ_DOGWOOD"] = str(dogwood)
