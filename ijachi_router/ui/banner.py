"""High-impact bold ASCII art and branding for ijachi and ijachi-code."""

from __future__ import annotations

from rich.panel import Panel
from rich.text import Text

# Clean, solid, human-readable bold sans-serif block font for IJACHI
_BANNER_ART = r"""
  █████       ██████     ███████     ██████    ███   ███    █████
   ███          ███     ███   ███   ███   ██   ███   ███     ███ 
   ███          ███     █████████   ███        █████████     ███ 
   ███     ██   ███     ███   ███   ███   ██   ███   ███     ███ 
  █████     ██████      ███   ███    ██████    ███   ███    █████
""".strip("\n")


def get_neon_banner() -> Panel:
    """Renders high-impact bold ASCII banner for ijachi-code."""
    banner_text = Text(_BANNER_ART, style="bold cyan")
    subtitle = Text("⚡ One Prompt. Best Model. Autonomous Workspace Agent.", style="bold magenta italic")
    combined = Text.assemble(banner_text, "\n\n", subtitle, justify="center")
    return Panel(
        combined,
        title="[bold yellow]✨ IJACHI CODE ✨[/bold yellow]",
        subtitle="[dim cyan]v1.0.0 • 20 Providers • Autonomous Coding Engine[/dim cyan]",
        border_style="bright_blue",
        padding=(1, 2),
    )
