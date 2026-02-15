"""Routing Agent - Orchestrates tasks across specialized remote agents."""

import logging
from collections.abc import AsyncGenerator

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

logger = logging.getLogger(__name__)


ROUTING_SYSTEM_PROMPT = """You are a task orchestrator that delegates work to specialized agents.

You have a send_message tool to communicate with remote agents. Use it to delegate tasks based on each agent's capabilities.

{agents_summary}

Workflow:
1. Analyze the user's request
2. Identify which agent(s) can handle it based on their skills
3. Use send_message to delegate tasks to the appropriate agent(s)
4. For multi-step tasks, coordinate between agents as needed
5. Compile and return the final result to the user"""


class RoutingAgent:
    def __init__(self, model_name: str = "gemini-2.0-flash"):
        self.name = "Routing Agent"
        self.description = "Orchestrates tasks across specialized agents"
        self.model_name = model_name
        self._registry: AgentRegistry | None = None
        self._initialized = False
        self._memory = MemorySaver()
        self._graph = None

    def get_agent_card(self, host: str = "localhost", port: int = 8000) -> AgentCard:
        return AgentCard(
            name=self.name,
            description=self.description,
            url=f"http://{host}:{port}",
            version="1.0.0",
            capabilities=AgentCapabilities(streaming=True, pushNotifications=False),
            skills=[
                AgentSkill(
                    id="orchestration",
                    name="Task Orchestration",
                    description="Routes tasks to appropriate specialized agents",
                    tags=["routing", "orchestration", "multi-agent"],
                )
            ],
            defaultInputModes=["text"],
            defaultOutputModes=["text"],
        )

    async def setup(self, agent_urls: list[str]):
        self._registry = get_registry()
        await self._registry.discover_many(agent_urls)
        self._initialized = True
        logger.info(
            f"RoutingAgent initialized with {len(self._registry.list_agents())} agents"
        )

    def _create_send_message_tool(self) -> StructuredTool:
        registry = self._registry

        class SendMessageInput(BaseModel):
            agent_name: str = Field(description="Name of the agent to send the task to")
            task: str = Field(description="The task or message to send to the agent")

        async def send_message(agent_name: str, task: str) -> str:
            if not registry:
                return "Error: Registry not initialized"
            return await registry.send_message(agent_name, task)

        return StructuredTool(
            name="send_message",
            description="Send a task to a specialized remote agent via A2A protocol",
            coroutine=send_message,
            args_schema=SendMessageInput,
        )

    async def process(self, query: str, context_id: str) -> AsyncGenerator[str, None]:
        if not self._initialized or not self._registry:
            raise RuntimeError("RoutingAgent not initialized. Call setup() first.")

        if self._graph is None:
            agents_summary = self._registry.get_agents_summary()
            system_prompt = ROUTING_SYSTEM_PROMPT.format(agents_summary=agents_summary)
            tools = [self._create_send_message_tool()]
            model = ChatGoogleGenerativeAI(model=self.model_name)
            self._graph = create_react_agent(
                model,
                tools=tools,
                checkpointer=self._memory,
                prompt=system_prompt,
            )

        config = {"configurable": {"thread_id": context_id}}

        async for event in self._graph.astream(
            {"messages": [HumanMessage(content=query)]}, config=config
        ):
            if "agent" in event:
                for msg in event["agent"].get("messages", []):
                    if isinstance(msg, AIMessage) and msg.content:
                        yield msg.content


class RoutingAgentExecutor(AgentExecutor):
    def __init__(self, agent: RoutingAgent):
        self.agent = agent

    async def execute(self, context: RequestContext, event_queue: EventQueue):
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
        if context.current_task:
            updater = TaskUpdater(
                event_queue, context.current_task.id, context.current_task.context_id
            )
            await updater.cancel()


def create_routing_agent_app(
    agent: RoutingAgent, host: str, port: int
) -> A2AStarletteApplication:
    from a2a.server.tasks import InMemoryTaskStore

    agent_card = agent.get_agent_card(host, port)
    executor = RoutingAgentExecutor(agent)
    task_store = InMemoryTaskStore()
    handler = DefaultRequestHandler(agent_executor=executor, task_store=task_store)

    return A2AStarletteApplication(agent_card=agent_card, http_handler=handler)
