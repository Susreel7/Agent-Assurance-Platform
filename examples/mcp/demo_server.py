"""Synthetic stdio MCP server for local demos.

Speaks newline-delimited JSON-RPC, which is the framing the MCP adapter uses.
It has no network client, no default host, and no credential. Tool results are
fixed synthetic text so a reviewer can exercise the registry and the adapter
without pointing the process at any real system.
"""

from __future__ import annotations

import json
import sys
from typing import Any

PROTOCOL = "2024-11-05"
SERVER = {"name": "demo-mcp", "version": "0.1.0"}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "echo",
        "description": "Return a short synthetic string. Does not read the filesystem or the network.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "maxLength": 200,
                    "description": "Text to echo back, capped at 200 characters.",
                }
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "describe_workspace",
        "description": "Return a fixed description of this demo server. There is no workspace to inspect.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]


def _result(message_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _error(message_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def _call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "echo":
        text = arguments.get("text", "")
        if not isinstance(text, str):
            text = ""
        body = text[:200]
        return {"content": [{"type": "text", "text": body}], "isError": False}
    if name == "describe_workspace":
        return {
            "content": [
                {
                    "type": "text",
                    "text": (
                        "demo-mcp is a local synthetic server. "
                        "It does not connect to a source host, a package registry, or an identity provider."
                    ),
                }
            ],
            "isError": False,
        }
    return {
        "content": [{"type": "text", "text": f"unknown tool: {name}"}],
        "isError": True,
    }


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    message_id = message.get("id")
    params = message.get("params") if isinstance(message.get("params"), dict) else {}

    if method == "initialize":
        return _result(
            message_id,
            {
                "protocolVersion": PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER,
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return _result(message_id, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        if not isinstance(name, str):
            return _error(message_id, -32602, "tools/call requires a tool name")
        return _result(message_id, _call(name, arguments))
    if method == "ping":
        return _result(message_id, {})
    if message_id is None:
        return None
    return _error(message_id, -32601, f"method not found: {method}")


def main() -> None:
    for line in sys.stdin:
        raw = line.strip()
        if not raw:
            continue
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            sys.stdout.write(json.dumps(_error(None, -32700, "parse error")) + "\n")
            sys.stdout.flush()
            continue
        if not isinstance(message, dict):
            continue
        response = handle(message)
        if response is None:
            continue
        sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
