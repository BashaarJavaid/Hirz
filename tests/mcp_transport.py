"""Raw authenticated transport probes with explicit SDK session initialization."""

import json

import httpx


def document(response):
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        return next(
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ")
            and line[6:].strip()
            and "result" in json.loads(line[6:])
        )
    return response.json()


async def post(client, path, *, json, headers):
    headers = {**headers, "Accept": "application/json, text/event-stream"}
    opened = await client.post(
        path,
        json={
            "jsonrpc": "2.0",
            "id": "init",
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "clientInfo": {"name": "transport-regression", "version": "1"},
                "capabilities": {},
            },
        },
        headers=headers,
    )
    if opened.status_code != 200:
        return opened
    headers |= {
        "mcp-session-id": opened.headers["mcp-session-id"],
        "MCP-Protocol-Version": "2025-11-25",
    }
    await client.post(
        path,
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers=headers,
    )
    response = await client.post(path, json=json, headers=headers)
    await client.delete(path, headers=headers)
    if response.status_code == 200:
        return httpx.Response(
            200,
            json=document(response),
            headers={
                k: v
                for k, v in response.headers.items()
                if k.lower() not in {"content-type", "content-length"}
            },
        )
    return response
