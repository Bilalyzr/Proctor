"""MCP server for the SUT tools (blueprint Domain 7 / MCP-1).

JSON-RPC 2.0 over stdio (``python -m sut.mcp_server``) or an in-memory
transport for contract tests. Implements the MCP surface the blueprint
requires: initialize handshake with capability negotiation, tools/list with
inputSchema, tools/call with the isError error-transport distinction, and
correct JSON-RPC error codes (-32700 parse, -32601 method not found, -32602
invalid params). Protocol version mismatches negotiate down to the server's
version with a clear error for unsupported majors.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from sut.tools.base import ToolRegistry, ToolResult, build_default_registry

PROTOCOL_VERSION = "2024-11-05"
SUPPORTED_VERSIONS = ("2024-11-05", "2025-06-18")
JSONRPC_VERSION = "2.0"

PARSE_ERROR = -32700
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}


class McpServer:
    """In-memory MCP server over the shared ToolRegistry."""

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self.registry = registry if registry is not None else build_default_registry()
        self._initialized = False
        self.tools_changed_notifications = 0

    # ------------------------------------------------------------------ api
    def handle_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Handle one parsed JSON-RPC message; None for notifications."""
        method = message.get("method")
        if method is None:
            return _error(message.get("id"), INVALID_PARAMS, "missing method")
        if not isinstance(method, str):
            return _error(message.get("id"), PARSE_ERROR, "method must be a string")

        if method == "initialize":
            return self._initialize(message)
        if method == "notifications/initialized":
            self._initialized = True
            return None
        if method == "tools/list":
            return self._tools_list(message)
        if method == "tools/call":
            return self._tools_call(message)
        return _error(message.get("id"), METHOD_NOT_FOUND, f"unknown method: {method}")

    def handle_raw(self, raw: str) -> str | None:
        """Handle one raw JSON line; malformed input yields -32700."""
        try:
            message = json.loads(raw)
        except json.JSONDecodeError as exc:
            return json.dumps(_error(None, PARSE_ERROR, f"parse error: {exc.msg}"))
        if not isinstance(message, dict):
            return json.dumps(_error(None, PARSE_ERROR, "request must be an object"))
        response = self.handle_message(message)
        return None if response is None else json.dumps(response, sort_keys=True, default=str)

    # ------------------------------------------------------------- handlers
    def _initialize(self, message: dict[str, Any]) -> dict[str, Any]:
        params = message.get("params") or {}
        requested = params.get("protocolVersion", PROTOCOL_VERSION)
        if requested not in SUPPORTED_VERSIONS:
            return _error(
                message.get("id"),
                INVALID_PARAMS,
                f"unsupported protocolVersion {requested}; server supports {SUPPORTED_VERSIONS}",
            )
        return _result(
            message.get("id"),
            {
                "protocolVersion": min(requested, SUPPORTED_VERSIONS[0])
                if requested >= SUPPORTED_VERSIONS[0]
                else SUPPORTED_VERSIONS[0],
                "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": {"name": "shopfast-refund-tools", "version": "1.0.0"},
            },
        )

    def _tools_list(self, message: dict[str, Any]) -> dict[str, Any]:
        tools = [spec.to_mcp() for spec in self.registry.list_tools()]
        return _result(
            message.get("id"),
            {"tools": tools, "nextCursor": None},
        )

    def _tools_call(self, message: dict[str, Any]) -> dict[str, Any]:
        params = message.get("params") or {}
        name = params.get("name")
        if not isinstance(name, str) or not name:
            return _error(message.get("id"), INVALID_PARAMS, "params.name is required")
        if name not in {spec.name for spec in self.registry.list_tools()}:
            return _error(
                message.get("id"),
                INVALID_PARAMS,
                f"unknown tool: {name}",
            )
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _error(message.get("id"), INVALID_PARAMS, "params.arguments must be an object")
        validation_error = self._validate_arguments(name, arguments)
        if validation_error:
            return _error(message.get("id"), INVALID_PARAMS, validation_error)
        outcome: ToolResult = self.registry.call(name, arguments)
        return _result(
            message.get("id"),
            {
                "content": outcome.to_mcp_content(),
                "isError": outcome.is_error,
                "structuredContent": outcome.payload if outcome.ok else None,
            },
        )

    def _validate_arguments(self, tool: str, arguments: dict[str, Any]) -> str | None:
        """Schema validation of tool arguments (jsonschema, clear messages)."""
        import jsonschema

        schema = self.registry.spec(tool).input_schema
        try:
            jsonschema.validate(instance=arguments, schema=schema)
        except jsonschema.ValidationError as exc:
            return f"arguments failed schema for {tool}: {exc.message}"
        return None


def serve_stdio(registry: ToolRegistry | None = None) -> None:  # pragma: no cover
    """Run the server on stdio (one JSON-RPC message per line)."""
    server = McpServer(registry)
    for line in sys.stdin:
        response = server.handle_raw(line)
        if response is not None:
            sys.stdout.write(response + "\n")
            sys.stdout.flush()


if __name__ == "__main__":  # pragma: no cover
    serve_stdio()
