"""Rich UI Design System & Terminal Aesthetic Engine for ijachi-code.

Provides neon gradient banners, double-bordered rounded panels, glowing status pills,
capability badges, dynamic micro-animations, built-in themes, and the status bar.

Themes
------
- dark       : Default cyan/magenta neon (original ijachi-code look)
- light      : Black-on-white, suitable for light terminal backgrounds
- ansi       : Pure ANSI 16-color, compatible with all terminals
- accessible : High-contrast sequential output for screen readers
- auto       : Follows terminal COLORFGBG hint; falls back to 'dark'

Usage
-----
::

    from ijachi_router.ui import set_theme, print_banner, get_status_pill
    set_theme("dark")
    print_banner()
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from rich.console import Console
from rich.panel import Panel
from rich.style import Style
from rich.text import Text
from rich.table import Table
from rich.theme import Theme


# ---------------------------------------------------------------------------
# Theme definitions
# ---------------------------------------------------------------------------

ThemeName = Literal["dark", "light", "ansi", "accessible", "auto"]

_THEMES: dict[str, Theme] = {
    "dark": Theme({
        "banner":         "bold cyan",
        "banner.sub":     "bold magenta italic",
        "banner.border":  "bright_blue",
        "banner.title":   "bold yellow",
        "banner.version": "dim cyan",
        "status.active":  "bold white on green",
        "status.unset":   "white on red",
        "status.free":    "bold white on dark_blue",
        "tool.output":    "dim yellow",
        "user.label":     "bold bright_blue",
        "assistant.label":"bold bright_green",
        "info":           "dim cyan",
        "warning":        "bold yellow",
        "error":          "bold red",
        "success":        "bold green",
    }),
    "light": Theme({
        "banner":         "bold blue",
        "banner.sub":     "bold dark_orange italic",
        "banner.border":  "blue",
        "banner.title":   "bold dark_orange",
        "banner.version": "dim black",
        "status.active":  "bold white on dark_green",
        "status.unset":   "bold white on dark_red",
        "status.free":    "bold black on blue",
        "tool.output":    "dark_orange",
        "user.label":     "bold blue",
        "assistant.label":"bold dark_green",
        "info":           "dim black",
        "warning":        "dark_orange",
        "error":          "dark_red",
        "success":        "dark_green",
    }),
    "ansi": Theme({
        # Restrict to basic 8/16 ANSI colors — works in all terminals
        "banner":         "bold",
        "banner.sub":     "bold italic",
        "banner.border":  "",
        "banner.title":   "bold",
        "banner.version": "dim",
        "status.active":  "bold",
        "status.unset":   "bold",
        "status.free":    "bold",
        "tool.output":    "dim",
        "user.label":     "bold",
        "assistant.label":"bold",
        "info":           "dim",
        "warning":        "bold",
        "error":          "bold",
        "success":        "bold",
    }),
    "accessible": Theme({
        # High-contrast sequential output — designed for screen readers
        "banner":         "bold",
        "banner.sub":     "bold",
        "banner.border":  "",
        "banner.title":   "bold",
        "banner.version": "",
        "status.active":  "bold",
        "status.unset":   "bold",
        "status.free":    "bold",
        "tool.output":    "",
        "user.label":     "bold",
        "assistant.label":"bold",
        "info":           "",
        "warning":        "bold",
        "error":          "bold",
        "success":        "bold",
    }),
}

# ---------------------------------------------------------------------------
# Active theme state
# ---------------------------------------------------------------------------

_active_theme_name: str = "dark"
_console: Console = Console(theme=_THEMES["dark"])


def _detect_auto_theme() -> str:
    """Detect whether the terminal has a light or dark background.

    Uses the COLORFGBG environment variable (set by most terminals) where
    a light background produces a high background number (>= 8).

    Returns:
        'light' or 'dark'.
    """
    colorfgbg = os.environ.get("COLORFGBG", "")
    if colorfgbg:
        parts = colorfgbg.split(";")
        try:
            bg = int(parts[-1])
            return "light" if bg >= 8 else "dark"
        except (ValueError, IndexError):
            pass
    return "dark"


def set_theme(name: str) -> str:
    """Switch the active UI theme globally.

    Args:
        name: Theme name — one of 'dark', 'light', 'ansi', 'accessible', 'auto'.

    Returns:
        The resolved theme name that was applied.
    """
    global _active_theme_name, _console

    resolved = name
    if name == "auto":
        resolved = _detect_auto_theme()

    theme = _THEMES.get(resolved, _THEMES["dark"])
    _active_theme_name = resolved
    _console = Console(theme=theme)
    return resolved


def get_current_theme() -> str:
    """Return the name of the currently active theme.

    Returns:
        Theme name string (e.g. 'dark').
    """
    return _active_theme_name


def list_themes() -> list[str]:
    """Return the names of all available themes.

    Returns:
        Sorted list of theme name strings.
    """
    return sorted(_THEMES.keys()) + ["auto"]


# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------

_BANNER_ART = r"""
 ██   ███████   █████    ██████  ██   ██  ██
 ██        ██  ██   ██  ██       ██   ██  ██
 ██        ██  ███████  ██       ███████  ██
 ██   ██   ██  ██   ██  ██       ██   ██  ██
 ██    █████   ██   ██   ██████  ██   ██  ██
