"""Local Link protocol smoke over real Pipeline grants and disposable twin storage."""

import argparse
import asyncio
import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import JsonValue

from hirz.audit import export_document, verify_database, verify_file, write_export
from hirz.executor import twin
from hirz.executor.local import compose
from hirz.executor.observations import ingest
from hirz.executor.storage import row
from hirz.link.agent import Agent
from hirz.link.command import DevelopmentSigner, Envelope, Rejected, sign
from hirz.link.store import Store, initialize
from hirz.local import read_env
from hirz.pipeline.hashing import action_hash
from hirz.pipeline.models import Action, Decision, Inverse, Revert
from hirz.twin.disposable import disposable
from scripts.smoke_executor import PRINCIPAL, action, setup


async def run(folder: Path) -> dict[str, Any]:
    folder.mkdir(mode=0o700, parents=False, exist_ok=False)
    async with disposable(read_env(Path(".env"))) as connection:
        p, world = await setup(connection)
        world.clock.set_speed(0)
        registry = await compose(p, world=world, config="presence:twin,energy:twin")
        await registry.start()
        store = None
        try:
            await ingest(p, registry, PRINCIPAL)
            opening = action(world)
            opening = opening.model_copy(
                update={
                    "revert": Revert(
                        after_s=20,
                        inverse=Inverse(
                            **{"class": opening.action_class},
                            target=opening.target,
                            params={"on": False},
                        ),
                    )
                }
            )
            opening = opening.model_copy(update={"content_hash": action_hash(opening)})
            queued = await p.enqueue(opening, PRINCIPAL)
            assert queued.status == "executing"
            decision = await p.redeem(opening, PRINCIPAL)
            assert decision.decision == "execute"
            async with connection.begin():
                stored = await row(p, opening.action_id)
            opening = Action.model_validate(stored["proposal"])
            key = ec.generate_private_key(ec.SECP256R1())
            envelope = sign(
                opening,
                home_id=p.household_id,
                approved_hash=opening.content_hash,
                at=p.clock(),
                signer=DevelopmentSigner(key),
            )
            journal = folder / "link.sqlite"
            initialize(journal, p.household_id, key.public_key())
            store = Store(journal, p.household_id, key.public_key())

            async def apply(
                accepted: Envelope, requested: Action
            ) -> dict[str, JsonValue]:
                assert accepted == envelope
                if requested.action_id == opening.action_id:
                    grant = decision
                else:
                    async with connection.begin():
                        saved = await row(p, requested.action_id)
                    grant = Decision.model_validate(saved["lifecycle"]["decision"])
                await twin.execute(p, world, requested, grant)
                return dict(twin.state(world, requested))

            assert await Agent(store, apply, clock=p.clock).receive(envelope)
            assert twin.state(world, opening)["on"] is True
            with_error = False
            try:
                await Agent(store, apply, clock=p.clock).receive(envelope)
            except Rejected as exc:
                assert str(exc) == "already_claimed"
                with_error = True
            assert with_error
            store.close()
            store = None
            world.clock.jump(p.clock() + timedelta(seconds=21))
            store = Store(journal, p.household_id, key.public_key())
            await Agent(store, apply, clock=p.clock).recover()
            assert twin.state(world, opening)["on"] is False and not store.due(
                p.clock()
            )
            verification, rows = await verify_database(
                connection, p.household_id, p.audit.key.public_key(), collect=True
            )
            assert verification["status"] == "valid"
            write_export(
                folder / "audit.json",
                export_document(p.household_id, p.audit.key.public_key(), rows),
            )
            offline = verify_file(
                folder / "audit.json", p.household_id, key=p.audit.key.public_key()
            )
            assert offline["status"] == "valid"
            report = {
                "source": "twin",
                "signer": "explicit local development key",
                "opening": "pipeline authorized, signed, verified",
                "replay": "refused",
                "restart_ending": "verified",
                "audit_rows": verification["checked_count"],
                "local_receipts": len(store.receipts()),
                "not_checked": "AWS signer/relay, rejection receipt ingestion, physical HA and fully cloud-independent adapter",
            }
            write_export(folder / "report.json", report)
            return report
        finally:
            if store:
                store.close()
            await registry.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(asyncio.run(run(args.artifacts_dir))))
    except Exception as exc:
        print(f"FAIL local Link smoke ({type(exc).__name__}); private details withheld")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
