"""Live task checklist panel for ijachi-code.

Displays a dynamic checklist with elapsed time, token count, active/pending/
completed states, and the ability to collapse older completed items.

Usage
-----
::

    from ijachi_router.task_panel import TaskPanel
    panel = TaskPanel()
    panel.add("Read core.py")
    panel.add("Apply fix")
    with panel.live():
        panel.set_active(0)
        ...
        panel.complete(0)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Iterator

from rich.console import Console, ConsoleRenderable
from rich.live import Live
from rich.panel import Panel
from rich.text import Text


class TaskStatus:
    """Status constants for checklist items."""

    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"


@dataclass
class TaskItem:
    """A single task in the checklist."""

    label: str
    status: str = TaskStatus.PENDING
    start_time: float | None = None
    finish_time: float | None = None
    metadata: str = ""

    @property
    def duration(self) -> float:
        """Elapsed seconds for this item."""
        if self.start_time is None:
            return 0.0
        end = self.finish_time or time.monotonic()
        return end - self.start_time


class TaskPanel:
    """Live-updating task checklist panel.

    Args:
        accessible: If True, render plain text output instead of Rich panels.
        max_visible_completed: Maximum number of completed items to show before
            collapsing the rest into ".. +N completed".
    """

    def __init__(
        self,
        accessible: bool = False,
        max_visible_completed: int = 3,
    ) -> None:
        self.accessible = accessible
        self.max_visible_completed = max_visible_completed
        self.items: list[TaskItem] = []
        self._start_time = time.monotonic()
        self._tokens_in = 0
        self._tokens_out = 0
        self._state = "thinking"
        self._live: Live | None = None
        self._console = Console()

    # ------------------------------------------------------------------
    # Item management
    # ------------------------------------------------------------------

    def add(self, label: str, status: str = TaskStatus.PENDING) -> int:
        """Add a new task and return its index."""
        item = TaskItem(label=label, status=status)
        self.items.append(item)
        self.refresh()
        return len(self.items) - 1

    def set_active(self, index: int) -> None:
        """Mark the item at *index* as active and refresh the panel."""
        if 0 <= index < len(self.items):
            self.items[index].status = TaskStatus.ACTIVE
            self.items[index].start_time = time.monotonic()
            self.refresh()

    def complete(self, index: int, metadata: str = "") -> None:
        """Mark the item at *index* as completed and refresh the panel."""
        if 0 <= index < len(self.items):
            item = self.items[index]
            item.status = TaskStatus.COMPLETED
            item.finish_time = time.monotonic()
            item.metadata = metadata
            self.refresh()

    def update_label(self, index: int, label: str) -> None:
        """Update an item label in place."""
        if 0 <= index < len(self.items):
            self.items[index].label = label
            self.refresh()

    # ------------------------------------------------------------------
    # Token / state telemetry
    # ------------------------------------------------------------------

    def set_tokens(self, tokens_in: int, tokens_out: int) -> None:
        """Update the displayed token counters."""
        self._tokens_in = tokens_in
        self._tokens_out = tokens_out
        self.refresh()

    def add_tokens(self, tokens_in: int, tokens_out: int) -> None:
        """Increment token counters."""
        self._tokens_in += tokens_in
        self._tokens_out += tokens_out
        self.refresh()

    def set_state(self, state: str) -> None:
        """Update the short state label (e.g. 'thinking', 'running')."""
        self._state = state
        self.refresh()

    # ------------------------------------------------------------------
    # Live rendering
    # ------------------------------------------------------------------

    def live(self) -> "_TaskPanelLiveContext":
        """Return a context manager that starts/stops the live panel."""
        return _TaskPanelLiveContext(self)

    def start(self) -> None:
        """Start live updating. Idempotent."""
        if self._live is not None:
            return
        self._start_time = time.monotonic()
        self._live = Live(self.render(), refresh_per_second=4, transient=False)
        self._live.start()

    def stop(self) -> None:
        """Stop live updating."""
        if self._live is not None:
            self._live.stop()
            self._live = None

    def refresh(self) -> None:
        """Refresh the live display if active, or reprint in accessible mode."""
        if self.accessible:
            self._print_accessible()
        elif self._live is not None:
            self._live.update(self.render())

    def render(self) -> ConsoleRenderable:
        """Return the current Rich renderable."""
        elapsed = time.monotonic() - self._start_time
        header = (
            f"({self._format_duration(elapsed)} · "
            f"↓ {self._format_tokens(self._tokens_in + self._tokens_out)} tokens · "
            f"{self._state})"
        )

        lines: list[Text] = []
        completed_hidden = 0
        visible_completed = 0

        for item in self.items:
            if item.status == TaskStatus.COMPLETED:
                if visible_completed >= self.max_visible_completed:
                    completed_hidden += 1
                    continue
                visible_completed += 1
                dur = self._format_duration(item.duration)
                meta = f" {item.metadata}" if item.metadata else ""
                lines.append(Text.from_markup(f"  [green]✔[/green] {item.label} [dim]({dur}){meta}[/dim]"))
            elif item.status == TaskStatus.ACTIVE:
                lines.append(Text.from_markup(f"  [bright_yellow]■[/bright_yellow] {item.label}"))
            else:
                lines.append(Text.from_markup(f"  [dim]□[/dim] {item.label}"))

        if completed_hidden:
            lines.append(Text.from_markup(f"  [dim].. +{completed_hidden} completed[/dim]"))

        body = Text("\n").join(lines) if lines else Text("  [dim](no tasks)[/dim]")
        return Panel(
            body,
            title=f"[bold cyan]📋 Tasks[/bold cyan]  [dim]{header}[/dim]",
            border_style="cyan",
            padding=(0, 1),
        )

    def _print_accessible(self) -> None:
        """Print a plain-text version of the checklist."""
        elapsed = time.monotonic() - self._start_time
        total = self._tokens_in + self._tokens_out
        print(f"tasks: {self._format_duration(elapsed)} | {total} tokens | {self._state}")
        for item in self.items:
            mark = {
                TaskStatus.COMPLETED: "[x]",
                TaskStatus.ACTIVE: "[*]",
                TaskStatus.PENDING: "[ ]",
            }[item.status]
            print(f"  {mark} {item.label}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_duration(seconds: float) -> str:
        seconds = max(0, int(seconds))
        if seconds < 60:
            return f"{seconds}s"
        minutes, seconds = divmod(seconds, 60)
        if minutes < 60:
            return f"{minutes}m {seconds}s"
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h {minutes}m {seconds}s"

    @staticmethod
    def _format_tokens(n: int) -> str:
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.1f}k"
        return str(n)


class _TaskPanelLiveContext:
    """Context-manager wrapper around TaskPanel live updating."""

    def __init__(self, panel: TaskPanel) -> None:
        self.panel = panel

    def __enter__(self) -> TaskPanel:
        self.panel.start()
        return self.panel

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.panel.stop()
