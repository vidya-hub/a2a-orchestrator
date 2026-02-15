"""CLI entry points for A2A Demo."""

from .research import run as research
from .routing import run as routing
from .send import run as send
from .writer import run as writer

__all__ = ["research", "writer", "routing", "send"]
