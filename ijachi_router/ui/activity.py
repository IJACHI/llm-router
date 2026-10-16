"""Catchy Animated Status Spinner and Transparent Activity Streaming.

Displays Claude Code-style live animated spinner with rotating catchy phrases
and transparent output for routing, thought processes, decisions, and tool calls.
"""

from __future__ import annotations

import itertools
import re
import sys
import threading
import time
from typing import Callable

from rich.console import Console

console = Console()

# Catchy phrases cycled dynamically during turn processing
CATCHY_PHRASES = [
    "Thinking...",
    "Analyzing project architecture...",
    "Determining optimal tech stack...",
    "Evaluating candidate models...",
    "Synthesizing implementation strategy...",
    "Reading workspace context...",
    "Drafting code modules...",
    "Executing atomic file edits...",
    "Validating workspace consistency...",
    "Assembling context layers...",
    "Reviewing safety rules...",
    "Polishing response...",
]


_ACTIVE_SPINNERS: set[CatchyStatusSpinner] = set()


def ensure_spinners_stopped() -> None:
    """Ensure all background catchy spinners are cleanly terminated and joined."""
    for s in list(_ACTIVE_SPINNERS):
        try:
            s.stop()
        except Exception:
            pass
    _ACTIVE_SPINNERS.clear()


