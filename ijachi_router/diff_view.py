"""Live unified diff renderer for ijachi-code.

Renders exact in-terminal diffs with line numbers, surrounding context,
and red/green highlight blocks. Used by edit approval flows and by any
component that wants to show what changed.

Usage
-----
::

    from ijachi_router.diff_view import DiffRenderer
    renderer = DiffRenderer()
    panel = renderer.render(old_text, new_text, path="config.py")
    renderer.print(panel)
"""

from __future__ import annotations

import difflib
from typing import Iterator

from rich.console import Console, ConsoleRenderable
from rich.panel import Panel
from rich.text import Text


class DiffRenderer:
    """Render unified diffs in the terminal.

    Args:
        accessible: If True, render as plain text instead of Rich panels.
    """

    def __init__(self, accessible: bool = False) -> None:
        self.accessible = accessible
        self.console = Console()

    def render(
        self,
        old_text: str,
        new_text: str,
        path: str,
        context_lines: int = 3,
    ) -> ConsoleRenderable | str:
        """Return a Rich renderable (or plain string) of the unified diff."""
        diff_lines = self.unified_diff_lines(old_text, new_text, path, context_lines)
        if self.accessible:
            return "\n".join(diff_lines)

        text = Text()
        for line in diff_lines:
            if line.startswith("+") and not line.startswith("+++"):
                text.append(line + "\n", style="bold green")
            elif line.startswith("-") and not line.startswith("---"):
                text.append(line + "\n", style="bold red")
            elif line.startswith("@@"):
                text.append(line + "\n", style="cyan")
            else:
                text.append(line + "\n", style="dim")

        return Panel(
            text,
            title=f"[bold cyan]📝 Diff: {path}[/bold cyan]",
            subtitle=f"[dim]{self._summarize(old_text, new_text)}[/dim]",
            border_style="bright_blue",
            padding=(0, 1),
        )

    def print(
        self,
        old_text: str,
        new_text: str,
        path: str,
        context_lines: int = 3,
    ) -> None:
        """Render and print the diff directly to the terminal."""
        renderable = self.render(old_text, new_text, path, context_lines)
        if isinstance(renderable, str):
            print(renderable)
        else:
            self.console.print(renderable)

    def unified_diff_lines(
        self,
        old_text: str,
        new_text: str,
        path: str,
        context_lines: int = 3,
    ) -> list[str]:
        """Generate a clean unified diff as a list of text lines.

        Args:
            old_text: Original file content.
            new_text: Modified file content.
            path: File path used in the diff header.
            context_lines: Number of context lines around each hunk.

        Returns:
            List of diff lines including header and hunks.
        """
        old_lines = old_text.splitlines()
        new_lines = new_text.splitlines()
        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
            n=context_lines,
        )
        return list(diff)

    @staticmethod
    def _summarize(old_text: str, new_text: str) -> str:
        """Return a short addition/removal summary."""
        old_count = len(old_text.splitlines())
        new_count = len(new_text.splitlines())
        added = max(0, new_count - old_count)
        removed = max(0, old_count - new_count)
        return f"Added {added} line(s), removed {removed} line(s)"


class InlineDiff:
    """Very small helper to show a single inline old/new pair.

    Used when a full unified diff is too heavy (e.g. one-line edits).
    """

    def __init__(self, accessible: bool = False) -> None:
        self.accessible = accessible
        self.console = Console()

    def print(self, old: str, new: str, label: str = "Change") -> None:
        """Print an inline old → new pair."""
        if self.accessible:
            print(f"{label}:")
            print(f"  - {old}")
            print(f"  + {new}")
            return
        self.console.print(f"[bold yellow]{label}[/bold yellow]")
        self.console.print(f"[red]- {old}[/red]")
        self.console.print(f"[green]+ {new}[/green]")


def render_edit_approval(
    old_text: str,
    new_text: str,
    path: str,
    accessible: bool = False,
) -> None:
    """Convenience helper: render the diff for an edit approval prompt."""
    DiffRenderer(accessible=accessible).print(old_text, new_text, path)
