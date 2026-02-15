#!/usr/bin/env python3
"""Start the Research Agent server."""

import argparse
import asyncio
import logging
import signal

import uvicorn
from dotenv import load_dotenv

from ..agents import ResearchAgent, create_agent_app
from ..mcp import shutdown_mcp_manager

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    parser = argparse.ArgumentParser(description="Research Agent Server")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--mcp-command", default="uvx ddgs-mcp")
    args = parser.parse_args()

    agent = ResearchAgent(mcp_command=args.mcp_command)
    await agent.setup()

    app = create_agent_app(agent, args.host, args.port)

    shutdown_event = asyncio.Event()

    def signal_handler():
        logger.info("Shutting down...")
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    print(f"\nResearch Agent running at http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop.\n")

    config = uvicorn.Config(
        app=app.build(),
        host=args.host,
        port=args.port,
        log_level="warning",
    )
    server = uvicorn.Server(config)

    try:
        await asyncio.gather(
            server.serve(),
            shutdown_event.wait(),
            return_exceptions=True,
        )
    finally:
        server.should_exit = True
        await shutdown_mcp_manager()
        logger.info("Research Agent stopped")


def run():
    asyncio.run(main())


if __name__ == "__main__":
    run()
