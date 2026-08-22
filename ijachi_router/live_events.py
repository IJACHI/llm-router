"""Live Pipeline Event Bus for ijachi-code.

Emits named events as the routing pipeline progresses so the terminal UI can
narrate every stage to the user in real time — eliminating silent waiting.

Events are emitted synchronously from within the pipeline and consumed by the
CLI chat loop, which prints them as they arrive using Rich markup.

Usage
-----
::

    from ijachi_router.live_events import pipeline_events, emit

    # Emitting events from inside the pipeline:
    emit("classify", "Classified → code · complexity 0.72 · confidence 0.91")
    emit("query",    "Querying groq/llama-3.3-70b...", model="groq/llama-3.3-70b")

    # Consuming events in the chat loop (blocking iterator):
    for event in pipeline_events():
        print(event.render())
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from typing import Iterator

# ---------------------------------------------------------------------------
# Event model
# ---------------------------------------------------------------------------

# Emoji prefixes for each event kind
_KIND_ICONS: dict[str, str] = {
    "classify":  "🔍",
    "rank":      "📊",
    "query":     "📡",
    "cache_hit": "⚡",
    "tool":      "🛠 ",
    "security":  "🔐",
    "humanize":  "✍️ ",
    "stream":    "💬",
    "done":      "✅",
    "error":     "❌",
    "info":      "ℹ️ ",
}

_KIND_STYLES: dict[str, str] = {
    "classify":  "dim cyan",
    "rank":      "dim cyan",
    "query":     "bold cyan",
    "cache_hit": "bold yellow",
    "tool":      "bold yellow",
    "security":  "dim magenta",
    "humanize":  "dim",
    "stream":    "dim",
    "done":      "bold green",
    "error":     "bold red",
    "info":      "dim cyan",
}

# Sentinel to signal end of event stream
_DONE_SENTINEL = object()


@dataclass
class PipelineEvent:
    """A single named pipeline event with an optional payload."""
    kind: str
    message: str
    data: dict = field(default_factory=dict)

    def render(self) -> str:
        """Return a Rich markup string for this event."""
        icon = _KIND_ICONS.get(self.kind, "•")
        style = _KIND_STYLES.get(self.kind, "dim")
        return f"[{style}]{icon} {self.message}[/{style}]"


# ---------------------------------------------------------------------------
# Thread-local event bus (one per route/agent invocation)
# ---------------------------------------------------------------------------

# Each active streaming invocation gets its own queue via a context variable.
# We use threading.local() so parallel calls in tests don't bleed into each other.
_local = threading.local()


def _get_queue() -> queue.SimpleQueue | None:
    """Return the active event queue for the current thread, or None."""
    return getattr(_local, "event_queue", None)


def _set_queue(q: queue.SimpleQueue | None) -> None:
    _local.event_queue = q


# ---------------------------------------------------------------------------
# Public emit API (called from inside the routing pipeline)
# ---------------------------------------------------------------------------

def emit(kind: str, message: str, **data) -> None:
    """Emit a pipeline event to the current thread's subscriber queue.

    Safe to call even if no subscriber is active — events are silently dropped
    when there is no active queue (e.g. in background/batch usage).

    Args:
        kind: Event type identifier (e.g. 'classify', 'rank', 'query', 'tool').
        message: Human-readable event message.
        **data: Optional structured key-value payload attached to the event.
    """
    q = _get_queue()
    if q is not None:
        q.put(PipelineEvent(kind=kind, message=message, data=data))


# ---------------------------------------------------------------------------
# Subscriber context manager (used by the CLI chat loop)
# ---------------------------------------------------------------------------

from contextlib import contextmanager


@contextmanager
def pipeline_event_context():
    """Context manager that activates a live event queue for the current thread.

    While this context is active, all ``emit()`` calls from the same thread
    will enqueue events. On exit the queue is flushed and cleared.

    Yields:
        A :class:`queue.SimpleQueue` — iterate over it to consume events.

    Example::

        with pipeline_event_context() as q:
            # Start routing in a thread, then consume events
            for event in iter(q.get, _DONE_SENTINEL):
                print(event.render())
    """
    q: queue.SimpleQueue = queue.SimpleQueue()
    _set_queue(q)
    try:
        yield q
    finally:
        # Signal end-of-stream and clean up
        q.put(_DONE_SENTINEL)
        _set_queue(None)


def drain_events(q: queue.SimpleQueue, timeout: float = 0.05) -> list[PipelineEvent]:
    """Non-blocking drain of all currently queued events.

    Args:
        q: The event queue to drain.
        timeout: Maximum seconds to wait for each item.

    Returns:
        List of :class:`PipelineEvent` objects currently in the queue.
    """
    events: list[PipelineEvent] = []
    while True:
        try:
            item = q.get(timeout=timeout)
            if item is _DONE_SENTINEL:
                break
            events.append(item)
        except queue.Empty:
            break
    return events


DONE_SENTINEL = _DONE_SENTINEL
