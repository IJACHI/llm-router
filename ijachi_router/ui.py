"""Rich UI Design System & Terminal Aesthetic Engine for ijachi-code.

Provides bold ASCII art banner, neon styling, status pills, and capability badges.
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()

_BANNER_ART = r"""
 ██   ███████   █████    ██████  ██   ██  ██
 ██        ██  ██   ██  ██       ██   ██  ██
 ██        ██  ███████  ██       ███████  ██
 ██   ██   ██  ██   ██  ██       ██   ██  ██
 ██    █████   ██   ██   ██████  ██   ██  ██
"""


def get_neon_banner() -> Panel:
    """Renders high-impact bold ASCII banner for ijachi-code."""
    banner_text = Text(_BANNER_ART, style="bold cyan")
    subtitle = Text("⚡ One Prompt. Best Model. Autonomous Workspace Agent.", style="bold magenta italic")
    combined = Text.assemble(banner_text, "\n", subtitle, justify="center")
    return Panel(
        combined,
        title="[bold yellow]✨ IJACHI CODE ✨[/bold yellow]",
        subtitle="[dim cyan]v1.0.0 • 20 Providers • Autonomous Coding Engine[/dim cyan]",
        border_style="bright_blue",
        padding=(1, 2),
    )


def print_banner() -> None:
    """Print the bold ASCII banner to stdout."""
    console.print(get_neon_banner())


def get_status_pill(active: bool, is_free: bool = False) -> str:
    """Return a styled status pill badge."""
    if is_free:
        return "[bold white on dark_blue] ⚪ LOCAL FREE [/bold white on dark_blue]"
    elif active:
        return "[bold white on green] 🟢 ACTIVE [/bold white on green]"
    else:
        return "[white on red] 🔴 UNSET [/white on red]"


def get_badge(tag: str) -> str:
    """Return a styled capability badge."""
    tag_clean = tag.lower().strip()
    if "code" in tag_clean:
        return "[bold white on blue] 💻 CODE [/bold white on blue]"
    elif "reasoning" in tag_clean or "math" in tag_clean:
        return "[bold white on magenta] 🧠 REASONING [/bold white on magenta]"
    elif "fast" in tag_clean or "1800" in tag_clean:
        return "[bold black on yellow] ⚡ ULTRA-FAST [/bold black on yellow]"
    elif "summary" in tag_clean or "qa" in tag_clean:
        return "[bold white on dark_green] 📝 SUMMARY [/bold white on dark_green]"
    else:
        return f"[dim white on grey23] {tag.upper()} [/dim white on grey23]"
