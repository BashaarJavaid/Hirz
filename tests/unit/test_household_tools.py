"""Public contract validation and household-local reporting boundaries."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from hirz.mcp.contracts import (
    TOOLS,
    ActionInput,
    ApprovalInput,
    AuditInput,
    ContextInput,
    PermissionInput,
    RevisionInput,
    input_schema,
    response,
)
from hirz.mcp.household import audit_window, horizon_end
from hirz.risk import CONSUMER_ACTIONS
from tests.conftest import assert_no_identifiers


def test_speech_identifier_check():
    with pytest.raises(AssertionError):
        assert_no_identifiers(response(f"The plan is {uuid4().hex}.").speakable)
    assert_no_identifiers(response("The car limit is 50 percent.").speakable)


def test_every_tool_has_flat_strict_consumer_inputs():
    assert len(TOOLS) == 12
    for schema, _, _ in TOOLS.values():
        value = input_schema(schema)
        assert value["additionalProperties"] is False
        for field in value["properties"].values():
            assert field["description"]
            assert field.get("type") not in {"array", "object"}
        with pytest.raises(ValidationError):
            schema.model_validate({"role": "owner"})
    assert set(CONSUMER_ACTIONS) == {
        "charge_car",
        "stop_charging",
        "set_temperature",
        "turn_on_light",
        "turn_off_light",
        "request_door_unlock",
        "hold_battery",
        "pause_automation",
        "apply_profile",
    }
    assert not any("finance" in value for value in CONSUMER_ACTIONS.values())


@pytest.mark.parametrize(
    "model,args",
    [
        (ActionInput, dict(action="send_money", request_id="x")),
        (ActionInput, dict(action="pause_automation", room="kitchen", request_id="x")),
        (
            ActionInput,
            dict(action="set_temperature", temperature_f=True, request_id="x"),
        ),
        (ActionInput, dict(action="stop_charging", percent=50, request_id="x")),
        (ActionInput, dict(action="hold_battery", request_id="x" * 129)),
        (ApprovalInput, dict(approved="true", plan_id="p", version=1, request_id="x")),
        (ApprovalInput, dict(approved=True, plan_id="p", request_id="x")),
        (ApprovalInput, dict(approved=True, action_id="a", request_id="x")),
        (AuditInput, dict(limit=True)),
        (AuditInput, dict(limit=101)),
        (ContextInput, dict(scope="people", member="Mom")),
        (
            RevisionInput,
            dict(
                text="stop at 50",
                applies_to="car",
                kind="one_time",
                operation="replace",
                change="car_limit",
                percent=50,
                request_id="x",
            ),
        ),
    ],
)
def test_invalid_input(model, args):
    with pytest.raises(ValidationError):
        model.model_validate(args)


def test_horizon_and_windows_use_household_time():
    at = datetime(2026, 9, 24, 0, 0, tzinfo=UTC)
    assert horizon_end(at, "America/Chicago", "tonight") == datetime(
        2026, 9, 24, 13, tzinfo=UTC
    )
    assert horizon_end(at, "America/Chicago", "next_24h") == datetime(
        2026, 9, 25, tzinfo=UTC
    )
    start, end = audit_window(at, "America/Chicago", "last_night")
    assert start.astimezone(UTC) == datetime(2026, 9, 22, 23, tzinfo=UTC)
    assert end.astimezone(UTC) == datetime(2026, 9, 23, 13, tzinfo=UTC)
    assert PermissionInput(action="pause_automation", request_id="x").at is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Hello, how are you?", "low"),
        ("This is urgent", "medium"),
        ("Send money from a strange number", "high"),
        ("Send money from a strange number immediately", "critical"),
        ("No dollars; not urgent; never open the door.", "low"),
        ("Don't tell anyone", "medium"),
        ("keep this secret; courier; police", "critical"),
    ],
)
def test_approved_advice_weights_and_negation(text, expected):
    from hirz.mcp.trust import band, signals

    assert band(signals(text)).value == expected


@pytest.mark.parametrize(
    "number,expected",
    [
        ("(312) 555-0100", "+13125550100"),
        ("1 312 555 0100", "+13125550100"),
        ("+44 20 7946 0123", "+442079460123"),
    ],
)
def test_phone_normalization(number, expected):
    from hirz.mcp.trust import phone

    assert phone(number) == expected


@pytest.mark.parametrize(
    "number", ["3125550100 ext 1", "00442079460123", "+123", "call me", "+1/3125550100"]
)
def test_invalid_phone_is_not_guessed(number):
    from hirz.mcp.trust import phone

    with pytest.raises(ValueError):
        phone(number)


def test_budget_reservations_persist_and_fail_closed(tmp_path):
    import json

    from hirz.host.headless import Budget

    ledger = tmp_path / "budget.json"
    budget = Budget(ledger)
    budget.reserve(1000, 512)
    assert len(json.loads(ledger.read_text())["calls"]) == 1
    restarted = Budget(ledger)
    with pytest.raises(ValueError, match="EXHAUSTED"):
        restarted.reserve(2_000_000, 512)
    assert len(json.loads(ledger.read_text())["calls"]) == 1
    # The higher approved ceiling preserves all earlier reservations.
    ledger.write_text(json.dumps({"reserved_usd": "1.99", "calls": []}))
    restarted.reserve(1000, 512)
    assert json.loads(ledger.read_text())["reserved_usd"] == "1.993916"
    with pytest.raises(ValueError, match="EXHAUSTED"):
        Budget(ledger).reserve(10_000, 512)
    assert len(json.loads(ledger.read_text())["calls"]) == 1


def test_profile_configuration_and_objective_inputs_are_explicit():
    from hirz.mcp.contracts import PlanInput
    from hirz.mcp.profiles import Profile, Profiles

    assert not Profiles().households
    Profile.model_validate(
        {
            "settings": [
                {
                    "action": "set_temperature",
                    "room": "Living room",
                    "temperature_f": 72,
                }
            ]
        }
    )
    for setting in (
        {"action": "request_door_unlock", "room": "Front door"},
        {"action": "set_temperature", "room": "Living room"},
        {"action": "set_temperature", "room": "Living room", "temperature_f": 90},
        {"action": "turn_on_light", "room": "Living room", "temperature_f": 72},
    ):
        with pytest.raises(ValidationError):
            Profile.model_validate({"settings": [setting]})
    for objective in ("cheapest", "greenest", "most_comfortable"):
        assert (
            PlanInput(objective=objective, request_id="explicit").objective == objective
        )
        with pytest.raises(ValidationError):
            PlanInput(objective=objective)
    with pytest.raises(ValidationError):
        ActionInput(
            action="apply_profile",
            profile="night",
            room="Living room",
            request_id="invalid",
        )
    with pytest.raises(ValidationError):
        ActionInput(action="turn_on_light", profile="night", request_id="invalid")


def test_every_verification_outcome_is_labeled_and_bounded():
    from hirz.mcp.trust import case_response
    from hirz.pipeline.models import VerificationCase

    for status in ("pending", "genuine", "not_genuine", "will_call", "no_answer"):
        case = VerificationCase.model_validate(
            dict(
                case_id="private-case",
                claim={"text": "A request"},
                subject=dict(
                    contact_id="private-contact",
                    trusted=True,
                    claimed_party="Relative",
                    party="person",
                ),
                signals=[],
                risk_band="low",
                recommended=["verify_via_verified_channel"],
                speakable={},
                verification=dict(
                    status=status,
                    sent_to="private-contact",
                    started_at="2026-09-23T00:00:00Z",
                    expires_at="2026-09-23T00:02:00Z",
                ),
            )
        )
        result = case_response(case)
        assert result.data.source == "twin"
        speech = result.speakable.model_dump_json()
        assert "simulated" in speech and "private-" not in speech


def test_host_counts_foundation_model_before_reserving_complete_request(tmp_path):
    import json
    from types import SimpleNamespace
    from unittest.mock import Mock

    from hirz.host.headless import Budget, HeadlessHost

    host = HeadlessHost.__new__(HeadlessHost)
    client = Mock()
    client.count_tokens.return_value = {"inputTokens": 24}
    host.model = SimpleNamespace(client=client)
    ledger = tmp_path / "budget.json"
    host.budget = Budget(ledger)
    conversation = {
        "messages": [{"role": "user", "content": [{"text": "Hello"}]}],
        "system": [{"text": "Use household tools."}],
        "toolConfig": {"tools": []},
    }
    request = {**conversation, "inferenceConfig": {"maxTokens": 16}}
    host.reserve({"body": json.dumps(request)})
    client.count_tokens.assert_called_once_with(
        modelId="anthropic.claude-haiku-4-5-20251001-v1:0",
        input={"converse": conversation},
    )
    saved = ledger.read_text()
    assert json.loads(saved)["calls"] == [{"input_tokens": 24, "max_output_tokens": 16}]
    client.count_tokens.side_effect = RuntimeError("Counting unavailable")
    with pytest.raises(RuntimeError, match="Counting unavailable"):
        host.reserve({"body": json.dumps(request)})
    assert ledger.read_text() == saved


def test_headless_host_holds_exact_commitment_and_injects_retry_key():
    from types import SimpleNamespace
    from unittest.mock import Mock

    from hirz.host.headless import HeadlessHost

    host = HeadlessHost.__new__(HeadlessHost)
    host.schemas = {
        name: input_schema(schema) for name, (schema, _, _) in TOOLS.items()
    }
    host.selection_only, host.pending, host.selected = False, None, []
    host.agent = SimpleNamespace(messages=[])
    host.client = Mock()
    host.client.call_tool_sync.return_value = {"status": "queued"}
    event = SimpleNamespace(
        tool_use={
            "name": "execute_household_action",
            "input": {"action": "pause_automation", "request_id": "host"},
        }
    )
    host.before_tool(event)
    assert event.cancel_tool and host.pending
    assert host.pending["arguments"]["request_id"] != "host"
    assert not host.client.call_tool_sync.called
    assert host.confirm(approved=False) == {"status": "declined"}
    assert not host.client.call_tool_sync.called
    host.before_tool(event)
    exact = host.pending
    assert host.confirm(approved=True) == {"status": "queued"}
    assert host.client.call_tool_sync.call_args.args[1:] == (
        exact["name"],
        exact["arguments"],
    )
    assert host.pending is None and host.agent.messages
    event = SimpleNamespace(
        tool_use={
            "name": "get_household_plan",
            "input": {"objective": "greenest", "request_id": "host"},
        }
    )
    host.before_tool(event)
    assert event.cancel_tool and host.pending
    assert host.pending["arguments"]["objective"] == "greenest"
    assert host.confirm(approved=False) == {"status": "declined"}


def test_host_keeps_usage_snapshot_for_each_reported_turn():
    from types import SimpleNamespace
    from unittest.mock import Mock

    from hirz.host.headless import HeadlessHost

    host = HeadlessHost.__new__(HeadlessHost)
    usage = {"inputTokens": 10, "outputTokens": 2, "totalTokens": 12}
    host.agent = Mock(
        return_value=SimpleNamespace(metrics=SimpleNamespace(accumulated_usage=usage))
    )
    first = host.turn("Hello")
    usage["inputTokens"] = 30
    assert first["usage"]["inputTokens"] == 10
    assert host.turn("Again")["usage"]["inputTokens"] == 30


def test_tools_list_size_and_narrow_output_boundary(capsys, caplog):
    import asyncio
    import json
    from unittest.mock import AsyncMock

    from mcp import types

    from hirz.mcp.contracts import OUTPUTS, Result, WhatCanYouDoResult, output_schema
    from hirz.mcp.runtime import register
    from hirz.mcp.server import create_server, what_can_you_do
    from hirz.mcp.transport import local_security

    async def run():
        server = create_server(local_security(8000), authentication=True)
        runtime = AsyncMock()
        register(server, runtime)
        handlers = server._mcp_server.request_handlers
        listed = await handlers[types.ListToolsRequest](
            types.ListToolsRequest(method="tools/list")
        )
        rows = [
            tool.model_dump(
                mode="json",
                by_alias=True,
                include={
                    "name",
                    "description",
                    "inputSchema",
                    "outputSchema",
                    "meta",
                    "annotations",
                },
            )
            for tool in listed.root.tools
        ]
        sizes = {row["name"]: len(json.dumps(row).encode()) for row in rows}
        total = len(json.dumps(rows).encode())
        with capsys.disabled():
            print(f"tools/list bytes={total}; largest tool bytes={max(sizes.values())}")
            for name, size in sizes.items():
                print(f"{name} bytes={size}")
        assert set(sizes) == set(TOOLS) == set(OUTPUTS)
        assert total < 120_000
        assert all(size < 20_000 for size in sizes.values())
        assert next(row for row in rows if row["name"] == "what_can_you_do")[
            "outputSchema"
        ] == output_schema(WhatCanYouDoResult)
        assert isinstance(await what_can_you_do(), WhatCanYouDoResult)

        async def call(name, result):
            runtime.call.return_value = result
            value = await handlers[types.CallToolRequest](
                types.CallToolRequest(
                    method="tools/call",
                    params=types.CallToolRequestParams(name=name, arguments={}),
                )
            )
            return value.root

        unknown = await call("unknown_tool", response("Unused."))
        assert unknown.isError
        assert unknown.structuredContent == response(
            "That request could not be accepted. Check its references and try again.",
            status="failed",
            code="REQUEST_REFUSED",
        ).model_dump(mode="json", by_alias=True)

        for name, schema in OUTPUTS.items():
            for status in ("clarification", "failed"):
                result = response(
                    "Please check your request.",
                    status=status,
                    code="CHECK",
                    options=("Try again",),
                )
                # A persisted receipt has every superset default explicitly set.
                replay = Result.model_validate(result.model_dump(mode="json"))
                for candidate in (result, replay):
                    value = await call(name, candidate)
                    assert not value.isError
                    parsed = schema.model_validate(value.structuredContent)
                    assert parsed.speakable == result.speakable
                    assert parsed.data.status == status
                    assert json.loads(value.content[0].text) == value.structuredContent
                with pytest.raises(ValidationError):
                    schema.model_validate(
                        {**value.structuredContent, "unexpected": True}
                    )
                with pytest.raises(ValidationError):
                    schema.model_validate(
                        {**value.structuredContent, "data": {"unexpected": True}}
                    )
            invalid = response(
                "Please check your request.", available_tools=("secret",)
            )
            if name == "what_can_you_do":
                invalid = response("Please check your request.", reference="secret")
            value = await call(name, invalid)
            assert value.isError
            assert value.structuredContent["data"]["code"] == "UNAVAILABLE"
            assert "secret" not in json.dumps(value.structuredContent)
            assert f"tool={name} error=ValidationError" in caplog.text

    asyncio.run(run())


def test_published_schemas_omit_only_generated_titles():
    from hirz.mcp.contracts import OUTPUTS, ToolSchema

    def without_titles(value):
        if isinstance(value, dict):
            return {k: without_titles(v) for k, v in value.items() if k != "title"}
        if isinstance(value, list):
            return [without_titles(v) for v in value]
        return value

    for model in (*OUTPUTS.values(), *(row[0] for row in TOOLS.values())):
        assert model.model_json_schema(schema_generator=ToolSchema) == without_titles(
            model.model_json_schema()
        )
