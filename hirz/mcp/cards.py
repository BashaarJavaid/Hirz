"""Static MCP Apps resources; templates contain no household or evidence data.

https://github.com/modelcontextprotocol/ext-apps/blob/v2.0.0/specification/2026-01-26/apps.mdx
"""

from pathlib import Path
from typing import Any

from mcp import types
from mcp.server.lowlevel.helper_types import ReadResourceContents
from pydantic import AnyUrl

from hirz.mcp.server import HirzMCP

MIME = "text/html;profile=mcp-app"
NAMES = (
    "plan-card",
    "approval-card",
    "verification-card",
    "doorbell-card",
    "scorecard",
)
TOOLS = {
    "get_household_plan": "plan-card",
    "revise_household_plan": "plan-card",
    "approve_action": "approval-card",
    "execute_household_action": "approval-card",
    "assess_request_risk": "verification-card",
    "verify_trusted_identity": "verification-card",
    "get_household_context": "doorbell-card",
    "get_action_audit": "scorecard",
}


def assets() -> dict[str, str]:
    try:
        values = {
            f"ui://hirz/{name}": (
                Path(__file__).parent / "ui" / f"{name}.html"
            ).read_text()
            for name in NAMES
        }
        if any(
            "</html>" not in value or "<script" not in value
            for value in values.values()
        ):
            raise ValueError("Incomplete card build")
        return values
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            "Build all five MCP cards first: pnpm --filter mcp-app build"
        ) from exc


def register(server: HirzMCP) -> None:
    templates = assets()
    metadata: dict[str, Any] = {
        "ui": {"csp": {"connectDomains": [], "resourceDomains": [], "frameDomains": []}}
    }

    @server._mcp_server.list_resources()  # type: ignore[no-untyped-call, untyped-decorator]
    async def list_resources() -> list[types.Resource]:
        return [
            types.Resource(
                uri=AnyUrl(uri),
                name=name.replace("-", " "),
                mimeType=MIME,
                _meta=metadata,
            )
            for uri, name in zip(templates, NAMES)
        ]

    @server._mcp_server.read_resource()  # type: ignore[no-untyped-call, untyped-decorator]
    async def read_resource(uri: AnyUrl) -> list[ReadResourceContents]:
        return [
            ReadResourceContents(
                content=templates[str(uri)], mime_type=MIME, meta=metadata
            )
        ]
