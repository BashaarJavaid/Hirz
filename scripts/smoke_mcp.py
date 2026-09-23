"""Exercise a real local HTTP endpoint through the official MCP client SDK."""

import argparse
import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from hirz.mcp.server import Onboarding


async def smoke(url: str) -> None:
    async with streamable_http_client(url) as (read, write, session_id):
        async with ClientSession(read, write) as session:
            initialized = await session.initialize()
            assert initialized.protocolVersion == "2025-11-25"
            assert session_id() is None
            listed = await session.list_tools()
            assert [tool.name for tool in listed.tools] == ["what_can_you_do"]
            result = await session.call_tool("what_can_you_do", {})
            assert not result.isError
            validated = Onboarding.model_validate(result.structuredContent)
            assert validated.data.available_tools == ("what_can_you_do",)
            print(f"protocol={initialized.protocolVersion}; session_id=none")
            print("tools=what_can_you_do")
            print(validated.model_dump_json())
    print("PASS initialize -> tools/list -> tools/call; structured output validated")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000/mcp")
    args = parser.parse_args()
    try:
        asyncio.run(smoke(args.url))
    except Exception:
        print("FAIL MCP smoke")
        raise


if __name__ == "__main__":
    main()
