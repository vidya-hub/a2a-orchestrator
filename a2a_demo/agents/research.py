"""Research Agent - Web search via DuckDuckGo MCP."""

from a2a.types import AgentSkill

from .base import BaseAgent

SYSTEM_PROMPT = """You are a Research Agent that helps users find information online.

You have access to web search tools via DuckDuckGo.

IMPORTANT - Multi-step tasks:
If the user asks you to do something you cannot do (like saving files),
use the delegate_to_agent tool to hand off that part to another agent.

For example, if asked "search for X and save to a file":
1. First, use your search tools to find the information
2. Then, use delegate_to_agent to ask the Writer Agent to save it

Always be helpful and thorough in your research."""


class ResearchAgent(BaseAgent):
    """Research agent with web search capabilities."""

    def __init__(self, mcp_command: str = "uvx ddgs-mcp"):
        super().__init__(
            name="Research Agent",
            description="Searches the web for information using DuckDuckGo",
            skills=[
                AgentSkill(
                    id="web-search",
                    name="Web Search",
                    description="Search the internet for information, news, and answers",
                    tags=["search", "web", "research"],
                )
            ],
            mcp_command=mcp_command,
            system_prompt=SYSTEM_PROMPT,
        )
