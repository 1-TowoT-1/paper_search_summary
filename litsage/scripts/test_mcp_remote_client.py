from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from datetime import timedelta
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def _extract_tool_result(result: Any) -> Any:
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return structured

    content = getattr(result, "content", None) or []
    extracted: list[Any] = []
    for item in content:
        text = getattr(item, "text", None)
        if text is not None:
            try:
                extracted.append(json.loads(text))
            except json.JSONDecodeError:
                extracted.append(text)
        else:
            extracted.append(_jsonable(item))
    return extracted


def _http_client_factory(headers=None, timeout=None, auth=None):
    kwargs: dict[str, Any] = {"trust_env": False}
    if headers is not None:
        kwargs["headers"] = headers
    if timeout is not None:
        kwargs["timeout"] = timeout
    if auth is not None:
        kwargs["auth"] = auth
    return httpx.AsyncClient(**kwargs)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Test a remote LitSage MCP SSE server.")
    parser.add_argument("--url", required=True, help="MCP SSE endpoint, for example http://192.168.1.10:9000/sse")
    parser.add_argument("--tool", default=None, help="Tool name to call. If omitted, only lists tools.")
    parser.add_argument("--arguments-json", default="{}", help="JSON object passed to the tool.")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    tool_arguments = json.loads(args.arguments_json)
    if not isinstance(tool_arguments, dict):
        raise ValueError("--arguments-json must be a JSON object")

    async with sse_client(
        args.url,
        timeout=args.timeout,
        sse_read_timeout=args.timeout,
        httpx_client_factory=_http_client_factory,
    ) as streams:
        async with ClientSession(*streams, read_timeout_seconds=timedelta(seconds=args.timeout)) as session:
            init = await session.initialize()
            print("connected")
            print(json.dumps({"server": _jsonable(init.serverInfo)}, ensure_ascii=False, indent=2))

            tools = await session.list_tools()
            print("tools")
            print(json.dumps([tool.name for tool in tools.tools], ensure_ascii=False, indent=2))

            if args.tool:
                result = await session.call_tool(args.tool, tool_arguments)
                print("result")
                print(json.dumps(_extract_tool_result(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
