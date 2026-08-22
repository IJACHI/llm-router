"""Background subagent and task UI for ijachi-code.

Tracks named subagents and generic background tasks, shows live status cards,
allows expanding their outputs with Ctrl+O, and reports completion duration.

Usage
-----
::

    from ijachi_router.background_ui import BackgroundUIManager
    mgr = BackgroundUIManager()
    aid = mgr.spawn_agent("Thorough gap analysis", task_text)
    # ...later
    mgr.render_status()
    mgr.expand(aid)
"""

from __future__ import annotations

import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from rich.console import Console
from rich.panel import Panel
from rich.text import Text


@dataclass
class BackgroundAgent:
    """A backgrounded AgenticRouter run."""

    id: str
    name: str
    task: str
    future: Future
    start_time: float
    status: str = "running"  # running | done | error
    elapsed_sec: float = 0.0
    result_text: str = ""
    error: str = ""


@dataclass
class BackgroundTask:
    """A generic background task (any callable)."""

    id: str
    name: str
    future: Future
    start_time: float
    status: str = "running"
    elapsed_sec: float = 0.0
    result_text: str = ""
    error: str = ""


class BackgroundUIManager:
    """Registry and renderer for background agents/tasks.

    The manager keeps a global thread pool and a registry of active/completed
    background work. It is safe to instantiate multiple times; the underlying
    executor is shared lazily.
    """

    _executor: ThreadPoolExecutor | None = None

    def __init__(self, max_workers: int = 8) -> None:
        self.agents: dict[str, BackgroundAgent] = {}
        self.tasks: dict[str, BackgroundTask] = {}
        self._max_workers = max_workers
        self.console = Console()

    def _get_executor(self) -> ThreadPoolExecutor:
        if BackgroundUIManager._executor is None or BackgroundUIManager._executor._shutdown:
            BackgroundUIManager._executor = ThreadPoolExecutor(
                max_workers=self._max_workers,
                thread_name_prefix="ijachi-bg",
            )
        return BackgroundUIManager._executor

    # ------------------------------------------------------------------
    # Spawning
    # ------------------------------------------------------------------

    def spawn_agent(
        self,
        name: str,
        task: str,
        agent_factory: Callable[[], Any],
    ) -> str:
        """Spawn a named background agent and return its ID.

        Args:
            name: Human-readable agent name.
            task: The task string passed to the agent.
            agent_factory: Callable that returns an AgenticRouter-like object with
                a ``run(task, max_steps)`` method.

        Returns:
            The agent ID string.
        """
        agent_id = f"agent-{uuid.uuid4().hex[:8]}"
        start = time.monotonic()

        def _run() -> Any:
            from ijachi_router.telemetry import telemetry

            telemetry.emit_subagent_start(name)
            try:
                agent = agent_factory()
                result = agent.run(task, max_steps=10)
                return result
            except Exception as exc:
                raise exc

        future = self._get_executor().submit(_run)
        bg = BackgroundAgent(
            id=agent_id,
            name=name,
            task=task,
            future=future,
            start_time=start,
        )
        self.agents[agent_id] = bg

        # Attach completion callback
        future.add_done_callback(lambda f, aid=agent_id: self._on_agent_done(aid, f))
        return agent_id

    def submit_task(
        self,
        name: str,
        fn: Callable[..., Any],
        *args,
        **kwargs,
    ) -> str:
        """Submit a generic background task and return its ID."""
        task_id = f"task-{uuid.uuid4().hex[:8]}"
        start = time.monotonic()
        future = self._get_executor().submit(fn, *args, **kwargs)
        bg = BackgroundTask(
            id=task_id,
            name=name,
            future=future,
            start_time=start,
        )
        self.tasks[task_id] = bg
        future.add_done_callback(lambda f, tid=task_id: self._on_task_done(tid, f))
        return task_id

    # ------------------------------------------------------------------
    # Completion callbacks
    # ------------------------------------------------------------------

    def _on_agent_done(self, agent_id: str, future: Future) -> None:
        bg = self.agents.get(agent_id)
        if bg is None:
            return
        bg.elapsed_sec = time.monotonic() - bg.start_time
        try:
            result = future.result()
            bg.result_text = getattr(result, "final_text", str(result))
            bg.status = "done"
        except Exception as exc:
            bg.error = str(exc)
            bg.status = "error"

    def _on_task_done(self, task_id: str, future: Future) -> None:
        bg = self.tasks.get(task_id)
        if bg is None:
            return
        bg.elapsed_sec = time.monotonic() - bg.start_time
        try:
            bg.result_text = str(future.result())
            bg.status = "done"
        except Exception as exc:
            bg.error = str(exc)
            bg.status = "error"

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def active_count(self) -> int:
        """Number of agents + tasks still running."""
        running = sum(1 for a in self.agents.values() if a.status == "running")
        running += sum(1 for t in self.tasks.values() if t.status == "running")
        return running

    def list_active(self) -> list[BackgroundAgent | BackgroundTask]:
        """Return all currently running background work."""
        return [
            a for a in self.agents.values() if a.status == "running"
        ] + [t for t in self.tasks.values() if t.status == "running"]

    def get(self, work_id: str) -> BackgroundAgent | BackgroundTask | None:
        """Return a background agent or task by ID."""
        return self.agents.get(work_id) or self.tasks.get(work_id)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render_status(self, accessible: bool = False) -> None:
        """Print a summary card of all background agents/tasks."""
        if accessible:
            self._render_status_accessible()
            return

        if not self.agents and not self.tasks:
            self.console.print("[dim]No background work.[/dim]")
            return

        lines: list[Text] = []
        for bg in list(self.agents.values()) + list(self.tasks.values()):
            icon = "🟢" if bg.status == "running" else "🔴" if bg.status == "error" else "✅"
            elapsed = self._format_duration(bg.elapsed_sec or (time.monotonic() - bg.start_time))
            lines.append(Text.from_markup(f"  {icon} [bold]{bg.name}[/bold] [{bg.status}] · {elapsed}"))
            if bg.status == "done":
                preview = bg.result_text[:80].replace("\n", " ")
                lines.append(Text.from_markup(f"     [dim]{preview}[/dim]"))
            elif bg.status == "error":
                err = bg.error[:80].replace("\n", " ")
                lines.append(Text.from_markup(f"     [red]{err}[/red]"))

        panel = Panel(
            Text("\n").join(lines),
            title="[bold cyan]🌐 Background Work[/bold cyan]",
            border_style="bright_blue",
            padding=(0, 1),
        )
        self.console.print(panel)

    def expand(self, work_id: str, accessible: bool = False) -> None:
        """Expand and display the full output/result of a background agent/task."""
        bg = self.get(work_id)
        if bg is None:
            msg = f"Unknown background work ID: {work_id}"
            if accessible:
                print(msg)
            else:
                self.console.print(f"[red]{msg}[/red]")
            return

        if accessible:
            print(f"background: {bg.name} [{bg.status}]")
            print(bg.result_text or bg.error or "(still running)")
            return

        body = Text(bg.result_text or bg.error or "(still running)")
        self.console.print(
            Panel(
                body,
                title=f"[bold cyan]{bg.name}[/bold cyan]  [dim]{bg.status} · {self._format_duration(bg.elapsed_sec)}[/dim]",
                border_style="bright_blue",
                padding=(0, 1),
            )
        )

    def _render_status_accessible(self) -> None:
        for bg in list(self.agents.values()) + list(self.tasks.values()):
            print(f"background: {bg.name} [{bg.status}]")

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

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def shutdown(self, wait: bool = True) -> None:
        """Shutdown the shared executor. Mostly useful for tests."""
        if BackgroundUIManager._executor is not None:
            BackgroundUIManager._executor.shutdown(wait=wait)
            BackgroundUIManager._executor = None
