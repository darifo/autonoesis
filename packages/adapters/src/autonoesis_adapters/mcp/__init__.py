"""MCP (Model Context Protocol) Tool Server adapter base.

Provides the protocol bridge between Autonoesis Tool Definitions and
MCP-compatible tool servers.  Remote tool execution is isolated by the
ToolDefinition's resource_scope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class MCPToolDefinition:
    """An MCP tool as registered on the server side."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )


@dataclass(frozen=True, slots=True)
class MCPToolResult:
    """Result returned by an MCP tool invocation."""

    content: list[dict[str, Any]]
    is_error: bool = False


class MCPServerAdapter:
    """Registers Autonoesis Tools as MCP tools for consumption by MCP clients.

    In a full implementation this would:
    1. Accept tool registration requests from Autonoesis
    2. Expose them via the MCP JSON-RPC protocol
    3. Route invocations to the GovernedToolGateway
    4. Enforce resource isolation per ToolDefinition.resource_scope
    """

    def __init__(self) -> None:
        self._tools: dict[str, MCPToolDefinition] = {}

    def register(self, definition: MCPToolDefinition) -> None:
        """Register an MCP tool definition."""
        self._tools[definition.name] = definition

    def list_tools(self) -> tuple[MCPToolDefinition, ...]:
        """Return all registered MCP tools."""
        return tuple(self._tools.values())

    def get_tool(self, name: str) -> MCPToolDefinition | None:
        """Look up a tool by name."""
        return self._tools.get(name)


class MCPClientAdapter:
    """Calls remote MCP tools and normalizes results to Autonoesis ToolReceipts.

    In a full implementation this would:
    1. Connect to an MCP server via JSON-RPC
    2. Call tools/list and tools/call
    3. Convert results to the Autonoesis ToolReceipt format
    4. Apply resource isolation and credential brokering
    """

    async def call_tool(
        self,
        server_url: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> MCPToolResult:
        """Invoke *tool_name* on *server_url* with *arguments*."""
        _ = server_url
        return MCPToolResult(
            content=[{"type": "text", "text": f"MCP tool '{tool_name}' not yet connected"}],
            is_error=True,
        )
