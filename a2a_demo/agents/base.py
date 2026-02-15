"""Base Agent - Foundation for A2A agents with MCP tools and peer delegation."""

import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2AStarletteApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentSkill, TextPart
from a2a.utils import new_task
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import StructuredTool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel, Field

from ..core.registry import AgentRegistry, get_registry
from ..mcp.manager import MCPConnection, MCPManager, get_mcp_manager

logger = logging.getLogger(__name__)


class DelegateTaskInput(BaseModel):
    """Input schema for delegating tasks to peer agents."""

    agent_name: str = Field(description="Name of the agent to delegate to")
    task: str = Field(description="The task description to send to the agent")


class BaseAgent(ABC):
    """
    Base class for A2A agents with:
    - Persistent MCP connection
    - Peer agent delegation via A2A
    - LangGraph ReAct execution
    """

    def __init__(
        self,
        name: str,
        description: str,
        skills: list[AgentSkill],
        mcp_command: str,
        system_prompt: str,
        model_name: str = "gemini-2.0-flash",
        mcp_env: dict[str, str] | None = None,
    ):
        self.name = name
        self.description = description
        self.skills = skills
        self.mcp_command = mcp_command
        self.system_prompt = system_prompt
        self.model_name = model_name
        self.mcp_env = mcp_env

        # These are initialized in setup()
        self._mcp_connection: MCPConnection | None = None
        self._mcp_manager: MCPManager | None = None
        self._registry: AgentRegistry | None = None
        self._tools: list[StructuredTool] | None = None

    def get_agent_card(self, host: str = "localhost", port: int = 8000) -> AgentCard:
        """Generate the A2A agent card for discovery."""
        return AgentCard(
            name=self.name,
            description=self.description,
            url=f"http://{host}:{port}",
            version="1.0.0",
            capabilities=AgentCapabilities(streaming=True, pushNotifications=False),
            skills=self.skills,
            defaultInputModes=["text"],
            defaultOutputModes=["text"],
        )

    async def setup(self, peer_urls: list[str] | None = None):
        """
        Initialize the agent:
        - Connect to MCP server
        - Discover peer agents
        - Build tool list
        """
        # Get managers
        self._mcp_manager = get_mcp_manager()
        self._registry = get_registry()

        # Connect to MCP server (persistent connection)
        self._mcp_connection = await self._mcp_manager.get_connection(
            self.mcp_command, self.mcp_env
        )

        # Get MCP tools
        mcp_tool_infos = await self._mcp_connection.list_tools()
        mcp_tools = self._mcp_manager.create_langchain_tools(
            self._mcp_connection, mcp_tool_infos
        )

        # Discover peer agents if URLs provided
        if peer_urls:
            await self._registry.register_many(peer_urls)

        # Build final tool list: MCP tools + delegation tool
        self._tools = mcp_tools + self._create_delegation_tools()

        logger.info(
            f"Agent '{self.name}' initialized with {len(self._tools)} tools "
            f"({len(mcp_tools)} MCP + delegation)"
        )

    def _create_delegation_tools(self) -> list[StructuredTool]:
        """Create tools for delegating tasks to peer agents."""
        registry = self._registry

        async def delegate_to_agent(agent_name: str, task: str) -> str:
            """
            Delegate a task to another agent via A2A protocol.

            Use this when you need capabilities you don't have.
            For example, if you're the Research Agent and need to
            save results to a file, delegate to the Writer Agent.
            """
            if not registry:
                return "Error: Agent registry not initialized"

            available = registry.list_agents()
            if not available:
                return "Error: No peer agents available for delegation"

            if agent_name not in available:
                return f"Error: Unknown agent '{agent_name}'. Available: {available}"

            logger.info(f"Delegating to {agent_name}: {task[:100]}...")
            result = await registry.send_task(agent_name, task)
            return result

        async def list_available_agents() -> str:
            """List all available agents and their capabilities."""
            if not registry:
                return "Error: Agent registry not initialized"

            descriptions = registry.get_agent_descriptions()
            if not descriptions:
                return "No peer agents available"

            lines = ["Available agents:"]
            for name, desc in descriptions.items():
                lines.append(f"- {name}: {desc}")
            return "\n".join(lines)

        return [
            StructuredTool(
                name="delegate_to_agent",
                description=(
                    "Delegate a task to another agent via A2A protocol. "
                    "Use when you need capabilities you don't have. "
                    "First call list_available_agents to see what's available."
                ),
                coroutine=delegate_to_agent,
                args_schema=DelegateTaskInput,
            ),
            StructuredTool.from_function(
                coroutine=list_available_agents,
                name="list_available_agents",
                description="List all available peer agents and their capabilities.",
            ),
        ]

    async def process(self, query: str, context_id: str) -> AsyncGenerator[str, None]:
        """
        Process a query using LangGraph ReAct agent.

        Yields intermediate and final responses.
        """
        if not self._tools:
            raise RuntimeError("Agent not initialized. Call setup() first.")

        model = ChatGoogleGenerativeAI(model=self.model_name)
        graph = create_react_agent(
            model,
            tools=self._tools,
            checkpointer=MemorySaver(),
            prompt=self.system_prompt,
        )

        config = {"configurable": {"thread_id": context_id}}

        async for event in graph.astream(
            {"messages": [HumanMessage(content=query)]}, config=config
        ):
            if "agent" in event:
                for msg in event["agent"].get("messages", []):
                    if isinstance(msg, AIMessage) and msg.content:
                        yield msg.content


class BaseAgentExecutor(AgentExecutor):
    """Bridges BaseAgent to A2A protocol."""

    def __init__(self, agent: BaseAgent):
        self.agent = agent

    async def execute(self, context: RequestContext, event_queue: EventQueue):
        """Execute agent and stream A2A events."""
        query = context.get_user_input()
        if not query:
            raise ValueError("No user input found")

        task = context.current_task or new_task(context.message)
        updater = TaskUpdater(event_queue, task.id, task.context_id)

        await updater.start_work()
        logger.info(f"[{self.agent.name}] Processing: {query[:100]}...")

        try:
            final_response = ""
            async for response in self.agent.process(query, task.context_id):
                final_response = response

            message = updater.new_agent_message([TextPart(text=final_response)])
            await updater.complete(message=message)
            logger.info(f"[{self.agent.name}] Completed task {task.id}")

        except Exception as e:
            logger.error(f"[{self.agent.name}] Task {task.id} failed: {e}")
            error_msg = updater.new_agent_message([TextPart(text=f"Error: {e}")])
            await updater.failed(message=error_msg)
            raise

    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        """Cancel a running task."""
        if context.current_task:
            updater = TaskUpdater(
                event_queue, context.current_task.id, context.current_task.context_id
            )
            await updater.cancel()


def create_agent_app(agent: BaseAgent, host: str, port: int) -> A2AStarletteApplication:
    """Create an A2A Starlette application for the agent."""
    from a2a.server.tasks import InMemoryTaskStore

    agent_card = agent.get_agent_card(host, port)
    executor = BaseAgentExecutor(agent)
    task_store = InMemoryTaskStore()
    handler = DefaultRequestHandler(agent_executor=executor, task_store=task_store)

    return A2AStarletteApplication(agent_card=agent_card, http_handler=handler)
