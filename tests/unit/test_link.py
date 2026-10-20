"""Signed home commands, durable one-use claims and offline bounded endings."""

import asyncio
from datetime import timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from hirz.link.agent import Agent
from hirz.link.command import DevelopmentSigner, KMSSigner, Rejected, sign, verify
from hirz.link.store import Store, initialize
from hirz.pipeline.hashing import action_hash
from hirz.pipeline.models import ExpectedEffect, Inverse, Revert, Target
from tests.unit.test_executor import queued
from tests.unit.test_pipeline import AT, HOME


def command(key, action=None, *, at=AT, home=HOME, **changes):
    action = action or queued()
    return sign(
        action,
        home_id=home,
        approved_hash=action.content_hash,
        at=at,
        signer=DevelopmentSigner(key),
        **changes,
    )


def bounded():
    action = queued()
    return queued(
        revert=Revert(
            after_s=20,
            inverse=Inverse(
                **{"class": action.action_class},
                target=action.target,
                params={"on": False},
            ),
        )
    )


@pytest.fixture
def key():
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture
def journal(tmp_path, key):
    path = tmp_path / "link.sqlite"
    initialize(path, HOME, key.public_key())
    return path


def test_signed_action_roundtrip_and_key_pin(key):
    envelope = command(key)
    assert (
        verify(
            envelope.model_dump(mode="json", by_alias=True),
            key=key.public_key(),
            home_id=HOME,
            at=AT,
        )
        == envelope
    )
    with pytest.raises(Rejected, match="invalid_signature"):
        verify(
            envelope,
            key=ec.generate_private_key(ec.SECP256R1()).public_key(),
            home_id=HOME,
            at=AT,
        )
    with pytest.raises(ValueError, match="P-256"):
        DevelopmentSigner(ec.generate_private_key(ec.SECP384R1()))


@pytest.mark.parametrize(
    "change", ["unsigned", "tampered", "home", "future", "expired", "long_expiry"]
)
def test_refuses_invalid_envelopes(key, journal, change):
    value = command(key).model_dump(mode="json", by_alias=True)
    at = AT
    if change == "unsigned":
        del value["signature"]
    elif change == "tampered":
        value["command"]["action"]["params"]["on"] = False
    elif change == "home":
        value = command(key, home=uuid4()).model_dump(mode="json", by_alias=True)
    elif change == "future":
        at -= timedelta(seconds=1)
    elif change == "expired":
        at += timedelta(seconds=60)
    else:
        value["command"]["expires_at"] = (AT + timedelta(seconds=61)).isoformat()
    store = Store(journal, HOME, key.public_key())
    try:
        with pytest.raises(Rejected):
            store.reserve(value, at)
        assert [row["event_type"] for row in store.receipts()] == ["LINK_REJECTED"]
        assert (
            store.connection.execute("SELECT count(*) FROM commands").fetchone()[0] == 0
        )
    finally:
        store.close()


def test_signer_recomputes_hash_before_signing(key):
    action = queued()
    signer = Mock()
    with pytest.raises(Rejected, match="hash_mismatch"):
        sign(
            action,
            home_id=HOME,
            approved_hash="sha256:" + "0" * 64,
            at=AT,
            signer=signer,
        )
    tampered = action.model_copy(update={"params": {"on": False}})
    with pytest.raises(ValueError):
        sign(
            tampered,
            home_id=HOME,
            approved_hash=action.content_hash,
            at=AT,
            signer=signer,
        )
    signer.sign.assert_not_called()


def test_kms_digest_wire_contract_and_failure_never_falls_back(key):
    arn = "arn:aws:kms:us-east-1:123456789012:key/test"
    local = DevelopmentSigner(key)
    sdk = Mock()

    def signed(**kwargs):
        assert kwargs["KeyId"] == arn and kwargs["MessageType"] == "DIGEST"
        assert (
            kwargs["SigningAlgorithm"] == "ECDSA_SHA_256"
            and len(kwargs["Message"]) == 32
        )
        return {
            "KeyId": arn,
            "SigningAlgorithm": "ECDSA_SHA_256",
            "Signature": local.sign(kwargs["Message"]),
        }

    sdk.sign.side_effect = signed
    action = queued()
    value = sign(
        action,
        home_id=HOME,
        approved_hash=action.content_hash,
        at=AT,
        signer=KMSSigner(sdk, arn),
    )
    verify(value, key=key.public_key(), home_id=HOME, at=AT)
    sdk.sign.side_effect = OSError("synthetic unavailable provider")
    with pytest.raises(OSError):
        sign(
            action,
            home_id=HOME,
            approved_hash=action.content_hash,
            at=AT,
            signer=KMSSigner(sdk, arn),
        )


