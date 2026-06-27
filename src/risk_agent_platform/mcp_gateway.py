from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastmcp import Client, FastMCP

from risk_agent_platform.config import Settings
from risk_agent_platform.mcp_servers.factory import create_mcp_server
from risk_agent_platform.tracing import TraceRecorder


class MCPGateway:
    """MCP client adapter used by agents.

    In Docker, tools are reached through MCP HTTP URLs. In local embedded runs,
    this still uses FastMCP Client against real FastMCP server objects rather
    than importing tool classes directly.
    """

    def __init__(self, settings: Settings, *, embedded: bool = False, trace_id: str | None = None) -> None:
        self.settings = settings
        self.embedded = embedded
        self.tracer = TraceRecorder(settings, trace_id)
        self._servers: dict[str, FastMCP] = {}

    def call(self, server_name: str, tool_name: str, arguments: dict[str, Any] | None = None) -> Any:
        return _run_async(self.acall(server_name, tool_name, arguments or {}))

    async def acall(self, server_name: str, tool_name: str, arguments: dict[str, Any] | None = None) -> Any:
        transport = self._transport(server_name)
        with self.tracer.span(
            "mcp_tool_call",
            {"tool_name": tool_name, "server_name": server_name, "input_summary": _summarize(arguments or {})},
        ):
            async with Client(transport) as client:
                result = await client.call_tool(tool_name, arguments or {})
                if result.is_error:
                    raise RuntimeError(f"MCP tool error {server_name}.{tool_name}: {result.content}")
                self.tracer.event(
                    "mcp_tool_result",
                    {"tool_name": tool_name, "server_name": server_name, "output_summary": _summarize(result.data)},
                )
                return result.data

    def _transport(self, server_name: str) -> str | FastMCP:
        if self.embedded:
            if server_name not in self._servers:
                self._servers[server_name] = create_mcp_server(server_name, self.settings)
            return self._servers[server_name]
        try:
            return self.settings.mcp_urls[server_name]
        except KeyError as exc:
            raise ValueError(f"Unknown MCP URL for server: {server_name}") from exc


def _run_async(awaitable: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    raise RuntimeError("MCPGateway.call cannot be used from an active event loop; use acall instead")


def _summarize(value: Any) -> str:
    text = str(value)
    return text[:500]
