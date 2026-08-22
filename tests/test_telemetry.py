"""Unit tests for ijachi_router/telemetry.py."""

from __future__ import annotations

import time

import pytest

from ijachi_router.telemetry import TelemetryStream, EventType, telemetry


@pytest.fixture
def fresh_telemetry():
    """Return a reset telemetry instance for each test."""
    t = TelemetryStream()
    t._reset()
    return t


def test_emit_updates_counters(fresh_telemetry):
    t = fresh_telemetry
    t.emit_tool_call("read_file", {"path": "a.py"})
    t.emit_tool_call("read_file", {"path": "b.py"})
    t.emit_tool_call("list_dir")
    t.emit_tool_call("run_command", {"command": "pytest"})

    assert t.counters["files_read"] == 2
    assert t.counters["dirs_listed"] == 1
    assert t.counters["commands_run"] == 1


def test_llm_call_tracks_cost_and_tokens(fresh_telemetry):
    t = fresh_telemetry
    t.emit_llm_call("gpt-4o", 0.0012, 100, 50)
    assert t.counters["llm_calls"] == 1
    assert t.total_cost == pytest.approx(0.0012)
    assert t.total_tokens == (100, 50)


def test_status_line_formatting(fresh_telemetry):
    t = fresh_telemetry
    t.start_run("test run")
    time.sleep(0.01)
    t.emit_tool_call("read_file")
    t.emit_tool_call("read_file")
    t.emit_tool_call("grep_search")
    t.emit_tool_call("run_command")

    status = t.format_status_line()
    assert "Thought for" in status
    assert "read 2 files" in status
    assert "searched for 1 pattern" in status
    assert "ran 1 shell command" in status


def test_rollup_formatting(fresh_telemetry):
    t = fresh_telemetry
    t.start_run("test run")
    time.sleep(0.01)
    for _ in range(3):
        t.emit_tool_call("read_file")
    t.emit_tool_call("run_command")
    t.emit_llm_call("gpt-4o", 0.0042, 10, 20)

    rollup = t.finish_run()
    assert "* Crunched for" in rollup
    assert "4 tool calls" in rollup
    assert "1 LLM call" in rollup
    assert "$0.0042" in rollup


def test_activity_rollup(fresh_telemetry):
    t = fresh_telemetry
    t.start_run("test run")
    t.start_activity("indexing workspace")
    time.sleep(0.02)
    summary = t.finish_activity("indexing workspace")
    assert summary is not None
    assert "indexing workspace" in summary
    assert any(e.type == EventType.ROLLUP for e in t.events)


def test_subagent_events(fresh_telemetry):
    t = fresh_telemetry
    t.start_run("test run")
    t.emit_subagent_start("gap analysis")
    t.emit_subagent_finish("gap analysis", 12.5)
    assert t.counters["subagents"] == 1
    assert any(
        e.type == EventType.SUBAGENT_FINISH and e.metadata.get("elapsed_sec") == 12.5
        for e in t.events
    )


def test_unknown_tool_does_not_crash(fresh_telemetry):
    t = fresh_telemetry
    t.emit_tool_call("magic")
    assert t.counters["files_read"] == 0


def test_module_singleton():
    """The module-level telemetry is a singleton."""
    from ijachi_router import telemetry as telemetry_mod

    a = telemetry_mod.telemetry
    b = telemetry_mod.TelemetryStream()
    assert a is b
