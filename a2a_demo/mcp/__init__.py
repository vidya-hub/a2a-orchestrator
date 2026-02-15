"""A2A Demo - MCP connection management."""

from .manager import (
    MCPConnection,
    MCPManager,
    get_mcp_manager,
    shutdown_mcp_manager,
)

__all__ = [
    "MCPConnection",
    "MCPManager",
    "get_mcp_manager",
    "shutdown_mcp_manager",
]
