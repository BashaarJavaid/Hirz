"""Closed Gateway target until the independent action boundary is implemented."""

from typing import Any, NoReturn


def handler(event: dict[str, Any], context: Any) -> NoReturn:
    # Lambda errors become Gateway tool errors; a returned dict would be tool data.
    # https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-debug-messages.html
    raise RuntimeError("Action boundary unavailable")
