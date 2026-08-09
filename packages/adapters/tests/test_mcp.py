"""Tests for MCP adapter."""

from autonoesis_adapters.mcp import MCPServerAdapter, MCPToolDefinition


class TestMCPServerAdapter:
    def test_register_and_list(self) -> None:
        adapter = MCPServerAdapter()
        adapter.register(MCPToolDefinition(name="test-tool", description="A test tool"))

        tools = adapter.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "test-tool"

    def test_get_tool(self) -> None:
        adapter = MCPServerAdapter()
        adapter.register(MCPToolDefinition(name="tool-1"))

        assert adapter.get_tool("tool-1") is not None
        assert adapter.get_tool("nonexistent") is None

    def test_empty_server(self) -> None:
        adapter = MCPServerAdapter()
        assert len(adapter.list_tools()) == 0

    def test_default_input_schema(self) -> None:
        tool = MCPToolDefinition(name="minimal")
        assert tool.input_schema == {"type": "object", "properties": {}}
