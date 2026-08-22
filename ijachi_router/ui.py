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


def get_neon_banner() -> Panel:
    """Render the high-impact neon gradient banner for ijachi-code.

    Returns:
        A Rich Panel containing the ASCII banner art and subtitle.
    """
    banner_text = Text(_BANNER_ART, style="banner")
    subtitle = Text("⚡ One Prompt. Best Model. Zero Watermarks. OWASP Secured.", style="banner.sub")
    combined = Text.assemble(banner_text, "\n", subtitle, justify="center")
    return Panel(
        combined,
        title="[banner.title]✨ IJACHI AGENTIC PLATFORM ✨[/banner.title]",
        subtitle="[banner.version]v1.0.0 • 20 Providers • Skills • 100% Test Coverage[/banner.version]",
        border_style="banner.border",
        padding=(1, 2),
    )


def print_banner() -> None:
    """Print the neon banner to stdout using the active theme."""
    _console.print(get_neon_banner())


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


# ---------------------------------------------------------------------------
# Telemetry & Cost Breakdown Renderers
# ---------------------------------------------------------------------------

def render_route_footer(res, humanize_mode: str = "light") -> None:
    """Render a comprehensive telemetry breakdown footer after a single route call.

    Args:
        res: GenerationResult object containing cost, tokens, and savings.
        humanize_mode: The active humanize mode string.
    """
    if is_accessible_mode():
        saved_str = (
            f" saved=${res.cost_saved_usd:.4f} ({res.savings_pct:.1f}% vs {res.baseline_model})"
            if res.cost_saved_usd > 0
            else ""
        )
        print(
            f"telemetry: model={res.model} provider={res.provider} category={res.category} "
            f"tokens={res.input_tokens}in/{res.output_tokens}out cost=${res.cost_usd:.4f}{saved_str} "
            f"latency={res.latency_s:.2f}s ({res.tokens_per_sec:.1f}tok/s)"
        )
        return

    # Rich formatted breakdown
    cat_badge = get_badge(res.category)
    tok_rate = f"{res.tokens_per_sec:.1f} tok/s" if res.tokens_per_sec > 0 else "-"
    tokens_str = (
        f"[bold white]{res.input_tokens}[/bold white] in / "
        f"[bold white]{res.output_tokens}[/bold white] out "
        f"([dim]{res.total_tokens} total[/dim])"
    )
    cost_str = f"[bold green]${res.cost_usd:.4f}[/bold green]"

    if res.cost_saved_usd > 0:
        savings_str = (
            f"  📉 [bold cyan]Saved: ${res.cost_saved_usd:.4f} "
            f"({res.savings_pct:.1f}% vs {res.baseline_model})[/bold cyan]"
        )
    else:
        savings_str = ""

    summary_text = (
        f"🤖 [bold cyan]{res.model}[/bold cyan] ([dim]{res.provider}[/dim])  "
        f"{cat_badge}  "
        f"🔢 Tokens: {tokens_str}  "
        f"⏱️ [dim]{res.latency_s:.2f}s ({tok_rate})[/dim]\n"
        f"💰 Cost: {cost_str}{savings_str}"
    )

    from rich.panel import Panel
    _console.print(Panel(
        summary_text,
        title="[dim]⚡ Routing & Cost Telemetry[/dim]",
        border_style="dim bright_blue",
        padding=(0, 1),
    ))


def render_agent_breakdown(result) -> None:
    """Render a comprehensive multi-step task telemetry breakdown table.

    Args:
        result: AgentResult object.
    """
    if is_accessible_mode():
        print(
            f"\ntelemetry_summary: steps={len(result.steps)} "
            f"in_tokens={result.total_input_tokens} out_tokens={result.total_output_tokens} "
            f"total_cost=${result.total_cost_usd:.4f} saved=${result.total_cost_saved_usd:.4f} "
            f"latency={result.total_latency_s:.2f}s"
        )
        for s in result.steps:
            action = s.tool_name or "answer"
            print(
                f"  step #{s.step_number}: {action} model={s.model_used} "
                f"tokens={s.input_tokens}/{s.output_tokens} cost=${s.cost_usd:.4f}"
            )
        return

    _console.print()
    try:
        _console.print(result.get_breakdown_table())
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Real-Time Animated Status Spinner & Progress Helpers
# ---------------------------------------------------------------------------

from contextlib import contextmanager
from typing import Any, Generator


class _NoOpStatus:
    """Fallback status controller for accessible or non-interactive environments."""
    def update(self, text: str) -> None:
        if is_accessible_mode():
            print(f"status: {text}")


@contextmanager
def status_spinner(initial_message: str = "Thinking...") -> Generator[Any, None, None]:
    """Context manager that displays an animated Rich spinner during long operations.

    In accessibility mode, outputs plain text lines instead of ANSI animation.

    Args:
        initial_message: The initial status text to display next to the spinner.

    Yields:
        A status object that can be updated with `status.update("New message...")`.
    """
    if is_accessible_mode():
        print(f"status: {initial_message}")
        yield _NoOpStatus()
        return

    try:
        with _console.status(f"[bold cyan]{initial_message}[/bold cyan]", spinner="dots") as status:
            yield status
    except Exception:
        yield _NoOpStatus()


def live_status_message(message: str, style: str = "dim cyan") -> None:
    """Print an immediate live status notice."""
    if is_accessible_mode():
        print(f"status: {message}")
    else:
        _console.print(f"[{style}]⚡ {message}[/{style}]")


def get_permission_mode_label(mode: str) -> str:
    """Return the display label for a permission/autonomy mode.

    Args:
        mode: One of 'manual', 'accept-edits', 'plan', 'auto'.

    Returns:
        Unicode-decorated label string.
    """
    _labels: dict[str, str] = {
        "manual":       "⏸ manual",
        "accept-edits": "✏ accept-edits",
        "plan":         "📋 plan",
        "auto":         "⏵⏵ auto",
    }
    return _labels.get(mode, mode)
