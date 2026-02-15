"""Writer Agent - File operations via official MCP filesystem server."""

from a2a.types import AgentSkill

from .base import BaseAgent

SYSTEM_PROMPT = """You are a Writer Agent specialized in file system operations.

You have access to tools to:
- Read files and directories
- Write and create files
- List directory contents
- Manage files and folders

Always confirm what operations you've completed."""


class WriterAgent(BaseAgent):
    def __init__(self, mcp_command: str, allowed_dir: str | None = None):
        if allowed_dir and allowed_dir not in mcp_command:
            mcp_command = f"{mcp_command} {allowed_dir}"

        super().__init__(
            name="Writer Agent",
            description="Reads and writes files to the filesystem",
            skills=[
                AgentSkill(
                    id="file-ops",
                    name="File Operations",
                    description="Read, write, and manage files and directories",
                    tags=["files", "write", "filesystem"],
                )
            ],
            mcp_command=mcp_command,
            system_prompt=SYSTEM_PROMPT,
        )
