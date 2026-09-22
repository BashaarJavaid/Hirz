"""Code-selected facts, templates, and a conservative regex-and-set figure guard.

The guard proves figure membership, not that a figure was used in the right context.
No text in this module is consulted by the authorization or scheduling engines.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from hirz.explainer.models import Details, Narration, NarrationMetadata, Speakable
from hirz.graph.context import ContextSnapshot
from hirz.pipeline.hashing import digest
from hirz.pipeline.models import Action, Decision, Plan
from hirz.risk import CLASSES

if TYPE_CHECKING:
    from hirz.pipeline.service import Pipeline

VERSION = "explainer-1"
MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
# Complete numeric tokens, including altered units/signs, must match exactly.
FIGURE = re.compile(
    r"[+\-−]?(?:[$€£]\s*)?[+\-−]?\d+(?:[.,:]\d+)*"
    r"(?:\s*(?:[aApP][mM]|[°%]|[A-Za-z]+)(?:\s*[FC]\b)?)?"
)
QUANTITY = re.compile(
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    r"thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|"
    r"billion|half|quarter|double|triple|dozen|twice|thrice|minus|plus|negative|positive|first|second|third|fourth)\b",
    re.I,
)
ARTIFACT = re.compile(
    r"[#`*_{}\[\]<>|@\n\r\t]|^\s*[-+•]\s|https?://|\b[\w]+\.[\w]+\b|"
    r"\b[0-9a-f]{16,}\b|\b[0-9a-f]{8}-[0-9a-f-]{27,}\b",
    re.I,
)
# Model prose may explain; it cannot add an execution/approval/notification claim.
CLAIM = re.compile(
    r"\b(?:will|shall|sent|notified|notification|approved|authorized|executed|"
    r"verified|unlock|unlocked|lock|locked|open|opened|scheduled|queued|live|simulated|simulation|emailed|texted|called|delivered|contacted|replied|remind|announce|speak)\b|"
    r"\b(?:I|we)(?:'ll|’ll)\b",
    re.I,
)


@dataclass(frozen=True)
class Context:
    household_id: UUID
    timezone: str = "America/Chicago"
    locale: str = "en-US"
    source: str = "twin"
    names: dict[str, str] = field(default_factory=dict)


def context(snapshot: ContextSnapshot) -> Context:
    home = snapshot.data["households"][0]
    if str(home["id"]) != str(snapshot.household_id):
        raise ValueError("Narration household mismatch")
    return Context(
        snapshot.household_id,
        str(home["timezone"]),
        str(home["locale"]),
        names={str(m["id"]): str(m["display_name"]) for m in snapshot.data["members"]},
    )


async def decision_context(p: "Pipeline", action: Action | None) -> Context:
    if action is None:
        return Context(p.household_id, source="unknown")
    if action.target.adapter == "twin":
        return Context(p.household_id)
    snapshot = await p.snapshot(p.clock())
    assets = {
        str(b["asset_id"])
        for b in snapshot.data["asset_bindings"]
        if b["adapter"] == action.target.adapter
        and b["entity_id"] == action.target.entity
    }
    sources = {
        o["source"]
        for o in snapshot.data["observations"]
        if str(o.get("asset_id")) in assets
    }
    source = (
        "real"
        if sources == {"real"}
        else "real API, demo devices"
        if sources == {"real API, demo devices"}
        else "unknown"
    )
    return Context(p.household_id, source=source)


def decimal(value: float | Decimal, unit: str) -> str:
    number = Decimal(str(value)).quantize(
        Decimal("0.01" if unit in {"USD", "kWh"} else "0.1"), rounding=ROUND_HALF_UP
    )
    if not number:
        number = abs(number)
    text = format(number, "f")
    if unit not in {"USD", "kWh"}:
        text = text.rstrip("0").rstrip(".") if "." in text else text
    return (
        f"${text}" if unit == "USD" else f"{text}{' ' if unit == 'kWh' else ''}{unit}"
    )


def local_time(value: datetime, ctx: Context) -> str:
    if value.utcoffset() is None:
        raise ValueError("Narration requires aware times")
    return value.astimezone(ZoneInfo(ctx.timezone)).strftime("%I:%M %p").lstrip("0")


def display_name(value: str | None) -> str | None:
    # Names are optional data, never a reason to pass arbitrary prose to a provider.
    if (
        value
        and len(value) <= 40
        and re.fullmatch(r"[^\W\d_]+(?:[ '\-][^\W\d_]+){0,3}", value)
    ):
        if not QUANTITY.search(value):
            return value
    return None


def facts(obj: Plan | Decision, ctx: Context) -> dict[str, Any]:
    if isinstance(obj, Plan) and obj.household_id != ctx.household_id:
        raise ValueError("Narration household mismatch")
    result: dict[str, Any] = {"status": obj.status, "source": ctx.source}
    if isinstance(obj, Decision):
        result.update(
            outcome=obj.decision,
            event=obj.event_type.value,
            rule_mode=obj.constitution.mode,
            rule_version=obj.constitution.version,
            rule_subject=obj.constitution.rule.replace(".", " ").replace("_", " ")
            if obj.constitution.rule in CLASSES
            else "household request",
            conditions_met=obj.constitution.conditions_met,
            security=obj.constitution.rule.startswith("security."),
            risk=obj.risk.band.value if obj.risk else None,
            risk_reasons=[f.factor.replace("_", " ") for f in obj.risk.factors]
            if obj.risk
            else [],
        )
        return result
    historical = obj.status in {"refreshing", "superseded", "completed", "abandoned"}
    result.update(revised=obj.supersedes is not None, historical=historical)
    if historical:
        reasons = " ".join(obj.comparison_validity.reasons)
        result["held_reason"] = (
            "Planning temporarily failed; estimates are historical."
            if "temporarily failed" in reasons
            else "Complete runtime inputs are required; estimates are historical."
            if "Complete runtime" in reasons
            else "The supplied forecast ends too soon; estimates are historical."
            if "forecast ends too soon" in reasons
            else "Historical plan; its estimates are not current."
        )
        return result
    result["horizon"] = [
        local_time(obj.horizon.start, ctx),
        local_time(obj.horizon.end, ctx),
    ]
    result["figures"] = {
        key: decimal(getattr(obj.summary, key), unit)
        for key, unit in (
            ("grid_kwh", "kWh"),
            ("solar_kwh", "kWh"),
            ("exported_kwh", "kWh"),
            ("electricity_usd", "USD"),
            ("wear_usd", "USD"),
        )
    }
    saving = obj.summary.estimated_savings_usd
    result["positive_saving"] = bool(
        obj.comparison_validity.valid and saving is not None and saving > 0
    )
    if obj.comparison_validity.valid and saving is not None:
        result["figures"]["timer_difference"] = decimal(saving, "USD")
    if obj.comparison_validity.valid and obj.summary.peak_kwh_avoided is not None:
        result["figures"]["peak_difference"] = decimal(
            obj.summary.peak_kwh_avoided, "kWh"
        )
    result["alternatives"] = {
        a.label: decimal(a.cost_delta_usd, "USD")
        for a in obj.alternatives
        if a.validity.valid and a.cost_delta_usd is not None
    }
    constraints = []
    for c in obj.constraints:
        # Raw text/source strings and memory preference records never leave this process.
        if c.source.startswith("memory:") or c.source.startswith("preference:"):
            continue
        kind = c.encoded.get("kind")
        if kind not in {
            "ev_target",
            "ev_ceiling",
            "ev_not_before",
            "ev_deadline",
            "appliance_not_before",
            "appliance_deadline",
            "temperature",
            "temperature_band",
            "manual_hold",
        }:
            continue
        selected: dict[str, Any] = {
            "requirement": str(kind).replace("_", " "),
            "surface": c.surface,
        }
        selected["linked_account"] = (
            display_name(ctx.names.get(str(c.member_id))) or "household member"
        )
        if c.claimed_author:
            selected["claimed_author"] = (
                display_name(c.claimed_author) or "unverified name"
            )
        for key in ("value", "upper"):
            value = c.encoded.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                selected[key] = decimal(
                    value * 100 if str(kind).startswith("ev_") else value,
                    "%" if str(kind).startswith("ev_") else "°F",
                )
        for key in ("at", "starts_at", "ends_at"):
            value = c.encoded.get(key)
            if isinstance(value, str):
                selected[key] = local_time(datetime.fromisoformat(value), ctx)
        constraints.append(selected)
    result["constraints"] = constraints
    return result


def approved_figures(selected: dict[str, Any]) -> set[str]:
    # Only code-formatted, typed figure fields authorize numbers. Never scan free text.
    values = (
        list(selected.get("figures", {}).values())
        + list(selected.get("alternatives", {}).values())
        + selected.get("horizon", [])
    )
    values += [
        c[k]
        for c in selected.get("constraints", [])
        for k in ("value", "upper", "at", "starts_at", "ends_at")
        if k in c
    ]
    return set(values)


def safe_text(text: str, approved: set[str]) -> None:
    # Remove complete approved forms first only after tokenizing: "$-1.00" cannot authorize "$1.00".
    matches = list(FIGURE.finditer(text))
    if any(m.group() not in approved for m in matches) or QUANTITY.search(text):
        raise ValueError("Unapproved quantity")
    without_figures = FIGURE.sub("", text)
    if (
        re.search(
            r"[$€£%°]|(?<!\w)[+−-](?!\w)|\b(?:Action|Decision|Plan|RiskAssessment|NarrationMetadata)\b",
            without_figures,
        )
        or ARTIFACT.search(without_figures)
        or any(ch.isnumeric() for ch in without_figures)
    ):
        raise ValueError("Formatting or internal identifier")


def skeleton(
    obj: Plan | Decision, selected: dict[str, Any]
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    label = (
        "Real device data."
        if selected["source"] == "real"
        else "Simulated data."
        if selected["source"] == "twin"
        else "Source is not verified as real; shown as simulated."
    )
    if isinstance(obj, Plan):
        headline = {
            "proposed": "The updated plan is ready for review."
            if obj.supersedes
            else "An energy plan is ready for review.",
            "refreshing": "The plan is held for an update.",
            "approved": "The plan has consent; execution is still checked before each action.",
            "active": "The plan is active; individual outcomes require verification.",
            "superseded": "This historical plan has been replaced.",
            "completed": "This plan has ended; review individual action outcomes.",
            "abandoned": "This plan was cancelled.",
        }[obj.status]
        details = [label]
        if selected["historical"]:
            details.append(selected["held_reason"])
        else:
            saving = selected["figures"].get("timer_difference")
            details.append(
                f"Estimated difference versus your timer schedule: {saving}."
                if saving
                else "A valid savings comparison is unavailable."
            )
            if saving and not selected["positive_saving"]:
                details.append(
                    "This estimate offers no saving over the timer schedule."
                )
        if selected.get("constraints"):
            c = selected["constraints"][0]
            attribution = "Linked account: " + c["linked_account"] + "."
            if c.get("claimed_author"):
                attribution += " Claimed author: " + c["claimed_author"] + "."
            details = [details[0], details[1], attribution]
        return headline, tuple(details), ("Review",)
    headline = {
        "execute": "The request is permitted; its outcome is not yet verified.",
        "ask": "This request needs approval on your phone."
        if selected["security"]
        else "This request needs approval.",
        "deny": "This request is not permitted.",
        "verify": "This request needs verification before proceeding.",
    }[obj.decision]
    if obj.status:
        headline = {
            "executing": "Your request is queued.",
            "verified": "The simulated setting was verified."
            if selected["source"] != "real"
            else "The requested setting was verified.",
            "failed": "The requested setting could not be verified.",
            "held": "This request needs your attention.",
            "cancelled": "This request was cancelled.",
            "skipped": "This request's execution window has ended.",
            "dispatched": "The request's outcome is not yet verified.",
        }[obj.status]
    reason = (
        "The household rule prohibits this request."
        if obj.event_type.value == "DENY_CONSTITUTION"
        else "The current risk requires caution."
        if "RISK" in obj.event_type.value
        else "The household budget needs attention."
        if "BUDGET" in obj.event_type.value
        else "The current approval cannot authorize this request."
        if obj.event_type.value.startswith("DENY_APPROVAL")
        else "Current household rules and conditions apply."
    )
    return (
        headline,
        (label, reason),
        ("Review on phone",) if selected["security"] else ("Review",),
    )


def input_hash(selected: dict[str, Any], ctx: Context, provider: str) -> str:
    return digest(
        [
            str(ctx.household_id),
            ctx.timezone,
            ctx.locale,
            selected,
            VERSION,
            provider,
            MODEL_ID if provider == "bedrock" else None,
        ]
    )


def validate(n: Narration, obj: Plan | Decision, ctx: Context) -> Narration:
    n = Narration.model_validate(n.model_dump())
    selected = facts(obj, ctx)
    meta = n.narration
    provider = "bedrock" if meta.model_id else "template"
    if (
        meta.version != VERSION
        or meta.input_hash != input_hash(selected, ctx, provider)
        or meta.model_id not in {None, MODEL_ID}
    ):
        raise ValueError("Stale narration")
    if meta.provider == "bedrock" and (
        meta.model_id != MODEL_ID or meta.fallback_reason
    ):
        raise ValueError("Invalid provider metadata")
    headline, details, options = skeleton(obj, selected)
    if (
        n.speakable.headline != headline
        or n.speakable.options != options
        or not n.speakable.details
        or n.speakable.details[0] != details[0]
    ):
        raise ValueError("Code-owned narration changed")
    approved = approved_figures(selected)
    for text in (headline, *n.speakable.details, *options, meta.screen_summary):
        safe_text(text, approved)
    if meta.provider == "template" and (
        n.speakable.details != details
        or meta.screen_summary != " ".join((headline, *details))
    ):
        raise ValueError("Template text changed")
    if meta.provider == "bedrock":
        if not meta.screen_summary.startswith(details[0] + " "):
            raise ValueError("Missing screen source label")
        prose = " ".join(
            (
                *n.speakable.details[1:],
                meta.screen_summary.removeprefix(details[0] + " "),
            )
        )
        if CLAIM.search(prose):
            raise ValueError("Model made a status claim")
        if not selected.get("positive_saving", False) and re.search(
            r"\b(?:sav\w*|cheaper|less expensive)\b", prose, re.I
        ):
            raise ValueError("Unsupported saving claim")
        for constraint in selected.get("constraints", []):
            if constraint.get("claimed_author"):
                for key in ("linked_account", "claimed_author"):
                    qualifier = key.replace("_", " ") + ": " + constraint[key]
                    if qualifier.casefold() not in prose.casefold():
                        raise ValueError("Claimed attribution omitted")
    return n


def template(
    obj: Plan | Decision,
    ctx: Context,
    *,
    fallback_reason: Any = None,
    provider: str = "template",
) -> Narration:
    selected = facts(obj, ctx)
    headline, details, options = skeleton(obj, selected)
    return validate(
        Narration(
            speakable=Speakable(headline=headline, details=details, options=options),
            narration=NarrationMetadata(
                input_hash=input_hash(selected, ctx, provider),
                version=VERSION,
                provider="template",
                model_id=MODEL_ID if provider == "bedrock" else None,
                screen_summary=" ".join((headline, *details)),
                fallback_reason=fallback_reason,
            ),
        ),
        obj,
        ctx,
    )


def cached(
    obj: Plan | Decision, ctx: Context, provider: str | None = None
) -> Narration | None:
    if obj.narration is None or obj.speakable is None:
        return None
    try:
        n = validate(
            Narration(
                speakable=Speakable.model_validate(obj.speakable),
                narration=obj.narration,
            ),
            obj,
            ctx,
        )
        if provider and n.narration.input_hash != input_hash(
            facts(obj, ctx), ctx, provider
        ):
            return None
        return n
    except ValueError:
        return None


def attach[T: (Plan, Decision)](obj: T, n: Narration) -> T:
    return obj.model_copy(
        update={
            "speakable": n.speakable.model_dump(mode="json"),
            "narration": n.narration,
        }
    )


def prepared[T: (Plan, Decision)](obj: T, ctx: Context) -> T:
    return attach(obj, cached(obj, ctx) or template(obj, ctx))


class Explainer(Protocol):
    async def narrate(self, obj: Plan | Decision, ctx: Context) -> Narration: ...


class TemplateExplainer:
    async def narrate(self, obj: Plan | Decision, ctx: Context) -> Narration:
        return cached(obj, ctx, "template") or template(obj, ctx)


def enriched(obj: Plan | Decision, ctx: Context, output: Details) -> Narration:
    base = template(obj, ctx, provider="bedrock")
    return validate(
        base.model_copy(
            update={
                "speakable": base.speakable.model_copy(
                    update={"details": (base.speakable.details[0], *output.details)}
                ),
                "narration": base.narration.model_copy(
                    update={
                        "provider": "bedrock",
                        "screen_summary": base.speakable.details[0]
                        + " "
                        + output.screen_summary,
                    }
                ),
            }
        ),
        obj,
        ctx,
    )
