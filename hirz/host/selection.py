"""Strands selects proposed calls. The async browser host owns all execution."""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from botocore.config import Config  # type: ignore[import-untyped]
from mcp import types
from strands import Agent
from strands.hooks import AfterToolsEvent, BeforeToolCallEvent
from strands.models import BedrockModel
from strands.tools.tools import PythonAgentTool
from strands.types.content import Message
from strands.types.tools import ToolResult

from hirz.explainer.core import MODEL_ID
from hirz.host.headless import SYSTEM, Budget

MODELS = {
    "haiku": (MODEL_ID, "1.10", "5.50"),
    "nova": ("us.amazon.nova-lite-v1:0", "0.06", "0.24"),
}


def select(
    name: str,
    ledger: Path | None,
    tools: list[types.Tool],
    history: list[dict[str, Any]],
    text: str,
) -> tuple[list[tuple[str, dict[str, Any]]], str]:
    if ledger is None:
        raise ValueError("Paid host requires its separate item 29 ledger")
    model_id, inputs, outputs = MODELS[name]
    budget = Budget(
        ledger,
        limit=Decimal("5"),
        input_rate=Decimal(inputs),
        output_rate=Decimal(outputs),
        purpose="item29-host",
        model=model_id,
    )
    model = BedrockModel(
        model_id=model_id,
        region_name="us-east-1",
        streaming=False,
        max_tokens=512,
        temperature=0,
        boto_client_config=Config(
            retries={"total_max_attempts": 1}, connect_timeout=5, read_timeout=30
        ),
    )
    attempts = 0

    def reserve(params: dict[str, Any], **kwargs: Any) -> None:
        nonlocal attempts
        attempts += 1
        if attempts != 1:
            raise ValueError("Automatic inference retries are disabled")
        request = json.loads(params["body"])
        try:
            count = model.client.count_tokens(
                modelId=model_id.removeprefix("us."),
                input={
                    "converse": {
                        k: request[k]
                        for k in ("messages", "system", "toolConfig")
                        if k in request
                    }
                },
            )["inputTokens"]
        except Exception as exc:
            raise ValueError("TOKEN_COUNTING_UNAVAILABLE") from exc
        budget.reserve(count, request["inferenceConfig"]["maxTokens"])

    model.client.meta.events.register("before-call.bedrock-runtime.Converse", reserve)
    calls: list[tuple[str, dict[str, Any]]] = []

    def capture(event: BeforeToolCallEvent) -> None:
        calls.append((event.tool_use["name"], dict(event.tool_use["input"])))
        event.cancel_tool = (
            "Selected for sequential host confirmation; not executed yet."
        )

    def finish(event: AfterToolsEvent) -> None:
        event.end_turn = True

    def unused(*args: Any, **kwargs: Any) -> ToolResult:
        raise RuntimeError("Selection cannot execute tools")

    agent = Agent(
        model=model,
        messages=cast(list[Message], list(history)),
        tools=[
            PythonAgentTool(
                t.name,
                {
                    "name": t.name,
                    "description": t.description or t.name,
                    "inputSchema": {"json": t.inputSchema},
                },
                unused,
            )
            for t in tools
        ],
        system_prompt=SYSTEM.replace(
            "Return only one intended tool per turn.",
            "Select only the next call. Use actual returned tool data for subsequent references. Each mutation is confirmed separately. Security approval and rule activation require the companion app.",
        )
        + "\nThe host obtains exact confirmation before every mutation; do not ask a second commitment question. For a suspicious money request asking whether a known person is genuine, first assess_request_risk, then start verify_trusted_identity for that named trusted contact. A risk assessment alone does not check identity. Compound requests remain unfinished until each requested change is recorded. When a lowered car ceiling conflicts with the current target, propose lowering that target too, subject to the host's separate confirmation. Pending action approvals use the plan's returned decisions and their exact approval references. With no further tool needed, return only a clarification question if information is missing; otherwise return an empty response. The host speaks deterministic tool results itself.",
        callback_handler=None,
        retry_strategy=None,
    )
    agent.hooks.add_callback(BeforeToolCallEvent, capture)
    agent.hooks.add_callback(AfterToolsEvent, finish)
    result = agent(text)
    history[:] = cast(list[dict[str, Any]], list(agent.messages))
    message = str(result).strip()
    # Tool narration is deterministic. Only a short conversational question
    # can become a model-authored prompt; never repeat model outcome claims.
    return calls, message if message.endswith("?") and len(message) <= 500 else ""
