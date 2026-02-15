#!/usr/bin/env python3
"""Start the Routing Agent server."""

import argparse
import asyncio
import logging
import signal

import uvicorn
from dotenv import load_dotenv

from ..agents import RoutingAgent, create_routing_agent_app
from ..core import shutdown_registry

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    parser = argparse.ArgumentParser(description="Routing Agent Server")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--agents",
        nargs="+",
        required=True,
        help="URLs of agents to discover (e.g., http://localhost:8001 http://localhost:8002)",
    )
    args = parser.parse_args()

    agent = RoutingAgent()

    print(f"\nDiscovering agents: {args.agents}")
    await agent.setup(args.agents)

    app = create_routing_agent_app(agent, args.host, args.port)

    shutdown_event = asyncio.Event()

    def signal_handler():
        logger.info("Shutting down...")
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    print(f"\nRouting Agent running at http://{args.host}:{args.port}")
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
        await shutdown_registry()
        logger.info("Routing Agent stopped")


def run():
    asyncio.run(main())


if __name__ == "__main__":
    run()
