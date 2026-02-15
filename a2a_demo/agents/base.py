"""Base Agent - Foundation for specialized A2A agents with MCP tools."""

import logging
from abc import ABC
from collections.abc import AsyncGenerator

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2AStarletteApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentSkill, Part, TextPart
from a2a.utils import new_task
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import StructuredTool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

from ..mcp.manager import MCPConnection, MCPManager, get_mcp_manager

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
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

        self._mcp_connection: MCPConnection | None = None
        self._mcp_manager: MCPManager | None = None
        self._tools: list[StructuredTool] | None = None

    def get_agent_card(self, host: str = "localhost", port: int = 8000) -> AgentCard:
        return AgentCard(
            name=self.name,
            description=self.description,
            url=f"http://{host}:{port}",
            version="1.0.0",
            capabilities=AgentCapabilities(streaming=True, push_notifications=False),
            skills=self.skills,
            default_input_modes=["text"],
            default_output_modes=["text"],
        )

    async def setup(self):
        self._mcp_manager = get_mcp_manager()

        self._mcp_connection = await self._mcp_manager.get_connection(
            self.mcp_command, self.mcp_env
        )

        mcp_tool_infos = await self._mcp_connection.list_tools()
        self._tools = self._mcp_manager.create_langchain_tools(
            self._mcp_connection, mcp_tool_infos
        )

        logger.info(
            f"Agent '{self.name}' initialized with {len(self._tools)} MCP tools"
        )

    async def process(self, query: str, context_id: str) -> AsyncGenerator[str, None]:
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
    def __init__(self, agent: BaseAgent):
        self.agent = agent

    async def execute(self, context: RequestContext, event_queue: EventQueue):
        query = context.get_user_input()
        if not query:
            raise ValueError("No user input found")

        task = context.current_task
        if not task and context.message:
            task = new_task(context.message)
        if not task:
            raise ValueError("Could not create task")

        updater = TaskUpdater(event_queue, task.id, task.context_id)

        await updater.start_work()
        logger.info(f"[{self.agent.name}] Processing: {query[:100]}...")

        try:
            final_response = ""
            async for response in self.agent.process(query, task.context_id):
                final_response = response

            parts = [Part(root=TextPart(text=final_response))]
            message = updater.new_agent_message(parts)
            await updater.complete(message=message)
            logger.info(f"[{self.agent.name}] Completed task {task.id}")

        except Exception as e:
            logger.error(f"[{self.agent.name}] Task {task.id} failed: {e}")
            error_parts = [Part(root=TextPart(text=f"Error: {e}"))]
            error_msg = updater.new_agent_message(error_parts)
            await updater.failed(message=error_msg)
            raise

    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        if context.current_task:
            updater = TaskUpdater(
                event_queue, context.current_task.id, context.current_task.context_id
            )
            await updater.cancel()


def create_agent_app(agent: BaseAgent, host: str, port: int) -> A2AStarletteApplication:
    from a2a.server.tasks import InMemoryTaskStore

    agent_card = agent.get_agent_card(host, port)
    executor = BaseAgentExecutor(agent)
    task_store = InMemoryTaskStore()
    handler = DefaultRequestHandler(agent_executor=executor, task_store=task_store)

    return A2AStarletteApplication(agent_card=agent_card, http_handler=handler)
