"""The onboarding-only public surface; household tools follow authentication."""

from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel

from hirz.explainer.models import Speakable
from hirz.mcp.transport import MAX_BODY_BYTES


class Capabilities(BaseModel):
    available_tools: tuple[Literal["what_can_you_do"], ...]


class Onboarding(BaseModel):
    speakable: Speakable
    data: Capabilities


async def what_can_you_do() -> Onboarding:
    """Describe Hirz and the capabilities available in this local preview."""
    return Onboarding(
        speakable=Speakable(
            headline="Hirz helps families set rules for home automation, plan energy use, and check suspicious requests.",
            details=(
                "This local preview only describes Hirz. Household tools are not connected yet.",
            ),
            options=(),
        ),
        data=Capabilities(available_tools=("what_can_you_do",)),
    )


def create_server(security: TransportSecuritySettings) -> FastMCP:
    server = FastMCP(
        "Hirz",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/mcp",
        transport_security=security,
        max_request_body_size=MAX_BODY_BYTES,
    )
    server.add_tool(what_can_you_do)
    return server
