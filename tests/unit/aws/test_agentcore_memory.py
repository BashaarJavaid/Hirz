"""Pinned SDK contract, pagination and private scope checks; no AWS network."""

import asyncio
from copy import deepcopy
from unittest.mock import Mock
from uuid import uuid4

import boto3
import pytest
from botocore.stub import Stubber

from hirz.aws import client as aws_client
from hirz.aws.memory import AgentCoreMemory, scope
from hirz.memory.models import Page, Session, Turn
from hirz.memory.provider import InProcessMemory, configured
from tests.unit.test_pipeline import AT, HOME, ident

MEMORY = "hirz_test-1234567890"


@pytest.fixture
def turn():
    session = Session(
        household_id=HOME,
        member_id=ident("members", "malik"),
        surface="app",
        session_id="private / session " + "é" * 200,
    )
    return Turn(
        id=uuid4(),
        session=session,
        session_id=session.session_id,
        sequence=1,
        role="user",
        text="I prefer the living room at 72 degrees.",
        recorded_at=AT,
        decision_seq=1,
    )


def event(turn):
    return {
        "memoryId": MEMORY,
        **scope(turn.session),
        "eventId": f"{turn.sequence}#abc",
        "eventTimestamp": turn.recorded_at,
        "payload": [
            {
                "conversational": {
                    "role": turn.role.upper(),
                    "content": {"text": turn.text},
                }
            },
            {"blob": turn.model_dump(mode="json")},
        ],
    }


@pytest.fixture
def backend(monkeypatch):
    sdk = boto3.client(
        "bedrock-agentcore",
        region_name="us-east-1",
        aws_access_key_id="synthetic",
        aws_secret_access_key="synthetic",
    )
    factory = Mock(return_value=sdk)
    monkeypatch.setattr(aws_client, "client", factory)
    provider = AgentCoreMemory(MEMORY)
    factory.assert_not_called()
    with Stubber(sdk) as stub:
        yield provider, stub
        stub.assert_no_pending_responses()
    sdk.close()


@pytest.mark.parametrize("extract", [False, True])
def test_sdk_append_retry_and_unordered_paginated_read(backend, turn, extract):
    provider, stub = backend
    value = event(turn)
    expected = {k: v for k, v in value.items() if k != "eventId"} | {
        "clientToken": str(turn.id)
    }
    if not extract:
        expected["extractionMode"] = "SKIP"
    for _ in range(2):
        stub.add_response("create_event", {"event": value}, expected)
    later = turn.model_copy(update={"id": uuid4(), "sequence": 2, "role": "assistant"})
    args = {
        "memoryId": MEMORY,
        **scope(turn.session),
        "includePayloads": True,
        "maxResults": 100,
    }
    stub.add_response("list_events", {"events": [], "nextToken": "next"}, args)
    stub.add_response(
        "list_events",
        {"events": [event(later), value, value]},
        args | {"nextToken": "next"},
    )

    async def run():
        await provider.append(turn, extract=extract)
        await provider.append(turn, extract=extract)
        assert await provider.turns(turn.session, Page(after=1, limit=1)) == (later,)

    asyncio.run(run())


@pytest.mark.parametrize(
    "changed",
    ["memoryId", "actorId", "sessionId", "embedded_session", "text", "payload"],
)
def test_event_scope_and_content_mismatch_refused(backend, turn, changed):
    provider, stub = backend
    value = deepcopy(event(turn))
    if changed in {"memoryId", "actorId", "sessionId"}:
        value[changed] = "other_memory-1234567890"
    elif changed == "embedded_session":
        value["payload"][1]["blob"]["session"]["household_id"] = str(uuid4())
    elif changed == "text":
        value["payload"][0]["conversational"]["content"]["text"] = "changed"
    else:
        value["payload"] = value["payload"][:1]
    stub.add_response("list_events", {"events": [value]})
    with pytest.raises(ValueError):
        asyncio.run(provider.turns(turn.session))


def test_conflicting_sequences_and_replayed_append_content_refused(backend, turn):
    provider, stub = backend
    altered = turn.model_copy(update={"text": "different"})
    stub.add_response("create_event", {"event": event(altered)})
    stub.add_response("list_events", {"events": [event(turn), event(altered)]})
    with pytest.raises(ValueError, match="append content mismatch"):
        asyncio.run(provider.append(turn))
    with pytest.raises(ValueError, match="sequence conflict"):
        asyncio.run(provider.turns(turn.session))


@pytest.mark.parametrize("failure", ["repeated", "limit"])
def test_pagination_is_bounded(backend, turn, failure):
    provider, stub = backend
    for n in range(2 if failure == "repeated" else 10):
        stub.add_response(
            "list_events",
            {"events": [], "nextToken": "same" if failure == "repeated" else str(n)},
        )
    with pytest.raises(ValueError, match="pagination|scan limit"):
        asyncio.run(provider.turns(turn.session))


@pytest.mark.parametrize("foreign", [False, True])
def test_hints_require_exact_member_namespace(backend, turn, foreign):
    provider, stub = backend
    for strategy in ("preferences",) if foreign else ("preferences", "semantic"):
        namespace = f"/hirz/{scope(turn.session)['actorId']}/{strategy}/"
        stub.add_response(
            "list_memory_records",
            {
                "memoryRecordSummaries": [
                    {
                        "memoryRecordId": "record-" + "1" * 40,
                        "memoryStrategyId": "strategy-1234567890",
                        "createdAt": AT,
                        "namespaces": [namespace + "other/" if foreign else namespace],
                        "content": {"text": "Unaccepted " + strategy},
                    }
                ]
            },
            {"memoryId": MEMORY, "namespace": namespace, "maxResults": 100},
        )
    if foreign:
        with pytest.raises(ValueError, match="namespace mismatch"):
            asyncio.run(provider.hints(turn.session))
    else:
        hints = asyncio.run(provider.hints(turn.session))
        assert [h.text for h in hints] == [
            "Unaccepted preferences",
            "Unaccepted semantic",
        ]
        assert all(h.session == turn.session for h in hints)


def test_scope_and_explicit_configuration(monkeypatch, turn):
    monkeypatch.delenv("HIRZ_MEMORY_ID", raising=False)
    assert isinstance(configured(), InProcessMemory)
    monkeypatch.setenv("HIRZ_MEMORY_ID", MEMORY)
    assert isinstance(configured(), AgentCoreMemory)
    monkeypatch.setenv("HIRZ_MEMORY_ID", "")
    with pytest.raises(ValueError, match="identifier"):
        configured()
    original = scope(turn.session)
    for changes in (
        {"household_id": uuid4()},
        {"member_id": uuid4()},
        {"surface": "alexa"},
        {"session_id": "other"},
    ):
        assert scope(turn.session.model_copy(update=changes)) != original
    assert len(original["sessionId"]) == 64 and "/" not in original["sessionId"]
