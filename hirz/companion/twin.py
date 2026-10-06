"""Durable controls over repository scenario replay, isolated from the signed-in home."""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import sqlalchemy as sa
import yaml
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from hirz import db
from hirz.companion.governance import household
from hirz.graph.seeds import UniqueLoader
from hirz.pipeline.models import Principal
from hirz.pipeline.service import Pipeline
from hirz.twin.scenario import Event, LoadedScenario, run_scenario

# Scenario execution, tariffs and explicit migrations share the deployment's
# working directory, including when Hirz itself is installed from a wheel.
ROOT = Path("scenarios").resolve()
SCENARIOS = ("demo-evening", "demo-evening-hourly", "parents-scam-check")


class Controls(BaseModel):
    model_config = ConfigDict(extra="forbid")
    at: AwareDatetime
    paused: bool = True
    speed: Literal[1, 60] = 60
    injections: list[Event] = Field(default_factory=list, max_length=50)


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["start", "pause", "resume", "step", "inject"]
    id: str | None = Field(default=None, max_length=64)
    scenario: str | None = None
    minutes: int = Field(default=1, ge=1, le=60)
    speed: Literal[1, 60] = 60
    event: Event | None = None

    @model_validator(mode="after")
    def shape(self) -> "Command":
        if (self.operation == "start") != (self.scenario is not None):
            raise ValueError("Choose a scenario only when starting a run")
        if (self.operation == "start") == (self.id is not None):
            raise ValueError("Existing controls require a run")
        if (self.operation == "inject") != (self.event is not None):
            raise ValueError("Injection requires one typed event")
        if self.event and self.event.event not in {
            "presence.arrive",
            "presence.leave",
            "presence.sleep",
            "presence.wake",
            "wearable.recovery",
            "doorbell.press",
            "doorbell.motion",
            "call.inbound",
            "contact.checkin_reply",
        }:
            raise ValueError("Only supported simulated input events may be injected")
        return self


def scenario(name: str) -> LoadedScenario:
    if name not in SCENARIOS:
        raise ValueError("Select a repository scenario")
    loaded = LoadedScenario(ROOT / (name + ".yaml"))
    if any(b.adapter != "twin" for b in loaded.spec.bindings.values()):
        raise ValueError(
            "Companion scenario controls require twin-only device bindings"
        )
    return loaded


