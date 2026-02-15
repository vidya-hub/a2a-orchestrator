"""Agent Registry - Centralized discovery and tracking of A2A agents."""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field

import httpx
from a2a.client import A2AClient
from a2a.types import (
    AgentCard,
    Message,
    MessageSendParams,
    SendMessageRequest,
    TextPart,
)

logger = logging.getLogger(__name__)


@dataclass
class RegisteredAgent:
    """An agent registered in the system."""

    name: str
    url: str
    card: AgentCard
    client: A2AClient
    skills: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.skills = [s.name for s in self.card.skills]


class AgentRegistry:
    """
    Centralized registry for A2A agent discovery and communication.

    This allows agents to discover and communicate with each other
    via the A2A protocol.
    """

    def __init__(self):
        self._agents: dict[str, RegisteredAgent] = {}
        self._http_client = httpx.AsyncClient(timeout=120.0)
        self._lock = asyncio.Lock()

    async def register(self, url: str) -> RegisteredAgent | None:
        """
        Discover and register an agent at the given URL.

        Args:
            url: Base URL of the agent (e.g., http://localhost:8001)

        Returns:
            RegisteredAgent if successful, None otherwise
        """
        try:
            # Fetch agent card
            card_url = f"{url.rstrip('/')}/.well-known/agent.json"
            response = await self._http_client.get(card_url)
            response.raise_for_status()
            card = AgentCard(**response.json())

            # Create A2A client
            client = A2AClient(
                httpx_client=self._http_client,
                agent_card=card,
                url=url.rstrip("/"),
            )

            # Register
            async with self._lock:
                agent = RegisteredAgent(
                    name=card.name,
                    url=url.rstrip("/"),
                    card=card,
                    client=client,
                )
                self._agents[card.name] = agent
                logger.info(f"Registered agent: {card.name} at {url}")
                logger.info(f"  Skills: {agent.skills}")
                return agent

        except Exception as e:
            logger.error(f"Failed to register agent at {url}: {e}")
            return None

    async def register_many(self, urls: list[str]) -> list[RegisteredAgent]:
        """Register multiple agents concurrently."""
        tasks = [self.register(url) for url in urls]
        results = await asyncio.gather(*tasks)
        return [r for r in results if r is not None]

    def get(self, name: str) -> RegisteredAgent | None:
        """Get a registered agent by name."""
        return self._agents.get(name)

    def list_agents(self) -> list[str]:
        """List all registered agent names."""
        return list(self._agents.keys())

    def get_agent_descriptions(self) -> dict[str, str]:
        """Get descriptions of all agents (for LLM routing)."""
        return {
            name: f"{agent.card.description} (Skills: {', '.join(agent.skills)})"
            for name, agent in self._agents.items()
        }

    async def send_task(self, agent_name: str, task: str) -> str:
        """
        Send a task to an agent via A2A protocol.

        This is the core A2A communication method.

        Args:
            agent_name: Name of the target agent
            task: Task description to send

        Returns:
            Response text from the agent
        """
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
                        role="user",
                        parts=[TextPart(text=task)],
                        messageId=str(uuid.uuid4()),
                    )
                ),
            )
            response = await agent.client.send_message(request)

            # Extract response text from A2A response structure
            try:
                result = response.root.result.status.message.parts[0].root.text
                logger.info(f"A2A ← {agent_name}: {result[:100]}...")
                return result
            except Exception:
                return str(response)

        except Exception as e:
            logger.error(f"A2A communication failed with {agent_name}: {e}")
            return f"Error communicating with {agent_name}: {e}"

    async def close(self):
        """Close the registry and all connections."""
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
