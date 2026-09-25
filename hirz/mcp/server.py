"""The onboarding-only public surface; household tools follow authentication."""

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from hirz.explainer.models import Speakable
from hirz.mcp.contracts import WhatCanYouDoData, WhatCanYouDoResult
from hirz.mcp.transport import MAX_BODY_BYTES


async def what_can_you_do() -> WhatCanYouDoResult:
    """Describe Hirz and the capabilities available in this local preview."""
    return WhatCanYouDoResult(
        speakable=Speakable(
            headline="Hirz helps families set rules for home automation, plan energy use, and check suspicious requests.",
            details=(
                "This local preview only describes Hirz. Household tools are not connected yet.",
            ),
            options=(),
        ),
        data=WhatCanYouDoData(available_tools=("what_can_you_do",)),
    )


class HirzMCP(FastMCP):
    """New tools require auth wiring and default to the read scope."""

    def __init__(self, *args: Any, authentication: bool = False, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.authentication = authentication
        self.tool_scopes: dict[str, str] = {}

    def add_tool(
        self,
        fn: Any,
        name: str | None = None,
        *args: Any,
        required_scope: str = "hirz:read",
        **kwargs: Any,
    ) -> None:
        from hirz.mcp.auth import SCOPES

        tool_name = name or fn.__name__
        if tool_name != "what_can_you_do":
            if not self.authentication:
                raise ValueError("Protected tools require authentication wiring")
            if required_scope not in SCOPES:
                raise ValueError("Unsupported tool scope")
            self.tool_scopes[tool_name] = required_scope
        elif fn is not what_can_you_do:
            raise ValueError("Only generic onboarding may be anonymous")
        super().add_tool(fn, name, *args, **kwargs)


def create_server(
    security: TransportSecuritySettings, *, authentication: bool = False
) -> HirzMCP:
    server = HirzMCP(
        "Hirz",
        authentication=authentication,
        stateless_http=True,
        json_response=True,
        streamable_http_path="/mcp",
        transport_security=security,
        max_request_body_size=MAX_BODY_BYTES,
    )
    server.add_tool(what_can_you_do, name="what_can_you_do")
    return server
