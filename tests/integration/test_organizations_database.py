"""Organization saves share the owner Pipeline, history and private case paths."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from test_companion_auth_database import enroll
from test_database import connect
from test_database import scratch_database as scratch_database
from test_pipeline_database import setup

from hirz import db
from hirz.companion import auth
from hirz.constitution.schema import load
from hirz.contacts.checkins import selected
from hirz.contacts.secrets import Config
from hirz.contacts.service import Command, command, guess
from hirz.graph.models import now
from hirz.graph.seeds import load_seeds, read_seed
from hirz.mcp.household import HouseholdTools
from hirz.pipeline.models import Principal
from hirz.pipeline.service import Pipeline, PolicyBundle
from hirz.protect.organizations import registry
from hirz.protect.scoring import signals
from hirz.protect.worker import advance
from tests.unit.test_companion_auth import Authenticator
from tests.unit.test_pipeline import PRINCIPAL, ident

pytestmark = pytest.mark.integration


def test_saved_registry_revision_history_and_isolation(scratch_database, monkeypatch):
    monkeypatch.setenv("HIRZ_LLM", "off")
    config = Config(Fernet.generate_key().decode(), "https://home.example")

    async def run():
        async with connect(scratch_database) as c:
            p = await setup(c, native=True)
            p.clock = now
            parents = read_seed(Path("constitutions/quinn-parents.yaml"))
            await load_seeds(c, [parents], p.clock)
            session = await enroll(
                p,
                await auth.initial_invitation(p, ident("members", "malik")),
                Authenticator(),
            )
            async with c.begin():
                actor = (await auth.session(c, session["session"], p.clock()))[
                    "principal"
                ].model_copy(
                    update={"passkey_verified": True, "requester_confirmed": True}
                )
            value = Command(
                operation="save_organization",
                organization_id="comed",
                registry_revision="2026-10-11",
            )
            tools = HouseholdTools(p, PRINCIPAL)
            serial = 0

            async def assess(**kwargs):
                nonlocal serial
                serial += 1
                result = await tools.call(
                    "assess_request_risk",
                    {
                        "party": "organization",
                        "text": "ComEd wants five hundred dollars from a strange number immediately",
                        "claimed_party": "ComEd",
                        "presented_number": "800-334-7661",
                        "request_id": f"organization-{serial}",
                        **kwargs,
                    },
                )
                assert result.data.case.risk_band.value == "critical"
                assert not result.data.presentation.can_check
                return result

            first = await assess()
            assert first.data.case.number_comparison == "matches"
            assert not first.data.case.subject.trusted
            assert first.data.case.organization_comparison.registry == "matches"
            assert "published" in first.speakable.headline
            for invalid in [
                value.model_copy(update={"registry_revision": "2026-10-10"}),
                value.model_copy(update={"value": "+18005555555"}),
                value.model_copy(update={"organization_id": "unknown"}),
            ]:
                with pytest.raises(ValueError):
                    async with p.repo.write(p.clock):
                        await command(p, actor, invalid, config)
            for invalid_actor in [
                PRINCIPAL,
                actor.model_copy(update={"passkey_verified": False}),
                actor.model_copy(update={"credential_id": "missing"}),
            ]:
                with pytest.raises(ValueError):
                    async with p.repo.write(p.clock):
                        await command(p, invalid_actor, value, config)

            adult_session = await enroll(
                p,
                await auth.initial_invitation(p, ident("members", "mom")),
                Authenticator(),
            )
            async with c.begin():
                adult = (await auth.session(c, adult_session["session"], p.clock()))[
                    "principal"
                ].model_copy(
                    update={"passkey_verified": True, "requester_confirmed": True}
                )
            with pytest.raises(ValueError, match="owner"):
                async with p.repo.write(p.clock):
                    await command(p, adult, value, config)
            with patch.object(
                p.audit,
                "append_many",
                AsyncMock(side_effect=RuntimeError("audit unavailable")),
            ):
                with pytest.raises(RuntimeError, match="audit unavailable"):
                    async with p.repo.write(p.clock):
                        await command(p, actor, value, config)
            async with c.begin():
                assert (
                    await c.scalar(
                        sa.select(sa.func.count())
                        .select_from(db.trusted_contacts)
                        .where(
                            db.trusted_contacts.c.attributes["party"].astext
                            == "organization"
                        )
                    )
                    == 0
                )

            async def save():
                async with connect(scratch_database) as other:
                    q = Pipeline(other, p.bundle, p.boundary, p.audit, now)
                    async with q.repo.write(q.clock):
                        return await command(q, actor, value, config)

            saves = await asyncio.gather(save(), save())
            assert saves[0] == saves[1]
            contact_id = UUID(saves[0]["id"])
            async with c.begin():
                before = await p.repo.get("trusted_contacts", {"id": contact_id})
                channel_before = (
                    (
                        await c.execute(
                            sa.select(db.contact_channels).where(
                                db.contact_channels.c.contact_id == contact_id
                            )
                        )
                    )
                    .mappings()
                    .one()
                )
                assert await selected(p, str(contact_id)) is None
            async with p.repo.write(p.clock):
                await command(p, actor, value, config)
            async with c.begin():
                assert (
                    await p.repo.get("trusted_contacts", {"id": contact_id}) == before
                )
                channel_after = (
                    (
                        await c.execute(
                            sa.select(db.contact_channels).where(
                                db.contact_channels.c.contact_id == contact_id
                            )
                        )
                    )
                    .mappings()
                    .one()
                )
                assert channel_after == channel_before
            matched = await assess(
                claimed_party=" COMMONWEALTH EDISON ",
                presented_number="+1 (800) 334-7661",
            )
            assert matched.data.case.subject.trusted
            assert matched.data.case.organization_comparison.saved_contact == "matches"
            assert "saved ComEd contact and" in matched.speakable.headline
            monkeypatch.setenv("HIRZ_LLM", "bedrock")
            enrichment_args = {
                "party": "organization",
                "claimed_party": "ComEd",
                "presented_number": "800-334-7661",
                "text": "When is ComEd open?",
                "request_id": "organization-enrichment",
            }
            pending = await tools.call("assess_request_risk", enrichment_args)
            assert pending.data.case.risk_band.value == "low"
            assert pending.data.case.extraction.status == "pending"
            with patch(
                "hirz.protect.worker.extract", return_value=signals("dollars urgent")
            ):
                assert await advance(p)
            enriched = await tools.call(
                "verify_trusted_identity",
                {"operation": "status", "case_id": pending.data.case.case_id},
            )
            assert enriched.data.case.risk_band.value == "high"
            assert enriched.data.case.extraction.status == "complete"
            assert (
                enriched.data.case.organization_comparison
                == pending.data.case.organization_comparison
            )
            assert enriched.data.case.number_comparison == "matches"
            assert enriched.data.case.verification is None
            assert any("warning signs" in line for line in enriched.speakable.details)
            assert (
                await tools.call("assess_request_risk", enrichment_args)
            ).model_dump() == pending.model_dump()
            monkeypatch.setenv("HIRZ_LLM", "off")
            for operation in ["word", "invite", "confirm", "revoke"]:
                with pytest.raises(ValueError, match="person workflows"):
                    async with p.repo.write(p.clock):
                        await command(
                            p,
                            actor,
                            Command(
                                operation=operation,
                                contact_id=contact_id,
                                value="test safe word",
                            ),
                            config,
                        )
            with pytest.raises(ValueError, match="Private case"):
                async with p.repo.write(p.clock):
                    await guess(
                        p,
                        actor,
                        matched.data.case.case_id,
                        "test",
                    )
            refused = await tools.call(
                "verify_trusted_identity",
                {
                    "operation": "start",
                    "case_id": matched.data.case.case_id,
                    "request_id": "no-person-check",
                },
            )
            assert refused.data.status == "unavailable"
            q = Pipeline(
                c,
                await PolicyBundle.validate(
                    parents.household_id,
                    load(Path("constitutions/quinn-parents.yaml")),
                    p.boundary,
                ),
                p.boundary,
                p.audit,
                now,
            )
            other = HouseholdTools(
                q, Principal(provider="demo", sub="mom", surface="app")
            )
            isolated = await other.call(
                "assess_request_risk",
                {
                    "party": "organization",
                    "claimed_party": "ComEd",
                    "text": "Utility request",
                    "presented_number": "800-334-7661",
                    "request_id": "other-home",
                },
            )
            assert not isolated.data.case.subject.trusted
            assert isolated.data.case.organization_comparison.saved_revision is None
            with pytest.raises(ValueError, match="unavailable"):
                await other.call(
                    "verify_trusted_identity",
                    {"operation": "status", "case_id": matched.data.case.case_id},
                )
            async with c.begin():
                assert await q.repo.get("trusted_contacts", {"id": contact_id}) is None
            wrong = await assess(presented_number="800-334-7662")
            assert wrong.data.case.number_comparison == "does_not_match"
            assert wrong.data.case.subject.trusted
            for name in ["Com Ed", "CоmEd", "the utility", None]:
                unknown = await assess(claimed_party=name)
                assert unknown.data.case.organization_comparison is None
                assert unknown.data.case.number_comparison == "insufficient_information"
            absent = await assess(presented_number=None)
            assert absent.data.case.subject.trusted
            assert absent.data.case.number_comparison is None
            assert absent.data.case.organization_comparison is None
            assert "number" not in str(absent.speakable.model_dump())
            with pytest.raises(ValueError):
                await assess(presented_number="800-COMED")
            async with p.repo.write(p.clock):
                person = await command(
                    p,
                    actor,
                    Command(
                        operation="create",
                        name="ComEd",
                        relationship="person with similar name",
                    ),
                    config,
                )
            person_case = await tools.call(
                "assess_request_risk",
                {
                    "party": "person",
                    "claimed_party": "ComEd",
                    "text": "When is dinner?",
                    "request_id": "person-comed",
                },
            )
            assert person_case.data.case.subject.contact_id == person["id"]
            assert person_case.data.case.organization_comparison is None
            assert person_case.data.case.number_comparison is None
            with pytest.raises(ValueError, match="unavailable"):
                await HouseholdTools(p, adult).call(
                    "verify_trusted_identity",
                    {"operation": "status", "case_id": matched.data.case.case_id},
                )
            replay_args = {
                "party": "organization",
                "text": "A utility request",
                "claimed_party": "ComEd",
                "presented_number": "800-334-7661",
                "request_id": "immutable-organization",
            }
            replay = await tools.call("assess_request_risk", replay_args)
            original = registry()[0]
            monkeypatch.setattr(
                "hirz.protect.organizations.registry",
                lambda: (original.model_copy(update={"revision": "2026-10-12"}),),
            )
            stale = await assess()
            assert not stale.data.case.subject.trusted
            assert (
                stale.data.case.organization_comparison.saved_revision == "2026-10-11"
            )
            assert (
                stale.data.case.organization_comparison.saved_contact
                == "insufficient_information"
            )
            async with p.repo.write(p.clock):
                await command(
                    p,
                    actor,
                    value.model_copy(update={"registry_revision": "2026-10-12"}),
                    config,
                )
            refreshed = await assess()
            assert refreshed.data.case.subject.trusted
            assert (
                refreshed.data.case.organization_comparison.saved_revision
                == "2026-10-12"
            )
            async with p.repo.write(p.clock):
                await command(
                    p, actor, Command(operation="remove", contact_id=contact_id), config
                )
            removed = await assess()
            assert removed.data.case.number_comparison == "matches"
            assert not removed.data.case.subject.trusted
            assert removed.data.case.organization_comparison.saved_revision is None
            async with connect(scratch_database) as fresh:
                restarted = HouseholdTools(
                    Pipeline(fresh, p.bundle, p.boundary, p.audit, now), PRINCIPAL
                )
                assert (
                    await restarted.call("assess_request_risk", replay_args)
                ).model_dump() == replay.model_dump()
            historical = await tools.call(
                "verify_trusted_identity",
                {"operation": "status", "case_id": matched.data.case.case_id},
            )
            assert historical.data.case == matched.data.case
            async with c.begin():
                assert await p.repo.get("trusted_contacts", {"id": contact_id}) is None
                assert (
                    await c.scalar(
                        sa.select(sa.func.count())
                        .select_from(db.HISTORY_TABLES["contact_channels"])
                        .where(
                            db.HISTORY_TABLES["contact_channels"].c.contact_id
                            == contact_id
                        )
                    )
                    == 2
                )

            async with p.repo.write(p.clock):
                await auth.revoke(p, actor, actor.credential_id, True)
            with pytest.raises(ValueError, match="passkey"):
                async with p.repo.write(p.clock):
                    await command(p, actor, value, config)

    asyncio.run(run())
