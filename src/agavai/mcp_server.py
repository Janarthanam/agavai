"""Minimal MCP stdio server exposing the same allowlisted tools."""

from __future__ import annotations

import json
import sys
from typing import Any

from agavai.config import load_config
from agavai.tools import OPENAPI_TOOLS, call_tool

# The microphone and what it recorded stay with the person at the machine.
LOCAL_ONLY = {"start_recording", "list_recordings"}


def _mcp_tools() -> list[dict[str, Any]]:
    out = []
    for item in OPENAPI_TOOLS:
        fn = item["function"]
        if fn["name"] in LOCAL_ONLY:
            continue
        out.append(
            {
                "name": fn["name"],
                "description": fn.get("description", ""),
                "inputSchema": fn.get("parameters") or {"type": "object", "properties": {}},
            }
        )
    return out


def handle(msg: dict[str, Any]) -> dict[str, Any] | None:
    method = msg.get("method")
    mid = msg.get("id")
    cfg = load_config()
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "agavai", "version": "0.1.0"},
            },
        }
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": _mcp_tools()}}
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name") or ""
        args = params.get("arguments") or {}
        text = f"unknown tool {name}" if name in LOCAL_ONLY else call_tool(str(name), args, cfg)
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {"content": [{"type": "text", "text": text}]},
        }
    if mid is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": mid,
        "error": {"code": -32601, "message": f"unknown method {method}"},
    }


def serve_stdio() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        reply = handle(msg)
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()
