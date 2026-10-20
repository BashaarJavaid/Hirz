"""Read-only item 38 Runtime smoke; live invocation needs its own approved window."""

import argparse
import asyncio
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import quote, urlsplit
from uuid import UUID

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from hirz.audit import write_export
from hirz.local import read_env
from hirz.mcp.auth import KeyCache
from hirz.mcp.contracts import TOOLS, GetHouseholdContextResult


def endpoints(runtime_arn: str, user_pool: str) -> tuple[str, str]:
    match = re.fullmatch(
        r"arn:aws:bedrock-agentcore:([a-z0-9-]+):[0-9]{12}:runtime/[A-Za-z0-9_-]+",
        runtime_arn,
    )
    if match is None or not re.fullmatch(
        re.escape(match[1]) + r"_[A-Za-z0-9]+", user_pool
    ):
        raise ValueError("Expected a Runtime ARN and Cognito pool in the same region")
    # Public resource and challenge contract; qualifier is part of the audience.
    # https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-mcp.html
    return (
        f"https://bedrock-agentcore.{match[1]}.amazonaws.com/runtimes/"
        + quote(runtime_arn, safe="")
        + "/invocations?qualifier=DEFAULT",
        f"https://cognito-idp.{match[1]}.amazonaws.com/{user_pool}",
    )


async def discover(http: httpx.AsyncClient, resource: str, issuer: str) -> None:
    url = urlsplit(resource)
    metadata_url = url._replace(
        path=url.path + "/.well-known/oauth-protected-resource"
    ).geturl()
    # Probe a protected read, because local public onboarding may be anonymous.
    refused = await http.post(
        resource,
        headers={"Accept": "application/json, text/event-stream"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "get_household_context", "arguments": {}},
        },
    )
    challenge = refused.headers.get("www-authenticate", "")
    if (
        refused.status_code != 401
        or not challenge.lower().startswith("bearer ")
        or re.findall(r'resource_metadata="([^"\r\n]+)"', challenge) != [metadata_url]
    ):
        raise ValueError("Missing or mismatched Runtime 401 discovery challenge")
    document = await KeyCache().document(http, metadata_url)
    if document.get("resource") != resource or document.get(
        "authorization_servers"
    ) != [issuer]:
        raise ValueError(
            "Runtime metadata does not match the configured resource/issuer"
        )


async def invoke(
    http: httpx.AsyncClient, resource: str, household: UUID
) -> dict[str, Any]:
    started = perf_counter()
    async with streamable_http_client(
        resource, http_client=http, terminate_on_close=False
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            initialized = await session.initialize()
            initialization_ms = (perf_counter() - started) * 1000
            if initialized.protocolVersion != "2025-11-25":
                raise ValueError("Unexpected MCP protocol version")
            names = [tool.name for tool in (await session.list_tools()).tools]
            if len(names) != len(TOOLS) or set(names) != set(TOOLS):
                raise ValueError("Runtime did not expose the exact Hirz tool catalog")
            started = perf_counter()
            result = await session.call_tool("get_household_context", {})
            read_ms = (perf_counter() - started) * 1000
            if result.isError:
                raise ValueError("Authenticated Runtime household read failed")
            value = GetHouseholdContextResult.model_validate(result.structuredContent)
            if (
                value.data.status != "ok"
                or value.data.context is None
                or value.data.context.household_id != household
            ):
                raise ValueError("Runtime did not return the expected linked household")
    return {
        "protocol": initialized.protocolVersion,
        "tool_count": len(names),
        "expected_household": "matched",
        "initialization_ms": initialization_ms,
        "household_read_ms": read_ms,
    }


async def smoke(
    runtime_arn: str, user_pool: str, token: str, household: UUID
) -> dict[str, Any]:
    resource, issuer = endpoints(runtime_arn, user_pool)
    if not re.fullmatch(r"[A-Za-z0-9_.~-]+", token):
        raise ValueError("Missing or malformed access token")
    # Bound the whole SDK exchange as well as individual HTTP waits.
    async with asyncio.timeout(90):
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=False, trust_env=False
        ) as http:
            await discover(http, resource, issuer)
        async with httpx.AsyncClient(
            headers={"Authorization": "Bearer " + token},
            timeout=30,
            follow_redirects=False,
            trust_env=False,
        ) as authenticated:
            report = await invoke(authenticated, resource, household)
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "status": "passed",
        "scope": "Runtime discovery and authenticated read only",
        "challenge": "401 with expected metadata URL",
        "metadata": "resource and issuer matched",
        **report,
        "not_checked": [
            "worker action within 10 seconds",
            "Gateway decision",
            "Link signed/unsigned commands",
            "audit anchor",
            "companion HTTPS and hosted demo",
            "scheduled tick",
            "live models and Memory strategies",
            "warm p95 and verified cold start",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-arn", required=True)
    parser.add_argument("--user-pool", required=True)
    parser.add_argument("--household", required=True, type=UUID)
    parser.add_argument(
        "--token-file",
        required=True,
        type=Path,
        help="Private .env-format file containing HIRZ_ACCEPTANCE_TOKEN",
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    # SDK diagnostics can include server responses; the retained report is redacted.
    previous_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        if args.output.exists() or args.output.is_symlink():
            raise ValueError("Refusing to overwrite evidence")
        token = read_env(args.token_file).get("HIRZ_ACCEPTANCE_TOKEN", "")
        report = asyncio.run(
            smoke(args.runtime_arn, args.user_pool, token, args.household)
        )
        write_export(args.output, report)
        print(json.dumps(report))
        return 0
    except Exception as exc:
        print(
            f"FAIL Runtime read smoke ({type(exc).__name__}); private details withheld"
        )
        return 1
    finally:
        logging.disable(previous_logging)


if __name__ == "__main__":
    raise SystemExit(main())
