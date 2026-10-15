"""Catchy Animated Status Spinner and Transparent Activity Streaming.

Displays Claude Code-style live animated spinner with rotating catchy phrases
and transparent output for routing, thought processes, decisions, and tool calls.
"""

from __future__ import annotations

import itertools
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

            # Render single-line status
            console.print(f"\r[bold cyan]{frame}[/bold cyan] [dim white]{current_phrase}[/dim white]   ", end="")
            time.sleep(0.1)

        # Clear line on stop
        console.print("\r" + " " * 70 + "\r", end="")

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._spin_loop, daemon=True)
        self._thread.start()

    def stop(self):
        if self._thread and self._thread.is_alive():
            self._stop_event.set()
            self._thread.join(timeout=0.5)

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


def render_thought_stream(thought: str) -> None:
    """Render the model's internal thought process / rationale."""
    if not thought or not thought.strip():
        return
    clean_thought = thought.strip()
    console.print(f"\n[bold magenta]💭 Thought Process:[/bold magenta]\n[italic dim]{clean_thought}[/italic dim]")


def render_tool_activity(tool_name: str, args: dict, success: bool, output: str = "") -> None:
    """Render live tool execution without being a black box."""
    status_icon = "[bold green]✓[/bold green]" if success else "[bold red]✗[/bold red]"
    args_summary = ", ".join(f"{k}='{v}'" if isinstance(v, str) and len(str(v)) < 30 else f"{k}={v}" for k, v in list(args.items())[:3])
    console.print(f"{status_icon} [bold cyan]{tool_name}[/bold cyan]({args_summary})")
    if output and ("error" in output.lower() or not success):
        console.print(f"  [dim red]↳ {output[:150]}[/dim red]")
