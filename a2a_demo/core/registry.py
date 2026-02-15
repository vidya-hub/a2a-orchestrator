"""Agent Registry - A2A agent discovery and communication."""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field

import httpx
from a2a.client import A2ACardResolver, A2AClient
from a2a.types import (
    AgentCard,
    Message,
    MessageSendParams,
    Part,
    Role,
    SendMessageRequest,
    TextPart,
)

logger = logging.getLogger(__name__)


@dataclass
class RemoteAgentConnection:
    name: str
    url: str
    card: AgentCard
    client: A2AClient
    skills: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.skills = [s.name for s in self.card.skills]

    @property
    def description(self) -> str:
        skills_str = ", ".join(self.skills) if self.skills else "general"
        return f"{self.card.description} (Skills: {skills_str})"


class AgentRegistry:
    def __init__(self):
        self._agents: dict[str, RemoteAgentConnection] = {}
        self._http_client = httpx.AsyncClient(timeout=120.0)
        self._lock = asyncio.Lock()

    async def discover_agent(self, url: str) -> RemoteAgentConnection | None:
        url = url.rstrip("/")

        try:
            resolver = A2ACardResolver(
                httpx_client=self._http_client,
                base_url=url,
            )
            card = await resolver.get_agent_card()

            client = A2AClient(
                httpx_client=self._http_client,
                agent_card=card,
                url=url,
            )

            async with self._lock:
                connection = RemoteAgentConnection(
                    name=card.name,
                    url=url,
                    card=card,
                    client=client,
                )
                self._agents[card.name] = connection
                logger.info(f"Discovered agent: {card.name} at {url}")
                logger.info(f"  Skills: {connection.skills}")
                return connection

        except Exception as e:
            logger.error(f"Failed to discover agent at {url}: {e}")
            return None

    async def discover_many(self, urls: list[str]) -> list[RemoteAgentConnection]:
        tasks = [self.discover_agent(url) for url in urls]
        results = await asyncio.gather(*tasks)
        return [r for r in results if r is not None]

    register = discover_agent
    register_many = discover_many

    def get(self, name: str) -> RemoteAgentConnection | None:
        return self._agents.get(name)

    def list_agents(self) -> list[str]:
        return list(self._agents.keys())

    def get_agent_descriptions(self) -> dict[str, str]:
        return {name: agent.description for name, agent in self._agents.items()}

    def get_agents_summary(self) -> str:
        if not self._agents:
            return "No remote agents available."

        lines = ["Available agents:"]
        for name, agent in self._agents.items():
            lines.append(f"  - {name}: {agent.description}")
        return "\n".join(lines)

    async def send_message(self, agent_name: str, task: str) -> str:
        return await self.send_message_with_session(agent_name, task, None)

    async def send_message_with_session(
        self, agent_name: str, task: str, session_id: str | None = None
    ) -> str:
        agent = self._agents.get(agent_name)
        if not agent:
            available = self.list_agents()
            return f"Error: Unknown agent '{agent_name}'. Available: {available}"

        logger.info(f"A2A → {agent_name}: {task[:100]}...")

        try:
            request = SendMessageRequest(
                id=str(uuid.uuid4()),
                params=MessageSendParams(
                    message=Message(
                        role=Role.user,
                        parts=[Part(root=TextPart(text=task))],
                        message_id=str(uuid.uuid4()),
                        context_id=session_id,
                    )
                ),
            )
            response = await agent.client.send_message(request)

            try:
                if hasattr(response.root, "result"):
                    task_result = response.root.result
                    if hasattr(task_result, "status") and task_result.status:
                        msg = task_result.status.message
                        if msg and msg.parts:
                            part = msg.parts[0]
                            if hasattr(part, "root") and hasattr(part.root, "text"):
                                result = part.root.text
                                logger.info(f"A2A ← {agent_name}: {result[:100]}...")
                                return result
                return str(response)
            except Exception:
                return str(response)

        except Exception as e:
            logger.error(f"A2A communication failed with {agent_name}: {e}")
            return f"Error communicating with {agent_name}: {e}"

    send_task = send_message

    async def close(self):
        await self._http_client.aclose()
        self._agents.clear()
        logger.info("Agent registry closed")


# Global registry instance
_registry: AgentRegistry | None = None


def get_registry() -> AgentRegistry:
    """Get the global agent registry."""
    global _registry
    if _registry is None:
        _registry = AgentRegistry()
    return _registry


async def shutdown_registry():
    """Shutdown the global registry."""
    global _registry
    if _registry:
        await _registry.close()
        _registry = None