"""

# Application metadata shown in the welcome card
_APP_VERSION = "v1.0.0"
_APP_TAGLINE = "⚡ One Prompt. Best Model. Zero Watermarks. OWASP Secured."

# Quick onboarding tips
_TIPS = [
    "Type /help for slash commands and keybindings",
    "Type /init to generate a CLAUDE.md context file",
    "Use @filename for file-path autocomplete",
    "Press Ctrl+T to toggle the live task checklist",
    "Press Ctrl+O to open the transcript viewer",
]

# In-app release feed (mirrors README highlights)
_RELEASE_NOTES: list[tuple[str, str]] = [
    ("v1.0.0", "Live terminal UI: task panels, diffs, telemetry, plan mode"),
    ("v0.9.5", "20-provider routing with real streaming & budget failover"),
    ("v0.9.0", "Agentic workspace tools, skill system, and memory layers"),
    ("v0.8.0", "Cost estimates, stats dashboard, and Pro REST gateway"),
]


def get_neon_banner() -> Panel:
    """Render the high-impact neon gradient banner for ijachi-code.

    Returns:
        A Rich Panel containing the ASCII banner art and subtitle.
    """
    banner_text = Text(_BANNER_ART, style="banner")
    subtitle = Text(_APP_TAGLINE, style="banner.sub")
    combined = Text.assemble(banner_text, "\n", subtitle, justify="center")
    return Panel(
        combined,
        title="[banner.title]✨ IJACHI AGENTIC PLATFORM ✨[/banner.title]",
        subtitle=f"[banner.version]{_APP_VERSION} • 20 Providers • Skills • 100% Test Coverage[/banner.version]",
        border_style="banner.border",
        padding=(1, 2),
    )


def print_banner() -> None:
    """Print the neon banner to stdout using the active theme."""
    _console.print(get_neon_banner())


def get_welcome_card(
    model: str = "auto",
    billing: str = "API Usage Billing",
    workspace: str | None = None,
) -> Panel:
    """Render the branded welcome card with metadata and tips.

    Args:
        model: Active model label (e.g. 'kimi-k2.7-code:cloud').
        billing: Billing engine label.
        workspace: Current working directory. Defaults to ``Path.cwd()``.

    Returns:
        A Rich Panel combining banner, metadata, tips, and release notes.
    """
    if workspace is None:
        workspace = str(Path.cwd())
    home = str(Path.home())
    workspace_display = workspace.replace(home, "~")

    banner = get_neon_banner()

    meta_table = Table(show_header=False, box=None, padding=(0, 1))
    meta_table.add_column(style="info", width=18)
    meta_table.add_column(style="white")
    meta_table.add_row("Version", _APP_VERSION)
    meta_table.add_row("Active Model", model)
    meta_table.add_row("Billing", billing)
    meta_table.add_row("Workspace", workspace_display)

    tips = Text.from_markup("\n".join(f"  • {tip}" for tip in _TIPS))

    release_table = Table(show_header=True, box=None, padding=(0, 1))
    release_table.add_column("Version", style="bold cyan", width=10)
    release_table.add_column("What's New", style="white")
    for version, note in _RELEASE_NOTES:
        release_table.add_row(version, note)

    body = Text.assemble(
        Text("\n"),
        Text.from_markup("[bold cyan]Session Context[/bold cyan]\n"),
        meta_table,
        Text("\n"),
        Text.from_markup("[bold cyan]Tips & Getting Started[/bold cyan]\n"),
        tips,
        Text("\n"),
        Text.from_markup("[bold cyan]What's New[/bold cyan]\n"),
        release_table,
    )

    return Panel(
        body,
        border_style="banner.border",
        padding=(1, 2),
        title=f"[banner.title]✨ IJACHI AGENTIC PLATFORM ✨[/banner.title]",
        subtitle=f"[banner.version]{_APP_VERSION}[/banner.version]",
    )


def print_welcome_card(
    model: str = "auto",
    billing: str = "API Usage Billing",
    workspace: str | None = None,
) -> None:
    """Print the full welcome card to the terminal."""
    _console.print(get_welcome_card(model=model, billing=billing, workspace=workspace))


def print_status_line(line: str) -> None:
    """Print a telemetry status line with subtle styling."""
    _console.print(f"[dim]{line}[/dim]")


def print_roll_up(line: str) -> None:
    """Print an execution roll-up line."""
    _console.print(f"[bold green]{line}[/bold green]")


# ---------------------------------------------------------------------------
# Status pills & badges
# ---------------------------------------------------------------------------

def get_status_pill(active: bool, is_free: bool = False) -> str:
    """Return a styled status pill badge markup string.

    Args:
        active: True if the provider is configured and active.
        is_free: True if the provider requires no API key (e.g. local Ollama).

    Returns:
        Rich markup string for the status pill.
    """
    if is_free:
        return "[status.free] ⚪ LOCAL FREE [/status.free]"
    elif active:
        return "[status.active] 🟢 ACTIVE [/status.active]"
    else:
        return "[status.unset] 🔴 UNSET [/status.unset]"


def get_badge(tag: str) -> str:
    """Return a styled capability badge markup string.

    Args:
        tag: Raw tag string from model config (e.g. 'code', 'reasoning').

    Returns:
        Rich markup string for the badge.
    """
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


# ---------------------------------------------------------------------------
# Permission mode display
# ---------------------------------------------------------------------------

_PERMISSION_MODE_LABELS: dict[str, str] = {
    "manual":       "⏸ manual",
    "accept-edits": "✏ accept-edits",
    "plan":         "📋 plan",
    "auto":         "⏵⏵ auto",
}


def get_permission_mode_label(mode: str) -> str:
    """Return the display label for a permission/autonomy mode.

    Args:
        mode: One of 'manual', 'accept-edits', 'plan', 'auto'.

    Returns:
        Unicode-decorated label string.
    """
    return _PERMISSION_MODE_LABELS.get(mode, mode)


PERMISSION_MODES: list[str] = ["manual", "accept-edits", "plan", "auto"]


def cycle_permission_mode(current: str) -> str:
    """Cycle to the next permission mode (Shift+Tab behaviour).

    Args:
        current: Current mode name.

    Returns:
        Next mode name in the cycle.
    """
    try:
        idx = PERMISSION_MODES.index(current)
        return PERMISSION_MODES[(idx + 1) % len(PERMISSION_MODES)]
    except ValueError:
        return PERMISSION_MODES[0]


# ---------------------------------------------------------------------------
# Accessibility helpers
# ---------------------------------------------------------------------------

def is_accessible_mode() -> bool:
    """Return True if the accessible theme is currently active.

    Returns:
        True when theme is 'accessible'.
    """
    return _active_theme_name == "accessible"


def accessible_label(role: str, content: str) -> None:
    """Print a sequential accessibility-friendly labeled message.

    In accessible mode, replaces spinners/panels with plain labeled lines.

    Args:
        role: Message role label (e.g. 'you', 'ijachi', 'tool', 'tool_error',
              'permission_required').
        content: The message content to print.
    """
    print(f"{role}: {content}")