class CatchyStatusSpinner:
    """Live terminal spinner with rotating catchy phrases like Claude Code."""

    def __init__(self, initial_phrase: str = "Thinking...", interval: float = 1.8):
        self.initial_phrase = initial_phrase
        self.interval = interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._phrase_cycle = itertools.cycle(CATCHY_PHRASES)

    def _spin_loop(self):
        spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        frame_idx = 0
        current_phrase = self.initial_phrase
        last_phrase_time = time.monotonic()

        while not self._stop_event.is_set():
            now = time.monotonic()
            if now - last_phrase_time >= self.interval:
                current_phrase = next(self._phrase_cycle)
                last_phrase_time = now

            frame = spinner_frames[frame_idx % len(spinner_frames)]
            frame_idx += 1

            if not self._stop_event.is_set():
                # Render single-line status using ANSI clear-to-end-of-line (\033[K)
                sys.stdout.write(f"\r\033[K\033[1;36m{frame}\033[0m \033[2m{current_phrase}\033[0m")
                sys.stdout.flush()
            time.sleep(0.1)

        # Clear line on stop
        try:
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()
        except Exception:
            pass

    def start(self):
        self._stop_event.clear()
        _ACTIVE_SPINNERS.add(self)
        self._thread = threading.Thread(target=self._spin_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        _ACTIVE_SPINNERS.discard(self)
        try:
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()
        except Exception:
            pass

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


def render_routing_badge(model_id: str, provider: str, cost: float, reason: str, quality_tier: int = 2) -> None:
    """Print transparent routing badge at the start of a turn."""
    tier_label = {1: "Preview", 2: "Standard Code", 3: "Analytical", 4: "Frontier"}.get(quality_tier, f"Tier {quality_tier}")
    cost_str = "$0.00 (Local/Free)" if cost == 0.0 else f"${cost:.4f}"
    console.print(
        f"[bold cyan]⚡ Routed to:[/bold cyan] [bold green]{model_id}[/bold green] "
        f"[dim]({provider} · {tier_label} · {cost_str} · {reason})[/dim]"
    )


def render_thought_stream(thought: str, expanded: bool = False) -> None:
    """Render the model's internal thought process / rationale, collapsed by default.

    When collapsed (default):
        Renders a clean, single-line folded indicator with the core of what is being reasoned,
        preventing terminal clutter while maintaining 100% transparency.
    When expanded (via /verbose):
        Renders the full thought block.
    """
    if not thought or not thought.strip():
        return
    clean_thought = thought.strip()

    if expanded:
        console.print(f"\n[bold magenta]💭 Thought Process:[/bold magenta]\n[dim italic]{clean_thought}[/dim italic]\n")
    else:
        first_line = clean_thought.splitlines()[0].strip()
        first_line = re.sub(r"^[#*\-\s>]+", "", first_line)
        if len(first_line) > 75:
            first_line = first_line[:72] + "..."
        console.print(f"[dim magenta]▸ Thought:[/dim magenta] [dim italic]{first_line}[/dim italic] [dim](collapsed · /thoughts to view)[/dim]")


def render_tool_activity(
    tool_name: str,
    args: dict,
    success: bool,
    output: str = "",
    diff: str = "",
    expanded: bool = False,
) -> None:
    """Render live tool execution with intelligent collapsible summaries.

    Intelligently collapses verbose outputs:
        - Read: path + line count (no wall of code dumping into scrollback).
        - Write: path + lines written.
        - Edit: path + diff line stats (+X -Y).
        - Bash: command + high-signal status summary (e.g. tests passed) or failure error.
        - Grep/Glob/ListDir: query/pattern + matches count.
    Critical errors and warnings are always surfaced and never hidden.
    """
    status_icon = "[bold green]✓[/bold green]" if success else "[bold red]✗[/bold red]"

    # 1. READ FILE
    if tool_name in ("Read", "ReadFile"):
        path = args.get("path", "")
        line_count = len(output.splitlines()) if output else 0
        if success:
            console.print(f"{status_icon} [bold cyan]Read[/bold cyan] [white]{path}[/white] [dim]({line_count} lines read)[/dim]")
        else:
            console.print(f"{status_icon} [bold cyan]Read[/bold cyan] [white]{path}[/white] [bold red]FAILED[/bold red]")
            if output:
                console.print(f"  [dim red]↳ {output[:150]}[/dim red]")
        return

    # 2. WRITE FILE
    if tool_name in ("Write", "WriteFile"):
        path = args.get("path", "")
        content = args.get("content", "")
        line_count = len(content.splitlines()) if content else len(output.splitlines())
        if success:
            console.print(f"{status_icon} [bold cyan]Write[/bold cyan] [bold green]{path}[/bold green] [dim]({line_count} lines written)[/dim]")
        else:
            console.print(f"{status_icon} [bold cyan]Write[/bold cyan] [bold red]{path}[/bold red] [bold red]FAILED[/bold red]")
            if output:
                console.print(f"  [dim red]↳ {output[:150]}[/dim red]")
        return

    # 3. EDIT FILE
    if tool_name in ("Edit", "EditFile"):
        path = args.get("path", "")
        if success:
            diff_summary = ""
            if diff:
                added = len([l for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")])
                removed = len([l for l in diff.splitlines() if l.startswith("-") and not l.startswith("---")])
                diff_summary = f"[dim]([green]+{added}[/green] [red]-{removed}[/red] lines)[/dim]"
            console.print(f"{status_icon} [bold cyan]Edit[/bold cyan] [bold yellow]{path}[/bold yellow] {diff_summary}")
            if expanded and diff:
                from ijachi_router.ui.render import render_diff
                render_diff(diff, title=f"Edit in {path}")
        else:
            console.print(f"{status_icon} [bold cyan]Edit[/bold cyan] [bold red]{path}[/bold red] [bold red]FAILED[/bold red]")
            if output:
                console.print(f"  [dim red]↳ {output[:150]}[/dim red]")
        return

    # 4. BASH / SHELL COMMANDS
    if tool_name in ("Bash", "ExecuteCommand", "RunCommand"):
        cmd = args.get("command", "")
        cmd_display = cmd if len(cmd) <= 45 else cmd[:42] + "..."
        if success:
            lines = [l.strip() for l in output.splitlines() if l.strip()]
            summary_line = ""
            for l in reversed(lines):
                if any(w in l.lower() for w in ("passed", "success", "failed", "warning", "error", "done", "complete")):
                    summary_line = l
                    break
            if not summary_line and lines:
                summary_line = lines[-1]
            if len(summary_line) > 60:
                summary_line = summary_line[:57] + "..."

            summary_badge = f"[dim]· {summary_line}[/dim]" if summary_line else ""
            console.print(f"{status_icon} [bold cyan]Bash[/bold cyan] [white]`{cmd_display}`[/white] {summary_badge}")
            if expanded and output:
                console.print(f"[dim]{output[:400]}[/dim]")
        else:
            console.print(f"{status_icon} [bold cyan]Bash[/bold cyan] [white]`{cmd_display}`[/white] [bold red]FAILED[/bold red]")
            if output:
                first_err = next((l for l in output.splitlines() if "error" in l.lower() or "fail" in l.lower()), output.splitlines()[-1] if output.splitlines() else output)
                console.print(f"  [dim red]↳ {first_err[:150]}[/dim red]")
        return

    # 5. GREP / SEARCH
    if tool_name in ("Grep", "GrepSearch"):
        query = args.get("query", "")
        matches = len([l for l in output.splitlines() if l.strip()]) if output else 0
        console.print(f"{status_icon} [bold cyan]Grep[/bold cyan] query='[bold yellow]{query}[/bold yellow]' [dim]({matches} matches found)[/dim]")
        return

    # 6. GLOB / FIND FILES
    if tool_name in ("Glob", "FindFiles"):
        pattern = args.get("pattern", "*")
        found = len([l for l in output.splitlines() if l.strip()]) if output else 0
        console.print(f"{status_icon} [bold cyan]Glob[/bold cyan] pattern='[bold yellow]{pattern}[/bold yellow]' [dim]({found} files found)[/dim]")
        return

    # 7. LIST DIRECTORY
    if tool_name in ("ListDir", "ListDirectory"):
        path = args.get("path", ".")
        count = len([l for l in output.splitlines() if l.strip()]) if output else 0
        console.print(f"{status_icon} [bold cyan]ListDir[/bold cyan] [white]{path}[/white] [dim]({count} entries)[/dim]")
        return

    # 8. DEFAULT FALLBACK
    args_summary = ", ".join(f"{k}='{v}'" if isinstance(v, str) and len(str(v)) < 30 else f"{k}={v}" for k, v in list(args.items())[:2])
    console.print(f"{status_icon} [bold cyan]{tool_name}[/bold cyan]({args_summary})")
    if output and (not success or "error" in output.lower()):
        console.print(f"  [dim red]↳ {output[:150]}[/dim red]")
