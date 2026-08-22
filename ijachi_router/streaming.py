"""Streaming Token Engine for ijachi-llm-router.

Yields real-time token chunks from providers via native streaming APIs
(OpenAI stream=True, Anthropic text_stream, Groq/OpenRouter deltas).

This replaces the previous fake simulation that routed the full response
then split it into words — chunks now arrive from the provider in real time
with <100ms first-token perception.
"""

from __future__ import annotations

from typing import Iterator

from ijachi_router.core import route_stream
from ijachi_router.providers.base import GenerationResult


def stream_route(
    prompt: str,
    priority: str | None = None,
    humanize_mode: str = "light",
    force_model: str | None = None,
) -> Iterator[str]:
    """Stream real token chunks from the optimal provider.

    Yields text fragments (``str``) as they arrive from the API.
    The last item yielded is a :class:`GenerationResult` with full telemetry.

    Usage::

        for chunk in stream_route("Write a Python quicksort"):
            if isinstance(chunk, str):
                print(chunk, end="", flush=True)
            else:
                result = chunk   # GenerationResult with cost/tokens/savings

    Args:
        prompt: The user prompt to route and stream.
        priority: Routing priority — ``'cost'``, ``'speed'``, ``'quality'``, or ``'balanced'``.
        humanize_mode: Post-processing watermark stripping level (``'light'``, ``'full'``, ``'off'``).
        force_model: Optional model ID to pin (bypasses automatic selection).

    Yields:
        ``str`` chunks as they arrive, then a final :class:`GenerationResult`.
    """
    yield from route_stream(
        prompt=prompt,
        priority=priority,
        humanize_mode=humanize_mode,
        force_model=force_model,
    )
