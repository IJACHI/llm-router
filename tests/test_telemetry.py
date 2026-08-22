"""Tests for the telemetry stream."""

from __future__ import annotations

from ijachi_router.telemetry import TelemetryStream, EventType, telemetry


def test_telemetry_singleton():
    """The module-level telemetry instance is a singleton."""
    a = TelemetryStream()
    b = TelemetryStream()
    assert a is b
    assert telemetry is a


def test_start_and_finish_run():
    """Starting and finishing a run produces run events and a rollup."""
    t = TelemetryStream()
    t._reset()

    t.start_run("Refactor routing engine")
    assert t.events[0].type == EventType.RUN_START
    assert t.run_task == "Refactor routing engine"

    rollup = t.finish_run()
    assert "Crunched for" in rollup
    assert t.events[-1].type == EventType.RUN_FINISH


def test_tool_call_counters():
    """emit_tool_call bumps the matching workspace counters."""
    t = TelemetryStream()
    t._reset()

    t.emit_tool_call("read_file", {"path": "core.py"})
    t.emit_tool_call("read_file", {"path": "agent.py"})
    t.emit_tool_call("write_file", {"path": "ui.py"})
    t.emit_tool_call("list_dir", {"path": "."})

    counters = t.counters
    assert counters["files_read"] == 2
    assert counters["files_written"] == 1
    assert counters["dirs_listed"] == 1


def test_status_line_rollup():
    """format_status_line and format_rollup reflect counters and elapsed time."""
    t = TelemetryStream()
    t._reset()

    t.start_run("demo")
    t._counters["files_read"] = 3
    t._counters["searches"] = 1
    t._counters["llm_calls"] = 2

    status = t.format_status_line()
    assert "Thought for" in status
    assert "read 3 files" in status
    assert "searched for 1 pattern" in status
    assert "routed 2 LLM calls" in status

    rollup = t.format_rollup(elapsed_sec=75.0)
    assert "Crunched for 1m 15s" in rollup
    assert "4 tool calls" in rollup
    assert "2 LLM calls" in rollup


def test_cost_and_tokens_tracked():
    """Costs and tokens accumulate across events."""
    t = TelemetryStream()
    t._reset()

    t.emit(EventType.LLM_CALL, cost_usd=0.005, tokens_in=100, tokens_out=50)
    t.emit(EventType.LLM_CALL, cost_usd=0.003, tokens_in=60, tokens_out=30)

    assert t.total_cost == 0.008
    assert t.total_tokens == (160, 80)
