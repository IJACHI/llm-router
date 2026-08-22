"""Unit tests for real-time streaming, live event bus, and telemetry display."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from ijachi_router.providers.base import GenerationResult, Provider, ProviderError
from ijachi_router.live_events import (
    PipelineEvent,
    DONE_SENTINEL,
    emit,
    pipeline_event_context,
    drain_events,
)


# ---------------------------------------------------------------------------
# Mock providers for streaming tests
# ---------------------------------------------------------------------------

class _MockStreamProvider(Provider):
    """Provider that yields 3 real word chunks via _stream."""
    name = "mock_stream"

    def _call(self, prompt: str, **kwargs):
        return "hello world done", 5, 3

    def _stream(self, prompt: str, **kwargs):
        for word in ["hello ", "world ", "done"]:
            yield word


class _FallbackProvider(Provider):
    """Provider that raises on _stream but succeeds on _call (tests fallback)."""
    name = "mock_fallback"

    def _call(self, prompt: str, **kwargs):
        return "fallback response", 4, 4

    def _stream(self, prompt: str, **kwargs):
        raise RuntimeError("streaming not supported")


# ---------------------------------------------------------------------------
# Provider streaming
# ---------------------------------------------------------------------------

def test_provider_base_default_stream_fallback():
    """Default _stream yields the full text from _call as a single chunk."""

    class _SingleChunk(Provider):
        name = "single"
        def _call(self, prompt, **kwargs):
            return "full text", 3, 3

    p = _SingleChunk(model_id="m1", pricing={})
    chunks = list(p.stream("test"))
    assert chunks == ["full text"]


def test_provider_stream_yields_multiple_chunks():
    """_MockStreamProvider streams 3 chunks in real time."""
    p = _MockStreamProvider(model_id="mock", pricing={})
    chunks = list(p.stream("hi"))
    assert chunks == ["hello ", "world ", "done"]
    assert "".join(chunks) == "hello world done"


def test_provider_stream_public_method_calls_underscored():
    """Provider.stream() delegates to _stream()."""
    p = _MockStreamProvider(model_id="mock", pricing={})
    result = "".join(p.stream("prompt"))
    assert result == "hello world done"


# ---------------------------------------------------------------------------
# Live event bus
# ---------------------------------------------------------------------------

def test_emit_without_subscriber_is_noop():
    """emit() silently drops events when no subscriber queue is active."""
    # Should not raise even though no queue is set
    emit("classify", "no subscriber active")


def test_pipeline_event_context_captures_events():
    """Events emitted inside a pipeline_event_context() are captured in the queue."""
    with pipeline_event_context() as q:
        emit("classify", "test classification", category="code")
        emit("rank", "test ranking")

    events = drain_events(q, timeout=0.1)
    assert len(events) == 2
    assert events[0].kind == "classify"
    assert events[1].kind == "rank"
    assert events[0].data["category"] == "code"


def test_pipeline_event_context_done_sentinel_ends_drain():
    """drain_events() stops when it hits DONE_SENTINEL."""
    with pipeline_event_context() as q:
        emit("query", "querying model")

    events = drain_events(q, timeout=0.1)
    assert any(e.kind == "query" for e in events)


def test_pipeline_event_render_returns_markup():
    """PipelineEvent.render() returns a non-empty string with the message."""
    ev = PipelineEvent(kind="done", message="finished in 1.2s")
    rendered = ev.render()
    assert "finished in 1.2s" in rendered
    assert len(rendered) > 10


def test_events_are_thread_isolated():
    """Each thread gets its own event queue — no cross-thread bleed."""
    results: dict[str, list] = {"t1": [], "t2": []}

    def run_in_thread(name: str):
        with pipeline_event_context() as q:
            emit("classify", f"from {name}")
            results[name] = drain_events(q, timeout=0.1)

    t1 = threading.Thread(target=run_in_thread, args=("t1",))
    t2 = threading.Thread(target=run_in_thread, args=("t2",))
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert len(results["t1"]) == 1
    assert results["t1"][0].message == "from t1"
    assert len(results["t2"]) == 1
    assert results["t2"][0].message == "from t2"


# ---------------------------------------------------------------------------
# route_stream
# ---------------------------------------------------------------------------

def _make_mock_provider_list():
    """Return a list with one _MockStreamProvider instance."""
    return [_MockStreamProvider(model_id="mock", pricing={"input_per_1k": 0.001, "output_per_1k": 0.002})]


def test_route_stream_yields_chunks_then_result(monkeypatch):
    """route_stream yields str chunks and then a GenerationResult as last item."""
    from ijachi_router.core import Router

    monkeypatch.setattr(
        "ijachi_router.core._prepare_pipeline",
        lambda prompt, config, *a, **kw: (
            _make_mock_provider_list(),
            prompt,
            "code",
            0.5,
        ),
    )

    router = Router.__new__(Router)
    router.config = MagicMock()
    router.config.priority = "balanced"

    items = list(router.route_stream("test prompt"))
    str_chunks = [i for i in items if isinstance(i, str)]
    result_items = [i for i in items if isinstance(i, GenerationResult)]

    assert len(str_chunks) >= 1
    assert len(result_items) == 1
    full_text = "".join(str_chunks)
    assert "hello" in full_text


def test_route_stream_emits_pipeline_events(monkeypatch):
    """route_stream emits at least a 'done' pipeline event."""
    from ijachi_router.core import Router

    monkeypatch.setattr(
        "ijachi_router.core._prepare_pipeline",
        lambda prompt, config, *a, **kw: (
            _make_mock_provider_list(),
            prompt,
            "code",
            0.5,
        ),
    )

    router = Router.__new__(Router)
    router.config = MagicMock()
    router.config.priority = "balanced"

    with pipeline_event_context() as q:
        list(router.route_stream("test prompt"))

    events = drain_events(q, timeout=0.2)
    kinds = {e.kind for e in events}
    assert "done" in kinds


# ---------------------------------------------------------------------------
# Telemetry rendering (UI layer)
# ---------------------------------------------------------------------------

def test_render_route_footer_prints_to_console(capsys):
    """render_route_footer prints the model name and cost to stdout."""
    from ijachi_router.ui import render_route_footer

    res = GenerationResult(
        text="hello",
        provider="groq",
        model="llama-3.3-70b",
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.0009,
        latency_s=1.2,
        cost_saved_usd=0.004,
        savings_pct=81.6,
        tokens_per_sec=125.0,
        baseline_model="gpt-4o",
        baseline_cost_usd=0.005,
    )

    # Should not raise — we just verify it runs without error in accessible mode
    from ijachi_router.ui import set_theme
    set_theme("accessible")
    render_route_footer(res)
    captured = capsys.readouterr()
    assert "llama-3.3-70b" in captured.out or "model=" in captured.out
    set_theme("dark")
