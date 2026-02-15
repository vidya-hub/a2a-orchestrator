"""MCP Manager - Persistent connection pooling for MCP servers."""

import asyncio
import json
import logging
import shlex
from typing import Any

from langchain_core.tools import StructuredTool
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import Field, create_model

logger = logging.getLogger(__name__)


def _sanitize_schema(schema: dict) -> dict:
    """Recursively sanitize JSON schema for Gemini compatibility.

    Gemini requires ALL arrays to have an 'items' field, even nested ones.
    This function ensures all arrays have items defined.
    """
    if not isinstance(schema, dict):
        return schema

    result = {}
    for key, value in schema.items():
        if key == "properties" and isinstance(value, dict):
            # Recursively sanitize each property
            result[key] = {
                prop_name: _sanitize_schema(prop_value)
                for prop_name, prop_value in value.items()
            }
        elif key == "items" and isinstance(value, dict):
            # Recursively sanitize array items
            result[key] = _sanitize_schema(value)
        elif isinstance(value, dict):
            # Recursively sanitize nested objects
            result[key] = _sanitize_schema(value)
        else:
            result[key] = value

    # If this is an array type without items, add default items
    if result.get("type") == "array" and "items" not in result:
        result["items"] = {"type": "string"}
        logger.debug(f"Added default items to array schema")

    return result


def _json_type_to_python(prop: dict) -> type:
    """Convert JSON schema type to Python type annotation."""
    json_type = prop.get("type", "string")

    type_map = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "object": dict,
    }

    if json_type == "array":
        items = prop.get("items", {})
        item_type = _json_type_to_python(items) if items else Any
        return list[item_type]

    return type_map.get(json_type, Any)


class MCPConnection:
    """A persistent connection to an MCP server."""

    def __init__(self, command: str, env: dict[str, str] | None = None):
        parts = shlex.split(command)
        self.command = command
        self.server_params = StdioServerParameters(
            command=parts[0],
            args=parts[1:] if len(parts) > 1 else [],
            env=env,
        )
        self._session: ClientSession | None = None
        self._context_stack = None
        self._tools_cache: list[dict] | None = None

    async def connect(self):
        """Establish persistent connection to MCP server."""
        if self._session:
            return  # Already connected

        # Create the async context managers but keep them open
        self._stdio_context = stdio_client(self.server_params)
        self._read_stream, self._write_stream = await self._stdio_context.__aenter__()

        self._session_context = ClientSession(self._read_stream, self._write_stream)
        self._session = await self._session_context.__aenter__()

        await self._session.initialize()
        logger.info(f"MCP connection established: {self.command}")

    async def disconnect(self):
        """Close the MCP connection."""
        if self._session:
            try:
                await self._session_context.__aexit__(None, None, None)
                await self._stdio_context.__aexit__(None, None, None)
            except Exception as e:
                logger.warning(f"Error closing MCP connection: {e}")
            finally:
                self._session = None
                self._tools_cache = None
            logger.info(f"MCP connection closed: {self.command}")

    @property
    def is_connected(self) -> bool:
        return self._session is not None

    async def list_tools(self) -> list[dict[str, Any]]:
        """List available tools (cached after first call)."""
        if not self._session:
            raise RuntimeError("Not connected to MCP server")

        if self._tools_cache is None:
            result = await self._session.list_tools()
            self._tools_cache = [
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "input_schema": _sanitize_schema(tool.inputSchema),
                }
                for tool in result.tools
            ]
            logger.info(
                f"Discovered {len(self._tools_cache)} tools from {self.command}"
            )

        return self._tools_cache

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call an MCP tool."""
        if not self._session:
            raise RuntimeError("Not connected to MCP server")

        logger.debug(f"Calling MCP tool: {name}")
        result = await self._session.call_tool(name=name, arguments=arguments)

        if result.content:
            text = getattr(result.content[0], "text", None)
            if text:
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return text
        return str(result)


class MCPManager:
    """Manages persistent MCP connections with pooling."""

    def __init__(self):
        self._connections: dict[str, MCPConnection] = {}
        self._lock = asyncio.Lock()

    async def get_connection(
        self, command: str, env: dict[str, str] | None = None
    ) -> MCPConnection:
        """Get or create a persistent MCP connection."""
        async with self._lock:
            if command not in self._connections:
                conn = MCPConnection(command, env)
                await conn.connect()
                self._connections[command] = conn
            return self._connections[command]

    async def close_all(self):
        """Close all MCP connections."""
        async with self._lock:
            for conn in self._connections.values():
                await conn.disconnect()
            self._connections.clear()
            logger.info("All MCP connections closed")

    def create_langchain_tools(
        self, connection: MCPConnection, tool_infos: list[dict]
    ) -> list[StructuredTool]:
        """Convert MCP tools to LangChain StructuredTools."""
        tools = []
        for tool_info in tool_infos:
            name = tool_info["name"]
            description = tool_info["description"]
            schema = tool_info.get("input_schema", {})

            # Create async tool function that uses the persistent connection
            async def make_tool_func(tool_name: str, conn: MCPConnection):
                async def tool_func(**kwargs) -> str:
                    result = await conn.call_tool(tool_name, kwargs)
                    return (
                        json.dumps(result, indent=2)
                        if isinstance(result, dict)
                        else str(result)
                    )

                return tool_func

            # Build pydantic schema for the tool
            args_schema = self._build_args_schema(name, schema)

            # We need to capture the current values in the closure
            tool = StructuredTool(
                name=name,
                description=description,
                coroutine=self._make_tool_coroutine(name, connection),
                args_schema=args_schema,
            )
            tools.append(tool)

        return tools

    def _make_tool_coroutine(self, tool_name: str, connection: MCPConnection):
        """Create a coroutine for calling an MCP tool."""

        async def tool_func(**kwargs) -> str:
            result = await connection.call_tool(tool_name, kwargs)
            return (
                json.dumps(result, indent=2)
                if isinstance(result, dict)
                else str(result)
            )

        return tool_func

    def _build_args_schema(self, tool_name: str, schema: dict):
        """Build a Pydantic model from JSON schema.

        IMPORTANT: Always returns a model, even for empty schemas.
        This prevents LangChain from inferring schemas that include
        RunnableConfig with arrays that break Gemini's validation.
        """
        properties = schema.get("properties", {})

        # Always create a model - even empty ones prevent LangChain from
        # injecting RunnableConfig which has arrays without 'items'
        if not properties:
            return create_model(f"{tool_name}Input")

        required = set(schema.get("required", []))
        fields = {}

        for name, prop in properties.items():
            python_type = _json_type_to_python(prop)
            default = prop.get("default", ...)

            if name not in required:
                from typing import Optional

                python_type = Optional[python_type]
                default = default if default != ... else None

            fields[name] = (
                python_type,
                Field(default=default, description=prop.get("description", "")),
            )

        return create_model(f"{tool_name}Input", **fields)


# Global MCP manager instance
_mcp_manager: MCPManager | None = None


def get_mcp_manager() -> MCPManager:
    """Get the global MCP manager instance."""
    global _mcp_manager
    if _mcp_manager is None:
        _mcp_manager = MCPManager()
    return _mcp_manager


async def shutdown_mcp_manager():
    """Shutdown the global MCP manager."""
    global _mcp_manager
    if _mcp_manager:
        await _mcp_manager.close_all()
        _mcp_manager = None
