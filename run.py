#!/usr/bin/env python3
"""
A2A Demo - Agent to Agent Communication

Architecture (following official Google A2A patterns):
- RoutingAgent: Orchestrator that routes tasks to specialized agents
- Research Agent: Web search capabilities via DuckDuckGo MCP
- Writer Agent: File operations via official MCP filesystem server

Usage:
    python run.py              # Start all agents
    python run.py send "task"  # Send task to routing agent
"""

import argparse
import asyncio
import logging
import signal
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from a2a_demo import (
    ResearchAgent,
    RoutingAgent,
    WriterAgent,
    create_agent_app,
    create_routing_agent_app,
    get_registry,
    shutdown_mcp_manager,
    shutdown_registry,
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class AgentServer:
    def __init__(self, agent, host: str, port: int, is_routing: bool = False):
        self.agent = agent
        self.host = host
        self.port = port
        self.is_routing = is_routing
        self._server = None
        self._started = asyncio.Event()

    async def setup(self, agent_urls: list[str] | None = None):
        if self.is_routing and agent_urls:
            await self.agent.setup(agent_urls)
        else:
            await self.agent.setup()

    async def start(self):
        if self.is_routing:
            app = create_routing_agent_app(self.agent, self.host, self.port)
        else:
            app = create_agent_app(self.agent, self.host, self.port)

        config = uvicorn.Config(
            app=app.build(),
            host=self.host,
            port=self.port,
            log_level="warning",
        )
        self._server = uvicorn.Server(config)

        logger.info(f"Starting {self.agent.name} on http://{self.host}:{self.port}")

        asyncio.get_event_loop().call_later(0.5, self._started.set)
        await self._server.serve()

    async def wait_started(self):
        await self._started.wait()

    async def stop(self):
        if self._server:
            self._server.should_exit = True


async def run_demo(args):
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    research_url = f"http://{args.host}:{args.research_port}"
    writer_url = f"http://{args.host}:{args.writer_port}"
    routing_url = f"http://{args.host}:{args.routing_port}"

    research_agent = ResearchAgent(mcp_command=args.research_mcp)
    writer_agent = WriterAgent(
        mcp_command=args.writer_mcp,
        allowed_dir=str(output_dir),
    )
    routing_agent = RoutingAgent()

    research_server = AgentServer(research_agent, args.host, args.research_port)
    writer_server = AgentServer(writer_agent, args.host, args.writer_port)
    routing_server = AgentServer(
        routing_agent, args.host, args.routing_port, is_routing=True
    )

    logger.info("Phase 1: Setting up specialized agents...")
    await research_server.setup()
    await writer_server.setup()

    shutdown_event = asyncio.Event()

    def signal_handler():
        logger.info("Shutting down...")
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    print("\n" + "=" * 60)
    print("A2A Demo - Agent to Agent Communication")
    print("=" * 60)
    print(f"\nRouting Agent:  {routing_url} (orchestrator)")
    print(f"Research Agent: {research_url}")
    print(f"Writer Agent:   {writer_url}")
    print(f"Output Dir:     {output_dir}")
    print("\nStarting servers...")

    async def setup_routing_after_startup():
        await asyncio.gather(
            research_server.wait_started(),
            writer_server.wait_started(),
        )
        await asyncio.sleep(1)

        logger.info("Phase 2: Setting up routing agent with discovered agents...")
        await routing_server.setup([research_url, writer_url])
        print("\nRouting Agent discovered specialized agents via A2A protocol.")
        print(f"Send tasks to: {routing_url}")
        print("Press Ctrl+C to stop.\n")

    try:
        await asyncio.gather(
            research_server.start(),
            writer_server.start(),
            routing_server.start(),
            setup_routing_after_startup(),
            shutdown_event.wait(),
            return_exceptions=True,
        )
    finally:
        await routing_server.stop()
        await research_server.stop()
        await writer_server.stop()
        await shutdown_mcp_manager()
        await shutdown_registry()
        logger.info("Cleanup complete")


async def send_task(args):
    registry = get_registry()

    url = f"http://{args.host}:{args.port}"
    await registry.discover_agent(url)

    print(f"\nSending to agent at {url}:")
    print(f"  Task: {args.task}\n")

    agent_name = args.agent or "Routing Agent"
    response = await registry.send_message(agent_name, args.task)
    print(f"Response:\n{response}\n")

    await shutdown_registry()


def main():
    parser = argparse.ArgumentParser(description="A2A Demo")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    run_parser = subparsers.add_parser("run", help="Run all agents")
    run_parser.add_argument("--host", default="localhost")
    run_parser.add_argument("--routing-port", type=int, default=8000)
    run_parser.add_argument("--research-port", type=int, default=8001)
    run_parser.add_argument("--writer-port", type=int, default=8002)
    run_parser.add_argument("--research-mcp", default="uvx ddgs-mcp")
    run_parser.add_argument(
        "--writer-mcp",
        default="npx -y @modelcontextprotocol/server-filesystem",
    )
    run_parser.add_argument(
        "--output-dir",
        default="./output",
        help="Directory for file operations",
    )

    send_parser = subparsers.add_parser("send", help="Send a task to an agent")
    send_parser.add_argument("task", help="Task to send")
    send_parser.add_argument("--host", default="localhost")
    send_parser.add_argument("--port", type=int, default=8000)
    send_parser.add_argument("--agent", help="Agent name (default: Routing Agent)")

    args = parser.parse_args()

    if args.command == "send":
        asyncio.run(send_task(args))
    else:
        if not args.command:
            args = parser.parse_args(["run"])
        asyncio.run(run_demo(args))


if __name__ == "__main__":
    main()
