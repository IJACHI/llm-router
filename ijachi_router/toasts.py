"""Toast notification system for ijachi-code.

Provides a simple in-session message queue with clickable-style badges.
Toasts are surfaced above the prompt field and in the bottom toolbar.

Usage
-----
::

    from ijachi_router.toasts import toast_manager
    toast_manager.push("Task complete ✓", level="success")
    toast_manager.render_badge()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.text import Text


class ToastLevel(Enum):
    """Severity levels for toast notifications."""

    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class Toast:
    """A single toast notification."""

    message: str
    level: ToastLevel = ToastLevel.INFO
    metadata: dict[str, Any] = field(default_factory=dict)


class ToastManager:
    """Singleton toast queue.

    The module-level ``toast_manager`` instance is the intended public API.
    """

    _instance: ToastManager | None = None

    def __new__(cls) -> ToastManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._reset()
        return cls._instance

    def _reset(self) -> None:
        """Clear the toast queue (mostly useful for tests)."""
        self.toasts: list[Toast] = []
        self._console = Console()

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------

    def push(self, message: str, level: str = "info", **metadata: Any) -> Toast:
        """Add a toast to the queue."""
        toast = Toast(
            message=message,
            level=ToastLevel(level.lower()),
            metadata=metadata,
        )
        self.toasts.append(toast)
        return toast

    def pop(self) -> Toast | None:
        """Remove and return the oldest unread toast, if any."""
        if not self.toasts:
            return None
        return self.toasts.pop(0)

    def clear(self) -> None:
        """Clear all pending toasts."""
        self.toasts.clear()

    @property
    def pending_count(self) -> int:
        """Number of unread toasts."""
        return len(self.toasts)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render_badge(self) -> str:
        """Return a short Rich markup badge string for the status bar."""
        n = len(self.toasts)
        if n == 0:
            return ""
        if n == 1:
            return f"[bold yellow]1 message (click ↓)[/bold yellow]"
        return f"[bold yellow]{n} messages (click ↓)[/bold yellow]"

    def print_pending(self, limit: int = 5) -> None:
        """Render the most recent pending toasts inline."""
        if not self.toasts:
            return
        for toast in self.toasts[-limit:]:
            self._print_one(toast)
        self.clear()

    def _print_one(self, toast: Toast) -> None:
        style_map = {
            ToastLevel.INFO: "cyan",
            ToastLevel.SUCCESS: "green",
            ToastLevel.WARNING: "yellow",
            ToastLevel.ERROR: "red",
        }
        color = style_map.get(toast.level, "white")
        icon_map = {
            ToastLevel.INFO: "ℹ",
            ToastLevel.SUCCESS: "✅",
            ToastLevel.WARNING: "⚠",
            ToastLevel.ERROR: "✗",
        }
        icon = icon_map.get(toast.level, "•")
        self._console.print(
            Panel(
                Text(toast.message),
                title=f"[bold {color}]{icon} {toast.level.value.upper()}[/bold {color}]",
                border_style=color,
                padding=(0, 1),
            )
        )


# Module-level singleton
toast_manager = ToastManager()
