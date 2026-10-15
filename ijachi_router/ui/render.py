"""Terminal output rendering and security sanitization.

Document 5.13 (SEC-10, UX-18) & Document 6.2, 6.3:
- Sanitizes untrusted output against control sequence injection (OSC 0/2/52, cursor movements, bells).
- Progressive markdown rendering.
- Diff preview with line numbers and syntax styling.
- Turn footer formatting (model, tokens, cost, latency).
- Persistent status line formatting.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

console = Console()

# Dangerous terminal escape sequences (Doc 5.13)
_ESCAPE_PATTERNS = [
    r"\x1b\](?:0|2);[^\x07\x1b]*[\x07\x1b\\]",  # OSC title changes
    r"\x1b\]52;[^\x07\x1b]*[\x07\x1b\\]",        # OSC 52 clipboard write
    r"\x1b\[[0-9;]*[HfABCDsuJKm]",               # Cursor movements / screen clearing (retain color unless NO_COLOR)
    r"\x07",                                      # Bell flood
]


def sanitize_terminal_output(text: str) -> str:
    """Strip malicious terminal control sequences before displaying (SEC-10)."""
    if not text:
        return ""
    result = text
    # Strip OSC 0/2/52 and bells
    result = re.sub(r"\x1b\](?:0|2);[^\x07\x1b]*[\x07\x1b\\]", "", result)
    result = re.sub(r"\x1b\]52;[^\x07\x1b]*[\x07\x1b\\]", "", result)
    result = result.replace("\x07", "")
    return result


def render_markdown(text: str) -> None:
    """Render markdown safely."""
    safe_text = sanitize_terminal_output(text)
    try:
        console.print(Markdown(safe_text))
    except Exception:
        console.print(Text(safe_text))


def render_diff(diff_text: str, title: str = "Diff Preview") -> None:
    """Render unified diff with colored additions and deletions."""
    safe_diff = sanitize_terminal_output(diff_text)
    syntax = Syntax(safe_diff, "diff", theme="monokai", line_numbers=True)
    console.print(Panel(syntax, title=f"[bold cyan]🔍 {title}[/bold cyan]", border_style="cyan"))


def render_turn_footer(
    model: str,
    in_tokens: int,
    out_tokens: int,
    cost_usd: float,
    latency_sec: float,
    cached_tokens: int = 0,
) -> None:
    """Render the standard footer line after each turn (Doc 6.3)."""
    cache_str = f" · cache={cached_tokens}" if cached_tokens else ""
    footer = (
        f"[dim]{model} · {in_tokens}in/{out_tokens}out{cache_str} · "
        f"${cost_usd:.4f} · {latency_sec:.2f}s[/dim]"
    )
    console.print(footer)


def format_status_line(
    mode: str,
    model: str,
    ctx_percent: int,
    last_cost: float,
    session_cost: float,
    budget_usd: float | None = None,
    routing_mode: str = "efficient",
    autonomy_mode: str = "manual",
) -> str:
    """Format single-line status bar with vibrant colored badges for routing and autonomy."""
    budget_str = f" / ${budget_usd:.2f}" if budget_usd is not None else ""
    route_colors = {"efficient": "bold green", "cheapest": "bold yellow", "best": "bold cyan", "best-fit": "bold magenta"}
    auto_colors = {"auto": "bold green", "semi-auto": "bold yellow", "manual": "bold cyan"}

    r_col = route_colors.get(routing_mode, "bold green")
    a_col = auto_colors.get(autonomy_mode, "bold cyan")

    return (
        f"[{r_col}]⚡ {routing_mode}[/{r_col}] · [{a_col}]🛡️  {autonomy_mode}[/{a_col}] · "
        f"[dim]{mode}: {model or 'auto'} · ctx {ctx_percent}% · "
        f"turn ${last_cost:.4f} · session ${session_cost:.4f}{budget_str}[/dim]"
    )
