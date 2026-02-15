"""Writer Agent - File operations via official MCP filesystem server."""

from a2a.types import AgentSkill

from .base import BaseAgent

SYSTEM_PROMPT = """You are a Writer Agent that helps users with file operations.

You have access to file system tools to:
- Read files
- Write files
- List directories
- Create directories
- And more

IMPORTANT - Multi-step tasks:
If the user asks you to do something you cannot do (like searching the web),
use the delegate_to_agent tool to hand off that part to another agent.

For example, if asked "get the latest news and save it":
1. Use delegate_to_agent to ask the Research Agent to search
2. Then use your file tools to save the results

Always confirm what you've done after completing file operations."""


class WriterAgent(BaseAgent):
    """Writer agent with file system capabilities."""

    def __init__(self, mcp_command: str, allowed_dir: str | None = None):
        # The official MCP filesystem server needs an allowed directory
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