def position(row: dict[str, Any], at: datetime) -> datetime:
    controls = Controls.model_validate(row["controls"])
    end = scenario(row["scenario"]).spec.clock.end
    elapsed = (
        0
        if controls.paused
        else max(0, (at - row["updated_at"]).total_seconds()) * controls.speed
    )
    return min(end, controls.at + timedelta(minutes=int(elapsed // 60)))


def time_label(loaded: LoadedScenario, at: datetime) -> str:
    local = at.astimezone(ZoneInfo(loaded.timezone))
    days = (
        local.date()
        - loaded.spec.clock.start.astimezone(ZoneInfo(loaded.timezone)).date()
    ).days
    return (f"+{days}d " if days else "") + local.strftime("%H:%M")


def injected(name: str, controls: Controls, folder: Path) -> LoadedScenario:
    original = ROOT / (name + ".yaml")
    data = yaml.load(original.read_text(), Loader=UniqueLoader)
    data["household"] = str((ROOT / data["household"]).resolve())
    for event in data["timeline"]:
        if event.get("patch"):
            event["patch"] = str((ROOT / event["patch"]).resolve())
    base = scenario(name)
    for event in controls.injections:
        if event.event == "contact.checkin_reply":
            data["timeline"] = [
                e
                for e in data["timeline"]
                if not (e["event"] == event.event and e.get("contact") == event.contact)
            ]
        data["timeline"].append(event.model_dump(mode="json", exclude_unset=True))
    data["timeline"].sort(key=lambda e: base.time(e["at"]))
    path = folder / "scenario.yaml"
    path.write_text(yaml.safe_dump(data))
    return LoadedScenario(path)


async def command(p: Pipeline, principal: Principal, value: Command) -> str:
    if value.operation == "start":
        loaded = scenario(value.scenario or "")
        ident = uuid4().hex
        controls = Controls(at=loaded.spec.clock.start, speed=value.speed)
        member = await p.requester(principal)
        await household(
            p, principal, "twin", {"operation": "start", "reference": ident}
        )
        await p.connection.execute(
            db.companion_runs.insert().values(
                id=ident,
                household_id=p.household_id,
                member_id=UUID(str(member.member_id)),
                principal=principal.model_dump(mode="json"),
                scenario=value.scenario,
                controls=controls.model_dump(mode="json", exclude_unset=True),
                revision=1,
                created_at=p.clock(),
                updated_at=p.clock(),
            )
        )
        return ident
    row = (
        (
            await p.connection.execute(
                sa.select(db.companion_runs).where(
                    p.scope(db.companion_runs),
                    db.companion_runs.c.id == value.id,
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ValueError("Run unavailable")
    loaded = scenario(row["scenario"])
    controls = Controls.model_validate(row["controls"])
    controls.at = position(dict(row), p.clock())
    if value.operation == "step":
        controls.at = min(
            loaded.spec.clock.end, controls.at + timedelta(minutes=value.minutes)
        )
        controls.paused = True
    elif value.operation in {"pause", "resume"}:
        controls.paused = value.operation == "pause"
        controls.speed = value.speed
    else:
        assert value.event
        if not controls.at <= loaded.time(value.event.at) < loaded.spec.clock.end:
            raise ValueError(
                "Inject at the current scenario time or later, before its end"
            )
        controls.injections = [*controls.injections, value.event]
        controls = Controls.model_validate(controls.model_dump(exclude_unset=True))
        with tempfile.TemporaryDirectory(prefix="hirz-twin-validate-") as folder:
            injected(row["scenario"], controls, Path(folder))
    await household(
        p, principal, "twin", {"operation": value.operation, "reference": str(value.id)}
    )
    await p.connection.execute(
        db.companion_runs.update()
        .where(
            p.scope(db.companion_runs),
            db.companion_runs.c.id == value.id,
        )
        .values(
            controls=controls.model_dump(mode="json", exclude_unset=True),
            revision=row["revision"] + 1,
            updated_at=p.clock(),
            principal=principal.model_dump(mode="json"),
        )
    )
    return str(value.id)


async def view(p: Pipeline) -> dict[str, Any]:
    rows = (
        (
            await p.connection.execute(
                sa.select(db.companion_runs)
                .where(p.scope(db.companion_runs))
                .order_by(db.companion_runs.c.created_at.desc())
                .limit(20)
            )
        )
        .mappings()
        .all()
    )
    return {
        "source": "twin",
        "event_schema": Event.model_json_schema(),
        "scenarios": [
            {
                "id": name,
                "start": scenario(name).spec.clock.start.isoformat(),
                "end": scenario(name).spec.clock.end.isoformat(),
            }
            for name in SCENARIOS
        ],
        "runs": [
            {
                "id": r["id"],
                "scenario": r["scenario"],
                "controls": r["controls"],
                "at": position(dict(r), p.clock()).isoformat(),
                "snapshot": r["snapshot"],
                "refreshing": r["revision"] != r["published_revision"]
                or not r["snapshot"]
                or r["snapshot"]["at"] != position(dict(r), p.clock()).isoformat(),
            }
            for r in rows
        ],
    }


async def advance(p: Pipeline) -> None:
    async with p.connection.begin():
        rows = (
            (
                await p.connection.execute(
                    sa.select(db.companion_runs)
                    .where(p.scope(db.companion_runs))
                    .order_by(db.companion_runs.c.created_at.desc())
                    .limit(20)
                )
            )
            .mappings()
            .all()
        )
    for row in rows:
        at = position(dict(row), p.clock())
        if (
            row["published_revision"] == row["revision"]
            and row["snapshot"]
            and row["snapshot"]["at"] == at.isoformat()
        ):
            continue
        principal = Principal.model_validate(row["principal"]).model_copy(
            update={"surface": "scheduler"}
        )
        async with p.connection.begin():
            if not await p.credential_current(principal):
                continue
        controls = Controls.model_validate(row["controls"])
        # ponytail: replay from the seed for each requested snapshot. This trades
        # latency for restart determinism; use persisted runner checkpoints if long
        # scenarios make replay too slow. Every execution replay owns a disposable DB.
        try:
            with tempfile.TemporaryDirectory(prefix="hirz-companion-twin-") as folder:
                loaded = injected(row["scenario"], controls, Path(folder))
                report = await run_scenario(
                    loaded, headless=True, to=time_label(loaded, at), assertions=True
                )
                calls = [c for c in loaded.world.config.inbound_calls if c.at <= at]
                checkins = [
                    {
                        "contact": slug,
                        "requested_at": time_label(loaded, s.requested_at),
                        "reply_at": time_label(loaded, at),
                        "deadline": time_label(loaded, s.deadline),
                        "status": s.status(at),
                    }
                    for s in loaded.world.config.contact_scripts
                    for slug, ident in loaded.references["trusted_contacts"].items()
                    if ident == s.contact_id and s.requested_at <= at
                ]
            snapshot = {
                "at": at.isoformat(),
                "source": "twin",
                "status": report["status"],
                "events": report["events"],
                "checks": report["checks"],
                "observations": report["snapshots"][-1]["observations"]
                if report["snapshots"]
                else [],
                "limitations": report["limitations"],
                "checkins": checkins,
                "claim": calls[-1].summary if calls else None,
            }
        except Exception:
            snapshot = {
                "at": at.isoformat(),
                "source": "twin",
                "status": "failed",
                "error": "Scenario replay failed; inspect the retained private run evidence.",
                "checkins": [],
            }
        async with p.repo.write(p.clock):
            revision = await p.connection.scalar(
                sa.select(db.companion_runs.c.revision).where(
                    p.scope(db.companion_runs), db.companion_runs.c.id == row["id"]
                )
            )
            if revision != row["revision"]:
                continue
            await household(
                p, principal, "twin", {"operation": "publish", "reference": row["id"]}
            )
            await p.connection.execute(
                db.companion_runs.update()
                .where(p.scope(db.companion_runs), db.companion_runs.c.id == row["id"])
                .values(snapshot=snapshot, published_revision=row["revision"])
            )
        return
