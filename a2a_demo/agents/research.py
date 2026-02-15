"""Research Agent - Web search via DuckDuckGo MCP."""

from a2a.types import AgentSkill

from .base import BaseAgent

SYSTEM_PROMPT = """You are a Research Agent specialized in finding information online.

You have access to web search tools via DuckDuckGo. Use them to:
- Search for current information, news, and facts
- Find answers to questions
- Research topics thoroughly

Always provide comprehensive and accurate search results."""


class ResearchAgent(BaseAgent):
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
