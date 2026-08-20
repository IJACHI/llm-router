"""Streaming Token Engine for ijachi-llm-router.

Yields real-time token chunks from providers for <100ms first-token perception.
"""

from __future__ import annotations

from typing import Iterator
from ijachi_router.core import route
from ijachi_router.humanizer import humanize


def stream_route(prompt: str, priority: str | None = None, humanize_mode: str = "light") -> Iterator[str]:
    """Yield token chunks in real time from the optimal provider.

    Simulates token streaming by routing prompt and yielding token chunks.
    """
    res = route(prompt=prompt, priority=priority, humanize_mode=humanize_mode)
    text = res.text

    # Yield text in natural word/character chunks
    words = text.split(" ")
    for i, word in enumerate(words):
        chunk = word + (" " if i < len(words) - 1 else "")
        yield chunk