def test_replay_and_fresh_envelope_for_claimed_operation_refused_after_restart(
    key, journal
):
    value = command(key)
    store = Store(journal, HOME, key.public_key())
    store.reserve(value, AT)
    store.close()
    store = Store(journal, HOME, key.public_key())
    try:
        for repeat in [value, command(key, queued(action_id="another"))]:
            with pytest.raises(Rejected, match="already_claimed"):
                store.reserve(repeat, AT + timedelta(seconds=1))
        assert len(store.receipts()) == 3
    finally:
        store.close()


def test_explicit_journal_init_pin_and_exclusive_process(key, journal, tmp_path):
    with pytest.raises(FileExistsError):
        initialize(journal, HOME, key.public_key())
    with pytest.raises(ValueError, match="mismatch"):
        Store(journal, uuid4(), key.public_key())
    store = Store(journal, HOME, key.public_key())
    try:
        with pytest.raises(BlockingIOError):
            Store(journal, HOME, key.public_key())
    finally:
        store.close()
    link = tmp_path / "alias"
    link.symlink_to(journal)
    with pytest.raises(OSError):
        Store(link, HOME, key.public_key())
    journal.chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        Store(journal, HOME, key.public_key())


def test_crash_before_dispatch_keeps_ending_and_does_not_retry_opening(key, journal):
    store = Store(journal, HOME, key.public_key())
    value = command(key, bounded())
    store.reserve(value, AT)
    store.close()
    store = Store(journal, HOME, key.public_key())
    try:
        due = store.due(AT + timedelta(seconds=20))
        assert len(due) == 1 and due[0][1].params == {"on": False}
        with pytest.raises(Rejected, match="action_not_due_or_expired"):
            store.reserve(value, AT + timedelta(seconds=20))
    finally:
        store.close()


def test_restart_offline_ending_failure_retry_and_readback(key, journal):
    async def run():
        clock = [AT]
        state = {"on": False}
        calls = []
        fail = [False]

        async def apply(envelope, action):
            calls.append(action.action_id)
            assert envelope.command.home_id == HOME
            if fail[0]:
                raise OSError("private upstream details")
            state.update(action.params)
            return state.copy()

        store = Store(journal, HOME, key.public_key())
        assert await Agent(store, apply, clock=lambda: clock[0]).receive(
            command(key, bounded())
        )
        assert state["on"] is True
        store.close()
        clock[0] += timedelta(seconds=20)
        store = Store(journal, HOME, key.public_key())
        try:
            agent = Agent(store, apply, clock=lambda: clock[0])
            fail[0] = True
            await agent.recover()
            assert store.due(clock[0]) and state["on"] is True
            fail[0] = False
            await agent.recover()
            assert state["on"] is False and store.due(clock[0]) == ()
            await agent.recover()
            assert len(calls) == 3
            assert "private upstream details" not in str(store.receipts())
        finally:
            store.close()

    asyncio.run(run())


def test_backwards_clock_ends_early_and_refuses_new_command(key, journal):
    store = Store(journal, HOME, key.public_key())
    try:
        store.reserve(command(key, bounded()), AT)
        assert store.due(AT + timedelta(seconds=10)) == ()
        assert len(store.due(AT + timedelta(seconds=5))) == 1
        with pytest.raises(Rejected, match="clock_moved_backwards"):
            store.reserve(
                command(key, queued(action_id="next")), AT + timedelta(seconds=5)
            )
    finally:
        store.close()


def test_unknown_or_wrong_readback_cannot_mark_verified(key, journal):
    async def run():
        async def apply(envelope, action):
            return {"on": 1}

        store = Store(journal, HOME, key.public_key())
        try:
            assert not await Agent(store, apply, clock=lambda: AT).receive(command(key))
            assert store.receipts()[-1]["event_type"] == "VERIFY_FAILED"
        finally:
            store.close()

    asyncio.run(run())


