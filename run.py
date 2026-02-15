#!/usr/bin/env python3
"""
A2A Demo - Agent to Agent Communication

This demo shows true A2A (Agent-to-Agent) communication where:
- Research Agent can delegate file operations to Writer Agent
- Writer Agent can delegate research to Research Agent
- Both use the A2A protocol for inter-agent communication

Usage:
    python run.py

The agents will:
1. Start on ports 8001 (Research) and 8002 (Writer)
2. Discover each other via A2A protocol
3. Accept tasks and delegate when needed
"""

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from a2a_demo import (
    ResearchAgent,
    WriterAgent,
    create_agent_app,
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
    """Manages an agent's A2A server."""

    def __init__(self, agent, host: str, port: int):
        self.agent = agent
        self.host = host
        self.port = port
        self._server = None
        self._started = asyncio.Event()

    async def setup(self, peer_urls: list[str] | None = None):
        """Initialize agent with MCP and optionally discover peers."""
        await self.agent.setup(peer_urls=peer_urls)

    async def start(self):
        """Start the A2A server."""
        app = create_agent_app(self.agent, self.host, self.port)

        config = uvicorn.Config(
            app=app.build(),
            host=self.host,
            port=self.port,
            log_level="warning",
        )
        self._server = uvicorn.Server(config)

        logger.info(f"Starting {self.agent.name} on http://{self.host}:{self.port}")

        # Signal that server is starting
        asyncio.get_event_loop().call_later(0.5, self._started.set)
        await self._server.serve()

    async def wait_started(self):
        """Wait for server to be ready."""
        await self._started.wait()

    async def stop(self):
        if self._server:
            self._server.should_exit = True


async def run_demo(args):
    """Run the A2A demo with both agents."""
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    research_url = f"http://{args.host}:{args.research_port}"
    writer_url = f"http://{args.host}:{args.writer_port}"

    research_agent = ResearchAgent(mcp_command=args.research_mcp)
    writer_agent = WriterAgent(
        mcp_command=args.writer_mcp,
        allowed_dir=str(output_dir),
    )

    research_server = AgentServer(research_agent, args.host, args.research_port)
    writer_server = AgentServer(writer_agent, args.host, args.writer_port)

    # Phase 1: Setup agents (MCP only, no peer discovery yet)
    logger.info("Phase 1: Setting up agents with MCP connections...")
    await research_server.setup(peer_urls=None)
    await writer_server.setup(peer_urls=None)

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
    print(f"\nResearch Agent: {research_url}")
    print(f"Writer Agent:   {writer_url}")
    print(f"Output Dir:     {output_dir}")
    print("\nStarting servers...")

    async def discover_peers_after_startup():
        """Wait for servers then discover peers via A2A."""
        await asyncio.gather(
            research_server.wait_started(),
            writer_server.wait_started(),
        )
        await asyncio.sleep(1)  # Extra buffer for HTTP readiness

        logger.info("Phase 2: Discovering peer agents via A2A...")
        registry = get_registry()
        await registry.register(writer_url)
        await registry.register(research_url)
        print("Agents discovered each other via A2A protocol.")
        print("Press Ctrl+C to stop.\n")

    try:
        await asyncio.gather(
            research_server.start(),
            writer_server.start(),
            discover_peers_after_startup(),
            shutdown_event.wait(),
            return_exceptions=True,
        )
    finally:
        await research_server.stop()
        await writer_server.stop()
        await shutdown_mcp_manager()
        await shutdown_registry()
        logger.info("Cleanup complete")


async def send_task(args):
    """Send a task to an agent."""
    registry = get_registry()

    url = f"http://{args.host}:{args.port}"
    await registry.register(url)

    print(f"\nSending to agent at {url}:")
    print(f"  Task: {args.task}\n")

    response = await registry.send_task(args.agent or "Research Agent", args.task)
    print(f"Response:\n{response}\n")

    await shutdown_registry()


def main():
    parser = argparse.ArgumentParser(description="A2A Demo")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Run command (default)
    run_parser = subparsers.add_parser("run", help="Run both agents")
    run_parser.add_argument("--host", default="localhost")
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

    # Send command
    send_parser = subparsers.add_parser("send", help="Send a task to an agent")
    send_parser.add_argument("task", help="Task to send")
    send_parser.add_argument("--host", default="localhost")
    send_parser.add_argument("--port", type=int, default=8001)
    send_parser.add_argument("--agent", help="Agent name")

    args = parser.parse_args()

    if args.command == "send":
        asyncio.run(send_task(args))
    else:
        # Default to run
        if not args.command:
            args = parser.parse_args(["run"])
        asyncio.run(run_demo(args))


if __name__ == "__main__":
    main()
