"""Real-time activity telemetry & execution roll-ups for ijachi-code.

Provides an event-driven telemetry stream that records every action the agent
takes during a run (file reads, edits, shell commands, searches, LLM calls,
etc.) and aggregates them into Claude Code-style status lines and roll-ups.

Usage
-----
::

    from ijachi_router.telemetry import telemetry
    telemetry.start_run("Refactor routing engine")
    telemetry.emit_tool_call("read_file", {"path": "core.py"})
    ...
    print(telemetry.format_status_line())
    telemetry.finish_run()
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EventType(Enum):
    """Kinds of telemetry events."""

    RUN_START = "run_start"
    RUN_FINISH = "run_finish"
    THINKING = "thinking"
    TOOL_CALL = "tool_call"
    TOOL_OUTPUT = "tool_output"
    LLM_CALL = "llm_call"
    SUBAGENT = "subagent"
    SUBAGENT_FINISH = "subagent_finish"
    ROLLUP = "rollup"
    CUSTOM = "custom"


@dataclass
class TelemetryEvent:
    """A single telemetry event."""

    type: EventType
    message: str = ""
    timestamp: float = field(default_factory=time.monotonic)
    metadata: dict[str, Any] = field(default_factory=dict)
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0


class TelemetryStream:
    """Singleton activity stream that records and aggregates agent telemetry.

    This class is designed to be accessed through the module-level ``telemetry``
    instance. It is safe to call from multiple threads because all mutations go
    through one object reference.
    """

    _instance: TelemetryStream | None = None

    def __new__(cls) -> TelemetryStream:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._reset()
        return cls._instance

    def _reset(self) -> None:
        """Reset internal counters and state (mostly useful for tests)."""
        self.events: list[TelemetryEvent] = []
        self._run_start: float | None = None
        self._run_task: str = ""
        self._active_activities: dict[str, float] = {}
        self._counters: dict[str, int] = {
            "files_read": 0,
            "files_written": 0,
            "files_edited": 0,
            "dirs_listed": 0,
            "searches": 0,
            "commands_run": 0,
            "llm_calls": 0,
            "subagents": 0,
        }
        self._cost: float = 0.0
        self._tokens_in: int = 0
        self._tokens_out: int = 0

    # ------------------------------------------------------------------
    # Event emission
    # ------------------------------------------------------------------

    def emit(
        self,
        event_type: EventType,
        message: str = "",
        metadata: dict[str, Any] | None = None,
        cost_usd: float = 0.0,
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> TelemetryEvent:
        """Record a telemetry event and update counters."""
        event = TelemetryEvent(
            type=event_type,
            message=message,
            metadata=metadata or {},
            cost_usd=cost_usd,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
        self.events.append(event)
        if cost_usd:
            self._cost += cost_usd
        if tokens_in:
            self._tokens_in += tokens_in
        if tokens_out:
            self._tokens_out += tokens_out
        return event

    def start_run(self, task: str) -> None:
        """Start tracking a new agent run."""
        self._reset()
        self._run_start = time.monotonic()
        self._run_task = task
        self.emit(EventType.RUN_START, f"Started: {task}", {"task": task})

    def finish_run(self, completed: bool = True) -> str:
        """Finish the current run and return a roll-up summary."""
        elapsed = 0.0
        if self._run_start is not None:
            elapsed = time.monotonic() - self._run_start
        status = "complete" if completed else "incomplete"
        summary = self.format_rollup(elapsed)
        self.emit(
            EventType.RUN_FINISH,
            summary,
            {"elapsed_sec": elapsed, "status": status},
            cost_usd=self._cost,
            tokens_in=self._tokens_in,
            tokens_out=self._tokens_out,
        )
        return summary

    def start_activity(self, label: str) -> None:
        """Mark the start of a named sub-activity (e.g. 'indexing workspace')."""
        self._active_activities[label] = time.monotonic()

    def finish_activity(self, label: str) -> str | None:
        """Mark the end of a named sub-activity and return a roll-up string."""
        start = self._active_activities.pop(label, None)
        if start is None:
            return None
        elapsed = time.monotonic() - start
        summary = f"* {label} · {self._format_duration(elapsed)}"
        self.emit(EventType.ROLLUP, summary, {"label": label, "elapsed_sec": elapsed})
        return summary

    # ------------------------------------------------------------------
    # Convenience emitters
    # ------------------------------------------------------------------

    def emit_tool_call(
        self,
        tool_name: str,
        args: dict[str, Any] | None = None,
    ) -> TelemetryEvent:
        """Record a workspace tool call and bump the matching counter."""
        meta = {"tool": tool_name, "args": args or {}}
        counter_key = self._tool_counter_key(tool_name)
        if counter_key:
            self._counters[counter_key] += 1
        return self.emit(EventType.TOOL_CALL, f"{tool_name}", meta)

    def emit_tool_output(self, tool_name: str, output: str) -> TelemetryEvent:
        """Record the output of a workspace tool call."""
        return self.emit(
            EventType.TOOL_OUTPUT,
            f"{tool_name} → done",
            {"tool": tool_name, "output_preview": output[:200]},
        )

    def emit_llm_call(
        self,
        model: str,
        cost_usd: float,
        tokens_in: int,
        tokens_out: int,
    ) -> TelemetryEvent:
        """Record an LLM routing call."""
        self._counters["llm_calls"] += 1
        return self.emit(
            EventType.LLM_CALL,
            f"routed to {model}",
            {"model": model},
            cost_usd=cost_usd,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )

    def emit_subagent_start(self, name: str) -> TelemetryEvent:
        """Record the start of a background subagent."""
        self._counters["subagents"] += 1
        return self.emit(EventType.SUBAGENT, f"started subagent {name}", {"name": name})

    def emit_subagent_finish(self, name: str, elapsed_sec: float) -> TelemetryEvent:
        """Record the completion of a background subagent."""
        return self.emit(
            EventType.SUBAGENT_FINISH,
            f"finished subagent {name}",
            {"name": name, "elapsed_sec": elapsed_sec},
        )

    # ------------------------------------------------------------------
    # Formatters
    # ------------------------------------------------------------------

    def format_status_line(self) -> str:
        """Return a concise 'Thought for X, read N files...' style status line.

        Example:
            "Thought for 18s, searched for 1 pattern, read 3 files,
             listed 1 directory, ran 3 shell commands"
        """
        elapsed = 0.0
        if self._run_start is not None:
            elapsed = time.monotonic() - self._run_start

        parts: list[str] = []
        parts.append(f"Thought for {self._format_duration(elapsed)}")

        if self._counters["searches"]:
            n = self._counters["searches"]
            parts.append(f"searched for {n} pattern{'s' if n != 1 else ''}")
        if self._counters["files_read"]:
            n = self._counters["files_read"]
            parts.append(f"read {n} file{'s' if n != 1 else ''}")
        if self._counters["dirs_listed"]:
            n = self._counters["dirs_listed"]
            parts.append(f"listed {n} director{'ies' if n != 1 else 'y'}")
        if self._counters["commands_run"]:
            n = self._counters["commands_run"]
            parts.append(f"ran {n} shell command{'s' if n != 1 else ''}")
        if self._counters["files_written"]:
            n = self._counters["files_written"]
            parts.append(f"wrote {n} file{'s' if n != 1 else ''}")
        if self._counters["files_edited"]:
            n = self._counters["files_edited"]
            parts.append(f"edited {n} file{'s' if n != 1 else ''}")
        if self._counters["llm_calls"]:
            n = self._counters["llm_calls"]
            parts.append(f"routed {n} LLM call{'s' if n != 1 else ''}")

        return ", ".join(parts)

    def format_rollup(self, elapsed_sec: float | None = None) -> str:
        """Return a high-level execution roll-up string.

        Example:
            "* Crunched for 2m 59s — 12 tools, 4 LLM calls, $0.0042"
        """
        if elapsed_sec is None and self._run_start is not None:
            elapsed_sec = time.monotonic() - self._run_start
        elapsed_sec = elapsed_sec or 0.0

        total_tools = (
            self._counters["files_read"]
            + self._counters["files_written"]
            + self._counters["files_edited"]
            + self._counters["dirs_listed"]
            + self._counters["searches"]
            + self._counters["commands_run"]
        )
        return (
            f"* Crunched for {self._format_duration(elapsed_sec)} — "
            f"{total_tools} tool call{'s' if total_tools != 1 else ''}, "
            f"{self._counters['llm_calls']} LLM call{'s' if self._counters['llm_calls'] != 1 else ''}, "
            f"${self._cost:.4f}"
        )

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def counters(self) -> dict[str, int]:
        """Return a copy of the current counter map."""
        return dict(self._counters)

    @property
    def total_cost(self) -> float:
        """Cumulative cost recorded so far."""
        return self._cost

    @property
    def total_tokens(self) -> tuple[int, int]:
        """Cumulative (input, output) tokens recorded so far."""
        return (self._tokens_in, self._tokens_out)

    @property
    def run_task(self) -> str:
        """The task label passed to start_run."""
        return self._run_task

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _tool_counter_key(self, tool_name: str) -> str | None:
        mapping = {
            "read_file": "files_read",
            "write_file": "files_written",
            "edit_file": "files_edited",
            "list_dir": "dirs_listed",
            "grep_search": "searches",
            "run_command": "commands_run",
        }
        return mapping.get(tool_name)

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format a duration as 'Xs', 'Xm Ys', or 'Xh Ym Zs'."""
        seconds = max(0, int(seconds))
        if seconds < 60:
            return f"{seconds}s"
        minutes, seconds = divmod(seconds, 60)
        if minutes < 60:
            return f"{minutes}m {seconds}s"
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h {minutes}m {seconds}s"


# Module-level singleton instance
telemetry = TelemetryStream()
