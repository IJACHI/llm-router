"""Streaming Token Engine for ijachi-llm-router.

Yields real-time token chunks from providers for <100ms first-token perception.
"""

from __future__ import annotations

from typing import Iterator
from ijachi_router.core import Router
from ijachi_router.humanizer import humanize


def stream_route(prompt: str, priority: str | None = None, humanize_mode: str = "light") -> Iterator[str]:
    """Yield token chunks in real time from the optimal provider."""
    router = Router()
    collected: list[str] = []
    for chunk in router.stream(prompt, priority=priority, humanize_mode=humanize_mode):
        collected.append(chunk)
        yield chunk