def test_semantic_replay_window_is_24_hours(key, journal):
    action = queued(
        scheduled_for=None,
        expected_effect=ExpectedEffect(
            entity="light.living_room",
            attr="on",
            value=True,
            by=AT + timedelta(days=2),
        ),
    )
    assert action.content_hash == action_hash(action)
    store = Store(journal, HOME, key.public_key())
    try:
        store.reserve(command(key, action), AT)
        other = action.model_copy(update={"action_id": "next"})
        with pytest.raises(Rejected, match="already_claimed"):
            store.reserve(
                command(key, other, at=AT + timedelta(hours=23)),
                AT + timedelta(hours=23),
            )
        store.reserve(
            command(key, other, at=AT + timedelta(hours=25)), AT + timedelta(hours=25)
        )
    finally:
        store.close()


def test_bounded_unlock_relocks_after_offline_restart(key, journal):
    async def run():
        target = Target(adapter="twin", entity="lock.front_door")
        action = queued(
            action_class="security.door_unlock",
            target=target,
            params={"locked": False, "open_minutes": 0.25},
            expected_effect=ExpectedEffect(
                entity=target.entity,
                attr="locked",
                value=False,
                by=AT + timedelta(seconds=10),
            ),
            revert=Revert(
                after_s=15,
                inverse=Inverse(
                    **{"class": "security.door_unlock"},
                    target=target,
                    params={"locked": True, "open_minutes": 0},
                ),
            ),
        )
        state = {"locked": True}

        async def apply(envelope, requested):
            state["locked"] = requested.params["locked"]
            return state.copy()

        store = Store(journal, HOME, key.public_key())
        assert await Agent(store, apply, clock=lambda: AT).receive(command(key, action))
        assert state["locked"] is False
        store.close()
        store = Store(journal, HOME, key.public_key())
        try:
            await Agent(
                store, apply, clock=lambda: AT + timedelta(seconds=16)
            ).recover()
            assert state["locked"] is True
            assert not store.due(AT + timedelta(seconds=16))
        finally:
            store.close()

    asyncio.run(run())


def test_journal_failure_prevents_actuation(key, journal, monkeypatch):
    async def run():
        invoked = []

        async def apply(envelope, requested):
            invoked.append(requested)
            return {"on": True}

        store = Store(journal, HOME, key.public_key())

        def fail(*args, **kwargs):
            raise OSError("synthetic disk failure")

        monkeypatch.setattr(store, "receipt", fail)
        try:
            with pytest.raises(OSError):
                await Agent(store, apply, clock=lambda: AT).receive(command(key))
            assert invoked == []
            assert (
                store.connection.execute("SELECT count(*) FROM commands").fetchone()[0]
                == 0
            )
        finally:
            store.close()

    asyncio.run(run())


@pytest.mark.parametrize("climate", [False, True])
def test_home_transport_requires_signed_claim_and_direct_readback(
    key, journal, tmp_path, climate
):
    from hirz.link.devices import Devices
    from tests.unit.test_ha import Recorded, adapter

    async def run():
        recorded = Recorded()
        ha = adapter(tmp_path, recorded)
        await ha.start()
        store = Store(journal, HOME, key.public_key())
        entity, attr, value = (
            ("climate.demo", "target_f", 72) if climate else ("light.demo", "on", True)
        )
        opening = queued(
            action_class="energy.hvac_adjust" if climate else "environment.lights",
            target=Target(adapter="ha", entity=entity),
            params={attr: value},
            expected_effect=ExpectedEffect(
                entity=entity, attr=attr, value=value, by=AT + timedelta(seconds=30)
            ),
        )
        envelope = command(key, opening)
        devices = Devices(ha, store, clock=lambda: AT)
        try:
            with pytest.raises(Rejected, match="unclaimed_command"):
                await devices(envelope, opening)
            assert not recorded.calls
            assert await Agent(store, devices, clock=lambda: AT).receive(envelope)
            assert len([r for r in recorded.calls if r.method == "POST"]) == 1
            with pytest.raises(Rejected, match="unclaimed_command"):
                await devices(envelope, opening)
            assert len([r for r in recorded.calls if r.method == "POST"]) == 1
        finally:
            store.close()
            await ha.close()

    asyncio.run(run())
