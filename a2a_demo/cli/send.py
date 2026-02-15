#!/usr/bin/env python3
"""Send a message to an A2A agent with interactive session support."""

import argparse
import asyncio
import logging
import uuid

from dotenv import load_dotenv

from ..core import get_registry, shutdown_registry

load_dotenv()

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


async def main():
    parser = argparse.ArgumentParser(description="Send a message to an A2A agent")
    parser.add_argument(
        "message",
        nargs="?",
        default=None,
        help="Message to send (optional, will prompt if not provided)",
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8000",
        help="Agent URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--session",
        default=None,
        help="Session ID for conversation continuity (auto-generated if not provided)",
    )
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Start interactive chat mode",
    )
    args = parser.parse_args()

    registry = get_registry()

    print(f"\nConnecting to {args.url}...")
    connection = await registry.discover_agent(args.url)

    if not connection:
        print(f"Error: Could not connect to agent at {args.url}")
        return

    print(f"Connected to: {connection.name}")

    session_id = args.session or str(uuid.uuid4())

    if args.interactive or args.message is None:
        print(f"Session ID: {session_id}")
        print("Type 'exit' or 'quit' to end the session.\n")

        while True:
            try:
                message = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye!")
                break

            if not message:
                continue
            if message.lower() in ("exit", "quit"):
                print("Goodbye!")
                break

            response = await registry.send_message_with_session(
                connection.name, message, session_id
            )
            print(f"\nAgent: {response}\n")
    else:
        print(f"Sending: {args.message}\n")
        response = await registry.send_message_with_session(
            connection.name, args.message, session_id
        )
        print(f"Response:\n{response}\n")
        print(
            f"(Session ID: {session_id} - use --session {session_id} to continue this conversation)"
        )

    await shutdown_registry()


def run():
    asyncio.run(main())


if __name__ == "__main__":
    run()
