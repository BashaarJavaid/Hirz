"""The persistent helper must agree with the unmodified pinned CLI."""

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from hirz.constitution.boundary import BoundaryError, Dogwood, Event
from hirz.constitution.compiler import boundary_input, compile_policy
from hirz.constitution.evaluator import resolve
from hirz.constitution.preview import SITUATIONS, situation
from hirz.constitution.schema import load
from hirz.pipeline.models import ROLES


def test_helper_matches_reference_and_never_retains_history():
    async def run():
        reference, helper = Dogwood(), Dogwood()
        async with helper.persistent():
            prepared = []
            for seed in ("quinn-home", "quinn-parents"):
                policy = load(Path(f"constitutions/{seed}.yaml"))
                compiled = compile_policy(policy)
                await helper.validate(compiled)
                prepared.append((policy, compiled))
                for name in SITUATIONS:
                    for role in ROLES:
                        action, facts = situation(policy, name, role)
                        outcome = resolve(policy, action, facts)
                        inputs = boundary_input(
                            compiled,
                            action,
                            facts,
                            ttl_minutes=outcome.approval.ttl_minutes,
                            approver_role="owner",
                            approval_channel="app_push",
                            quorum_satisfied=True,
                        )
                        current = Event(60, name, inputs)
                        prior = Event(0, "governance.approve_action", inputs)
                        for approvals in ((prior,), ()):
                            assert await helper.authorize(
                                compiled, current, approvals
                            ) == await reference.authorize(compiled, current, approvals)

            policy, compiled = prepared[0]
            action, facts = situation(policy, "security.door_unlock", "owner")
            inputs = boundary_input(
                compiled,
                action,
                facts,
                ttl_minutes=30,
                approver_role="owner",
                approval_channel="app_push",
                quorum_satisfied=True,
            )
            current = Event(60, "security.door_unlock", inputs)
            prior = Event(0, "governance.approve_action", inputs)
            cases = [
                (compiled, current, (prior,)),
                (compiled, current, ()),
                (compiled, replace(current, timestamp=1800), (prior,)),
                (compiled, replace(current, timestamp=1801), (prior,)),
                (prepared[1][1], current, (prior,)),
            ]
            for key, value in (
                ("household", "quinn-parents"),
                ("action_hash", "other"),
                ("session_id", "other"),
                ("approver_role", "guest"),
                ("approval_channel", "alexa"),
                ("quorum_satisfied", False),
            ):
                cases.append(
                    (compiled, current, (replace(prior, inputs=inputs | {key: value}),))
                )
            expected = [
                await reference.authorize(c, a, approvals) for c, a, approvals in cases
            ]
            actual = await asyncio.gather(
                *(helper.authorize(c, a, approvals) for c, a, approvals in cases)
            )
            assert actual == expected
            assert actual[0].allowed and not actual[1].allowed
            # An exact input change requires new preparation, never an old permit.
            changed = replace(
                compiled, policy=compiled.policy.replace("permit", "forbid")
            )
            await helper.validate(changed)
            assert await helper.authorize(changed, current, (prior,)) == (
                await reference.authorize(changed, current, (prior,))
            )
            assert not (await helper.authorize(changed, current, (prior,))).allowed
            assert (await helper.authorize(compiled, current, (prior,))).allowed
            assert not (await helper.authorize(compiled, current)).allowed
        async with helper.persistent():
            await helper.validate(compiled)
            assert not (await helper.authorize(compiled, current)).allowed

    asyncio.run(run())


@pytest.mark.parametrize("mutation", ["policy", "schema", "trace"])
def test_helper_refuses_unprepared_artifacts_and_malformed_traces(mutation):
    async def run():
        compiled = compile_policy(load(Path("constitutions/quinn-home.yaml")))
        engine = Dogwood()
        async with engine.persistent():
            await engine.validate(compiled)
            process = engine._process
            changed = (
                compiled
                if mutation == "trace"
                else replace(compiled, **{mutation: getattr(compiled, mutation) + "\n"})
            )
            with pytest.raises(BoundaryError):
                await engine.replay(changed, "invalid trace")
            assert process is not None and process.returncode is not None

    asyncio.run(run())
