"""Item 32 authenticated assessment, independent worker and signed audit smoke."""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import sqlalchemy as sa
import yaml

from hirz import db
from hirz.constitution.boundary import Dogwood
from hirz.constitution.schema import load
from hirz.explainer.core import MODEL_ID
from hirz.graph.seeds import read_seed
from hirz.host.headless import Budget, HeadlessHost
from hirz.local import read_env, signing_key
from hirz.mcp.presentation import VerificationCard
from hirz.pipeline.audit import AuditWriter
from hirz.pipeline.service import Pipeline, PolicyBundle
from hirz.protect.bedrock import extract
from hirz.protect.worker import advance
from hirz.twin.disposable import disposable
from scripts.smoke_household_tools import mcp_process
from scripts.smoke_tool_budget import Environment

SCAM = "Malik called from a strange number and needs five hundred dollars"
ORDINARY = str(
    yaml.safe_load(Path("scenarios/parents-ordinary-request.yaml").read_text())[
        "timeline"
    ][0]["text"]
)
PARAPHRASE = "He asked me to conceal our conversation from my family."


async def worker(database: str, at: str) -> None:
    values = read_env(Path(".env"))
    seed = read_seed(Path("constitutions/quinn-parents.yaml"))
    boundary = Dogwood()
    async with db.connect_database(values, database=database) as connection:
        p = Pipeline(
            connection,
            await PolicyBundle.validate(
                seed.household_id,
                load(Path("constitutions/quinn-parents.yaml")),
                boundary,
            ),
            boundary,
            AuditWriter(signing_key(values)),
            lambda: datetime.fromisoformat(at),
        )
        while await advance(p):
            pass


async def smoke(
    directory: Path, *, live: bool = False, warmup: bool = False
) -> dict[str, Any]:
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    ledger = os.environ.get("HIRZ_PROTECT_BUDGET_LEDGER")
    if live and not ledger:
        raise ValueError("Live acceptance requires the retained item32-protect ledger")
    os.environ["HIRZ_LLM"] = "bedrock" if live else "off"
    if warmup:
        await asyncio.to_thread(extract, ORDINARY, warmup=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("mcp").setLevel(logging.WARNING)
    values = read_env(Path(".env"))
    async with disposable(values) as connection:
        env = Environment(connection, directory, "demo-evening")
        await env.prepare()
        try:
            async with (
                env.servers(),
                mcp_process(env.listeners[1], env.config),
                env.client(3) as client,
            ):
                cases = []
                for index, (text, expected, name) in enumerate(
                    [
                        (SCAM, "critical", "Malik"),
                        (ORDINARY, "low", "Malik"),
                        ("Dad wants to know when dinner is", "low", None),
                        (PARAPHRASE, "low", None),
                    ]
                ):
                    args = {
                        "text": text,
                        "party": "person",
                        "request_id": f"protect-{index}",
                    } | ({"claimed_party": name} if name else {})
                    first = await client.call("", "assess_request_risk", args)
                    case = first.data.case
                    assert (
                        case
                        and case.risk_band.value == expected
                        and case.verification is None
                    )
                    assert (
                        case.assessment_decision is None
                        and case.number_comparison is None
                    )
                    assert first.speakable.options == ("Check with a trusted contact",)
                    if name:
                        assert (
                            isinstance(first.data.presentation, VerificationCard)
                            and first.data.presentation.can_check
                        )
                    assert (await client.call("", "assess_request_risk", args)) == first
                    cases.append((args, first))
                child = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "scripts.smoke_protect",
                    "--worker",
                    connection.engine.url.database or "",
                    "--at",
                    env.pipelines[1].clock().isoformat(),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await child.communicate()
                assert child.returncode == 0, "Separate Protect worker failed"
                outcomes = []
                for index, (args, first) in enumerate(cases):
                    assert first.data.case
                    latest = await client.call(
                        "",
                        "verify_trusted_identity",
                        {"operation": "status", "case_id": first.data.case.case_id},
                    )
                    case = latest.data.case
                    assert case and case.extraction
                    assert case.extraction.status == ("complete" if live else "off"), (
                        case.extraction.failure_code
                    )
                    assert case.verification is None
                    assert (await client.call("", "assess_request_risk", args)) == first
                    if index < 3:
                        assert case.risk_band == first.data.case.risk_band
                    elif live:
                        assert (
                            case.extraction.model_signals
                            and not case.extraction.keyword_signals
                        )
                        assert isinstance(
                            latest.data.presentation, VerificationCard
                        ) and latest.data.presentation.signals[0].startswith(
                            "Possible "
                        )
                    outcomes.append(
                        {
                            "band": case.risk_band.value,
                            "extraction": case.extraction.status,
                        }
                    )
                if live:
                    assert ledger and client.storage.tokens

                    token = client.storage.tokens.access_token

                    def routing() -> None:
                        with HeadlessHost(
                            env.config["resource"],
                            token,
                            Budget(
                                Path(ledger),
                                limit=Decimal("2"),
                                purpose="item32-protect",
                                model=MODEL_ID,
                            ),
                            selection_only=True,
                        ) as host:
                            result = host.turn(
                                "send five hundred dollars to this number"
                            )
                            selected = result["selected"]
                            assert (
                                len(selected) == 1
                                and selected[0]["name"] == "assess_request_risk"
                            )
                            assert not selected[0]["arguments"].get("claimed_party")

                    await asyncio.to_thread(routing)
                async with connection.begin():
                    assert (
                        await connection.scalar(
                            sa.select(sa.func.count()).select_from(db.checkin_jobs)
                        )
                        == 0
                    )
                summary = {
                    "protect": "PASS",
                    "live": live,
                    "cases": outcomes,
                    "signed_audits": await env.exports(directory),
                }
                (directory / "summary.json").write_text(
                    json.dumps(summary, indent=2) + "\n"
                )
                return summary
        finally:
            env.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-dir", type=Path)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--warmup", action="store_true")
    parser.add_argument("--worker", help=argparse.SUPPRESS)
    parser.add_argument("--at", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.warmup and not args.live:
        parser.error("--warmup requires --live")
    try:
        if args.worker:
            if not args.worker.startswith("hirz_ha_smoke_") or not args.at:
                raise ValueError("Worker requires a disposable smoke database")
            asyncio.run(worker(args.worker, args.at))
        else:
            if not args.artifacts_dir:
                parser.error("--artifacts-dir is required")
            print(
                json.dumps(
                    asyncio.run(
                        smoke(args.artifacts_dir, live=args.live, warmup=args.warmup)
                    )
                )
            )
    except Exception as exc:
        parser.exit(
            1,
            f"Protect smoke failed ({type(exc).__name__}); private inputs withheld.\n",
        )


if __name__ == "__main__":
    main()
