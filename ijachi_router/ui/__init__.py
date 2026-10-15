from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from ijachi_router.ui.prompts import SlashAndFileCompleter, prompt_user_input
from ijachi_router.ui.render import (
    format_status_line,
    render_diff,
    render_markdown,
    render_turn_footer,
    sanitize_terminal_output,
)
from ijachi_router.ui.banner import _BANNER_ART, get_neon_banner
from ijachi_router.ui.repl import InteractiveREPL

console = Console()


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


__all__ = [
    "InteractiveREPL",
    "SlashAndFileCompleter",
    "format_status_line",
    "prompt_user_input",
    "render_diff",
    "render_markdown",
    "render_turn_footer",
    "sanitize_terminal_output",
    "get_neon_banner",
    "print_banner",
    "get_status_pill",
    "get_badge",
    "_BANNER_ART",
]
